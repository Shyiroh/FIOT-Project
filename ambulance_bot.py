import os
import itertools
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = "8626343986:AAEPhk8PjXqA48FwmkMN_4U4x3fOMnrrijo"

DRIVER_CHAT_IDS = [
    5043247672
    # 123456789,
    # 987654321,
]

case_id_counter = itertools.count(1)

# case_id -> {
#   "user_id": int, "user_name": str,
#   "status": str,               # see STATUS_* constants below
#   "driver_id": int | None,
#   "driver_name": str | None,
#   "broadcast": {chat_id: message_id}  # driver "take case" cards, for cleanup
#   "menu_chat_id": int | None, "menu_msg_id": int | None,
# }
cases = {}

# user_id -> case_id, tracks the patient's currently open case
active_case_by_user = {}

STATUS_AWAITING_PHOTO = "AWAITING_PHOTO"
STATUS_AWAITING_DRIVER = "AWAITING_DRIVER"
STATUS_TAKEN = "TAKEN"
STATUS_PICKED_UP = "PICKED_UP"
STATUS_ON_WAY = "ON_WAY"
STATUS_CLOSED = "CLOSED"


def is_driver(user_id: int) -> bool:
    return user_id in DRIVER_CHAT_IDS


# ===================== USER SIDE =====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_driver(update.effective_user.id):
        await update.message.reply_text(
            "🚑 Driver mode active. You'll be pinged here whenever a new case comes in."
        )
    else:
        await update.message.reply_text(
            "Hi, I'm the emergency dispatch bot.\n\n"
            "If you need an ambulance, send /emergency and I'll ask you to "
            "confirm with a photo, then get a driver on the way."
        )


async def emergency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if is_driver(user.id):
        await update.message.reply_text("You're registered as a driver, not a patient on this bot.")
        return

    if active_case_by_user.get(user.id) is not None:
        await update.message.reply_text("You already have an active case. Send /cancel to withdraw it.")
        return

    case_id = next(case_id_counter)
    cases[case_id] = {
        "user_id": user.id,
        "user_name": user.full_name,
        "status": STATUS_AWAITING_PHOTO,
        "driver_id": None,
        "driver_name": None,
        "broadcast": {},
        "menu_chat_id": None,
        "menu_msg_id": None,
    }
    active_case_by_user[user.id] = case_id

    await update.message.reply_text(
        "🚨 Emergency started.\n\n"
        "Please send a photo now to verify the incident so we can dispatch an ambulance."
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    case_id = active_case_by_user.get(user.id)

    if case_id is None:
        await update.message.reply_text("You don't have an active case.")
        return

    case = cases[case_id]
    if case["status"] in (STATUS_TAKEN, STATUS_PICKED_UP, STATUS_ON_WAY):
        await update.message.reply_text(
            "A driver has already taken this case, so it can no longer be cancelled from your side. "
            "Please contact them directly if needed."
        )
        return

    # Pull down any "Take Case" cards still sitting in driver chats
    for chat_id, msg_id in case["broadcast"].items():
        try:
            await context.bot.edit_message_caption(
                chat_id=chat_id, message_id=msg_id, caption="❌ Case cancelled by patient."
            )
        except Exception:
            pass

    del cases[case_id]
    del active_case_by_user[user.id]
    await update.message.reply_text("Emergency cancelled.")


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    case_id = active_case_by_user.get(user.id)

    if case_id is None or cases[case_id]["status"] != STATUS_AWAITING_PHOTO:
        return  # not something we're waiting on right now, ignore

    case = cases[case_id]
    photo_file_id = update.message.photo[-1].file_id
    case["status"] = STATUS_AWAITING_DRIVER

    await update.message.reply_text(
        "✅ Incident verified. Broadcasting to ambulance drivers now — stand by."
    )

    if not DRIVER_CHAT_IDS:
        await update.message.reply_text(
            "⚠️ No drivers are currently registered with the bot. Please seek help by other means."
        )
        return

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🚑 Take Case", callback_data=f"take_{case_id}")]]
    )
    for driver_chat_id in DRIVER_CHAT_IDS:
        try:
            msg = await context.bot.send_photo(
                chat_id=driver_chat_id,
                photo=photo_file_id,
                caption=f"🚨 New emergency — Case #{case_id}\nPatient: {case['user_name']}",
                reply_markup=keyboard,
            )
            case["broadcast"][driver_chat_id] = msg.message_id
        except Exception:
            pass


