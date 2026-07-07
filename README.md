# FIOT Ambulance Bot — Smart Traffic Light Priority System

A Telegram bot that coordinates emergency ambulance dispatch between patients and drivers, and (eventually) triggers a physical traffic light override via an Arduino Uno + ESP01.

Built for FIOT Group 10 — *Smart Traffic Light Control: Ambulance Prioritization System*.

---

## How it works

The bot has two roles, but there's no manual "switch mode" — your role is decided automatically based on your Telegram account ID:

- **Patients** — anyone messaging the bot whose ID is *not* in `DRIVER_CHAT_IDS`
- **Drivers** — anyone whose ID *is* listed in `DRIVER_CHAT_IDS`

### Patient flow

| Step | Action |
|---|---|
| 1 | Patient sends `/emergency` |
| 2 | Bot asks for a photo to verify the incident |
| 3 | Patient sends a photo |
| 4 | Case is created and broadcast to every registered driver |
| 5 | Patient receives push updates as the case progresses (dispatched → picked up → on the way → arrived) |
| — | Patient can send `/cancel` any time before a driver takes the case |

### Driver flow

| Step | Action |
|---|---|
| 1 | Driver receives the patient's photo with a **🚑 Take Case** button |
| 2 | First driver to tap it locks the case — gets a "Case confirmed ✅" popup |
| 3 | All other drivers' copies auto-update to "Already taken" |
| 4 | Driver is sent a live status menu: **Picked Up Patient → On The Way → Case Closed (Arrived)** |
| 5 | Each tap notifies the patient in real time and advances the case |
| 6 | On **Case Closed**, the case is removed from memory and the flow ends |

### Case states

```
AWAITING_PHOTO → AWAITING_DRIVER → TAKEN → PICKED_UP → ON_WAY → CLOSED
```

Each case is tracked independently, so multiple emergencies can run at the same time without interfering with each other.

---

## Project structure

```
FIOT Ambulance Bot/
├── ambulance_bot.py     # main bot logic
├── config.py            # BOT_TOKEN (kept out of Git — see .gitignore)
├── .gitignore
└── README.md
```

---

## Setup

1. Install dependencies:
   ```
   pip install python-telegram-bot
   ```
2. Create `config.py` (this file is git-ignored, never commit it):
   ```python
   BOT_TOKEN = "your-token-from-@BotFather"
   ```
3. In `ambulance_bot.py`, set `DRIVER_CHAT_IDS` to the Telegram user IDs of your ambulance drivers:
   ```python
   DRIVER_CHAT_IDS = [
       5043247672,
   ]
   ```
   Get a user's ID by having them message **@userinfobot** on Telegram.
4. Run it:
   ```
   python ambulance_bot.py
   ```

### Bot commands

| Command | Who | Description |
|---|---|---|
| `/start` | Everyone | Greeting, tells you which role you're in |
| `/emergency` | Patients | Starts a new emergency case |
| `/cancel` | Patients | Cancels an active case (only before a driver takes it) |

---

## 🚦 Arduino Uno Integration (TODO — fill this in as you build it)

This is where the software dispatch logic hooks into the physical traffic light hardware described in the block diagram / flowchart slides.

**Hardware recap (from the presentation):**
- **Inputs:** WiFi module (ESP01), push button (manual override)
- **Outputs:** LED (traffic light), buzzer, LCD display, 7-segment display
- **Pipeline:** Telegram Bot → Cloud → ESP01 polls cloud → Arduino Uno → traffic light

**Flowchart stages to wire up:**

- [ ] `Normal Traffic Light Mode` — default cycling, LCD shows "NORMAL"
- [ ] `Manual Override` check — push button input read each loop
- [ ] `Check for Telegram Bot response` — ESP01 polls the cloud/bot for an active case
- [ ] `Priority Activate` — triggered when a case reaches `TAKEN` (or your chosen status)
- [ ] `Activate Traffic Light override` — force green on ambulance's approach
- [ ] `LCD Display Override Mode` — show "PRIORITY ACTIVE"
- [ ] `Maintain Green Light for 10 seconds`
- [ ] `7-Segment displays countdown`
- [ ] `Buzzer beeps for last 5 seconds`
- [ ] Return to `Normal Traffic Light Mode`

**Where this plugs into `ambulance_bot.py`:**

The natural hook point is inside `button_handler()`, in the branches where `case["status"]` changes (`take`, `pickup`, `onway`, `close`). That's where you'd send a serial command to the Arduino, e.g.:

```python
# near the top of the file
# import serial
# arduino = serial.Serial('COM3', 9600, timeout=1)

# inside button_handler(), right after case["status"] = STATUS_TAKEN:
# arduino.write(b'PRIORITY_ON\n')

# inside button_handler(), right after case["status"] = STATUS_CLOSED:
# arduino.write(b'PRIORITY_OFF\n')
```

On the Arduino side, you'd read these commands over serial and drive the flowchart's `Priority Activate` branch (auto route sequence vs. manual driver trigger via the push button) — add your own notes/pseudocode below as you implement it:

```
// --- Your Arduino-side logic notes go here ---
//
// e.g.
// void loop() {
//   if (Serial.available()) {
//     String cmd = Serial.readStringUntil('\n');
//     if (cmd == "PRIORITY_ON") { ... }
//     if (cmd == "PRIORITY_OFF") { ... }
//   }
//   checkManualOverrideButton();
//   updateLCD();
//   updateSevenSegmentCountdown();
// }
```

---

## Security notes

- `BOT_TOKEN` lives in `config.py`, which is excluded from Git via `.gitignore` — never commit a real token.
- If a token is ever accidentally shared or pushed, rotate it immediately via **@BotFather → `/mybots` → API Token → Revoke current token**.
