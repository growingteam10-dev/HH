import logging
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ================= CONFIGURATION =================
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"
CHANNEL_ID = "-1001234567890"  # Primary/Default Channel ID (Admin ID & extra channels configured inside)
# =================================================

# --- Quick Setup Inside Code (No Database Needed) ---
ADMIN_ID = 123456789  # Replace with your numeric Telegram User ID (get it from @userinfobot)
AROLINKS_API_KEY = "YOUR_AROLINKS_API_KEY"  # Get from arolinks.com -> Tools -> Developer API
PREMIUM_LINK = "https://t.me/+xpELQlAlL01mMTU1"

# Your Backup Channels (Button Label : Invite Link)
BACKUP_CHANNELS = {
    "Backup 1": "https://t.me/+YourBackupLink1",
    "Backup 2": "https://t.me/+YourBackupLink2",
    "Backup 3": "https://t.me/+YourBackupLink3",
}

# Your Target Posting Channels (Button Label : Channel Chat ID)
TARGET_CHANNELS = {
    "Main Channel": CHANNEL_ID,
    "Second Channel": "-1009876543210",
    "Third Channel": "-1001122334455",
}

# Logging with Date & Time
logging.basicConfig(
    format="%(asctime)s - [PROPHET] - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Temporary in-memory state for your active post
user_sessions = {}


def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


def shorten_arolink(long_url: str) -> str:
    """Automatically shortens URL using Arolinks API."""
    if not AROLINKS_API_KEY or AROLINKS_API_KEY == "YOUR_AROLINKS_API_KEY":
        return long_url
    try:
        api_url = f"https://arolinks.com/api?api={AROLINKS_API_KEY}&url={long_url}"
        response = requests.get(api_url, timeout=10).json()
        if response.get("status") == "success":
            return response.get("shortenedUrl", long_url)
    except Exception as e:
        logger.error(f"Arolinks API Error: {e}")
    return long_url


async def safe_delete(message):
    """Auto-deletes DM messages to keep chat clean."""
    try:
        await message.delete()
    except Exception:
        pass


# --- COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("Access Denied")
        logger.warning(f"Unauthorized /start attempt by {user.id} ({user.username})")
        return

    logger.info(f"Admin {user.id} started the bot.")
    await update.message.reply_text(
        "Welcome to Prophet 👑 Send any file, I will auto upload it"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Access Denied")
        return

    help_text = (
        "👑 **PROPHET WORKFLOW GUIDE**\n\n"
        "1️⃣ **Forward your post** (Photo/Video + Caption) from your Database Channel.\n"
        "2️⃣ **Send the File Link** from `@Otaku_Hentai_Official_bot` (PROPHET will auto-shorten it via Arolinks).\n"
        "3️⃣ **Tap a Backup Channel** button.\n"
        "4️⃣ **Select 2 Target Channels** and hit **🚀 PUBLISH POST**.\n\n"
        "All your DM inputs are auto-deleted after processing!"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


# --- STEP 1: RECEIVE POST FROM DATABASE CHANNEL ---
async def handle_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("Access Denied")
        return

    msg = update.message
    file_id = None
    media_type = None

    if msg.photo:
        file_id = msg.photo[-1].file_id
        media_type = "photo"
    elif msg.video:
        file_id = msg.video.file_id
        media_type = "video"
    elif msg.document:
        file_id = msg.document.file_id
        media_type = "document"
    else:
        await msg.reply_text("❌ Please forward a post with a Photo, Video, or File.")
        return

    caption = msg.caption or ""
    user_sessions[user.id] = {
        "step": "WAITING_LINK",
        "file_id": file_id,
        "media_type": media_type,
        "caption": caption,
        "short_link": "",
        "backup_link": "",
        "selected_channels": [],
    }

    await safe_delete(msg)
    prompt = await context.bot.send_message(
        chat_id=user.id,
        text="✅ **Post Captured!**\n\nNow send the shareable link from `@Otaku_Hentai_Official_bot` (I will auto-shorten it via Arolinks):",
        parse_mode="Markdown",
    )
    user_sessions[user.id]["last_bot_msg"] = prompt.message_id
    logger.info("Step 1 complete: Post captured from admin.")


# --- STEP 2: RECEIVE LINK & AUTO-SHORTEN ---
async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("Access Denied")
        return

    session = user_sessions.get(user.id)
    if not session or session.get("step") != "WAITING_LINK":
        await update.message.reply_text("⚠️ Forward a post first before sending a link.")
        return

    raw_link = update.message.text.strip()
    await safe_delete(update.message)

    # Delete previous bot prompt
    if "last_bot_msg" in session:
        try:
            await context.bot.delete_message(user.id, session["last_bot_msg"])
        except Exception:
            pass

    short_link = shorten_arolink(raw_link)
    session["short_link"] = short_link
    session["step"] = "WAITING_BACKUP"

    # Build Backup Channel Selection Buttons
    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"backup|{name}")]
        for name in BACKUP_CHANNELS.keys()
    ]
    prompt = await context.bot.send_message(
        chat_id=user.id,
        text=f"🔗 **Shortened Link:** `{short_link}`\n\n3️⃣ **Select Backup Channel for this post:**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    session["last_bot_msg"] = prompt.message_id
    logger.info(f"Step 2 complete: Shortened link generated ({short_link}).")


# --- STEP 3 & 4: BUTTON CALLBACKS (BACKUP & MULTI-CHANNEL SELECT) ---
def build_channel_keyboard(selected: list) -> InlineKeyboardMarkup:
    buttons = []
    for name in TARGET_CHANNELS.keys():
        prefix = "✅ " if name in selected else "⬜ "
        buttons.append([InlineKeyboardButton(f"{prefix}{name}", callback_data=f"chan|{name}")])
    if len(selected) > 0:
        buttons.append([InlineKeyboardButton(f"🚀 PUBLISH TO {len(selected)} CHANNEL(S)", callback_data="publish")])
    return InlineKeyboardMarkup(buttons)


async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    if not is_admin(user.id):
        await query.answer("Access Denied", show_alert=True)
        return

    await query.answer()
    session = user_sessions.get(user.id)
    if not session:
        await query.edit_message_text("⚠️ Session expired. Forward your post again.")
        return

    data = query.data

    # Backup Channel Selected
    if data.startswith("backup|"):
        backup_name = data.split("|", 1)[1]
        session["backup_link"] = BACKUP_CHANNELS[backup_name]
        session["step"] = "SELECT_CHANNELS"

        await query.edit_message_text(
            text=f"✅ Backup Selected: **{backup_name}**\n\n4️⃣ **Select the 2 Channels to post in:**",
            reply_markup=build_channel_keyboard(session["selected_channels"]),
            parse_mode="Markdown",
        )
        logger.info(f"Step 3 complete: Backup '{backup_name}' selected.")

    # Toggle Target Channels
    elif data.startswith("chan|"):
        chan_name = data.split("|", 1)[1]
        if chan_name in session["selected_channels"]:
            session["selected_channels"].remove(chan_name)
        else:
            session["selected_channels"].append(chan_name)

        await query.edit_message_reply_markup(
            reply_markup=build_channel_keyboard(session["selected_channels"])
        )

    # Publish Final Post with Inline Buttons
    elif data == "publish":
        # Exact Button Layout Matching Your Workflow
        post_buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 WATCH & DOWNLOAD", url=session["short_link"])],
            [
                InlineKeyboardButton("💎 Premium Plans", url=PREMIUM_LINK),
                InlineKeyboardButton("📢 Join Backup", url=session["backup_link"]),
            ],
        ])

        sent_count = 0
        for chan_name in session["selected_channels"]:
            chat_id = TARGET_CHANNELS[chan_name]
            try:
                if session["media_type"] == "photo":
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=session["file_id"],
                        caption=session["caption"],
                        reply_markup=post_buttons,
                    )
                elif session["media_type"] == "video":
                    await context.bot.send_video(
                        chat_id=chat_id,
                        video=session["file_id"],
                        caption=session["caption"],
                        reply_markup=post_buttons,
                    )
                elif session["media_type"] == "document":
                    await context.bot.send_document(
                        chat_id=chat_id,
                        document=session["file_id"],
                        caption=session["caption"],
                        reply_markup=post_buttons,
                    )
                sent_count += 1
                logger.info(f"Published post to {chan_name} ({chat_id}).")
            except Exception as e:
                logger.error(f"Failed to send to {chan_name}: {e}")

        await query.edit_message_text(
            f"👑 **PROPHET Upload Complete!**\nSuccessfully posted to **{sent_count}** channel(s).",
            parse_mode="Markdown",
        )
        user_sessions.pop(user.id, None)


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, handle_post))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    app.add_handler(CallbackQueryHandler(handle_callbacks))

    logger.info("PROPHET Bot is starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