# ===================== DRIVER SIDE =====================

def driver_menu_keyboard(status: str, case_id: int) -> InlineKeyboardMarkup:
    if status == STATUS_TAKEN:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("🚑 Picked Up Patient", callback_data=f"pickup_{case_id}")]]
        )
    if status == STATUS_PICKED_UP:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("🛣️ On The Way", callback_data=f"onway_{case_id}")]]
        )
    if status == STATUS_ON_WAY:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("🏥 Case Closed (Arrived)", callback_data=f"close_{case_id}")]]
        )
    return InlineKeyboardMarkup([])


STATUS_LABEL = {
    STATUS_TAKEN: "🚑 Case taken — head to the patient.",
    STATUS_PICKED_UP: "🧍 Patient picked up.",
    STATUS_ON_WAY: "🛣️ En route to hospital.",
    STATUS_CLOSED: "🏥 Case closed — arrived at hospital.",
}

PATIENT_UPDATE = {
    STATUS_TAKEN: "🚑 An ambulance driver has taken your case and is on the way to you.",
    STATUS_PICKED_UP: "🧍 The ambulance has picked you up.",
    STATUS_ON_WAY: "🛣️ You're on the way to the hospital.",
    STATUS_CLOSED: "🏥 You have arrived at the hospital.",
}


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    driver = query.from_user

    action, _, case_id_str = data.partition("_")
    case_id = int(case_id_str)
    case = cases.get(case_id)

    if case is None:
        await query.answer("This case no longer exists.", show_alert=True)
        return

    # ---- Taking a case ----
    if action == "take":
        if case["status"] != STATUS_AWAITING_DRIVER:
            await query.answer("Already taken by another driver.", show_alert=True)
            try:
                await query.edit_message_caption(caption=query.message.caption + "\n\n⛔ Already taken.")
            except Exception:
                pass
            return

        case["status"] = STATUS_TAKEN
        case["driver_id"] = driver.id
        case["driver_name"] = driver.full_name
        await query.answer("Case confirmed ✅", show_alert=True)

        # Update this driver's card
        await query.edit_message_caption(
            caption=f"🚑 Case #{case_id} — CONFIRMED, you're on it."
        )
        # Pull the offer from every other driver
        for chat_id, msg_id in case["broadcast"].items():
            if chat_id == driver.id:
                continue
            try:
                await context.bot.edit_message_caption(
                    chat_id=chat_id, message_id=msg_id,
                    caption=f"🚑 Case #{case_id} — taken by another driver."
                )
            except Exception:
                pass

        # Send the driver their live status menu
        menu = await context.bot.send_message(
            chat_id=driver.id,
            text=f"Case #{case_id} — {STATUS_LABEL[STATUS_TAKEN]}",
            reply_markup=driver_menu_keyboard(STATUS_TAKEN, case_id),
        )
        case["menu_chat_id"] = menu.chat_id
        case["menu_msg_id"] = menu.message_id

        await context.bot.send_message(case["user_id"], PATIENT_UPDATE[STATUS_TAKEN])
        return

    # ---- Progressing a case (pickup / onway / close) ----
    if case["driver_id"] != driver.id:
        await query.answer("This isn't your case.", show_alert=True)
        return

    next_status = {"pickup": STATUS_PICKED_UP, "onway": STATUS_ON_WAY, "close": STATUS_CLOSED}.get(action)
    if next_status is None:
        await query.answer()
        return

    case["status"] = next_status
    await query.answer(STATUS_LABEL[next_status], show_alert=True)
    await context.bot.send_message(case["user_id"], PATIENT_UPDATE[next_status])

    if next_status == STATUS_CLOSED:
        await query.edit_message_text(f"Case #{case_id} — {STATUS_LABEL[STATUS_CLOSED]}")
        active_case_by_user.pop(case["user_id"], None)
        del cases[case_id]
    else:
        await query.edit_message_text(
            f"Case #{case_id} — {STATUS_LABEL[next_status]}",
            reply_markup=driver_menu_keyboard(next_status, case_id),
        )


# ===================== MAIN =====================

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("emergency", emergency))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
