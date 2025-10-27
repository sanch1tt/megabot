import logging
import os
import shlex
import asyncio
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from telegram.constants import ParseMode

# Import your existing Mega helper classes
from requestlistener import RequestListener
from transferlistener import TransferListener
from mega import (MegaApi, MegaNode, MegaTransfer)

# Load Environment Variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_KEY = os.getenv("API_KEY")

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(levelname)s\t%(asctime)s %(message)s"
)

# Define states for ConversationHandler
(AWAIT_FILE_CHOICE, AWAIT_LINK_CONFIRM) = range(2)

# --- Helper functions from original bot ---

def convert_size(size_bytes):
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "%s %s" % (s, size_name[i])

def expand_ranges(msg):
    output = set()
    for item in msg.split(','):
        if '-' in item:
            start, end = map(int, item.split('-'))
            output.update(range(start, end + 1))
        else:
            output.add(int(item))
    return output

# --- MegaSession class (modified for Telegram) ---

class MegaSession:
    def __init__(self, api, listener):
        self._api = api
        self._listener = listener
        self.backlog = []
        self.current_dls = []
        self.files_list = []  # Store file list for selection

    def ls_telegram(self, path, files, depth):
        """Creates a file list for Telegram (no ANSI codes)."""
        if path is None:
            return "INFO: Not logged in"
        if path.getType() == MegaNode.TYPE_FILE:
            size = f"{convert_size(path.getSize())}"
            files.append(
                {"name": "\t" * depth + path.getName() + "\t" + size, "handle": path.getHandle()}
            )
        else:
            name = "\t" * depth + "./" + path.getName()
            files.append({"name": name, "handle": path.getHandle()})
            children = self._api.getChildren(path)
            for i in range(children.size()):
                self.ls_telegram(children.get(i), files, depth + 1)

    def download(self, node, save_to):
        if self._listener.cwd is None:
            logging.info("Not logged in")
            return
        transfer_listener = TransferListener()
        if node is None:
            logging.error("Node not found")
            return
        self.current_dls.append(transfer_listener)
        self._api.startDownload(
            node, save_to + "/" + node.getName(), transfer_listener
        )

    def pwd(self):
        if self._listener.cwd is None:
            logging.info("Not logged in")
            return
        return self._listener.cwd.getName()

    def wait(self):
        self._listener.event.wait()

    def quit(self):
        del self._listener
        del self._api
        logging.info("Bye!")
        return True

# --- Status Update Job ---

async def status_update_job(context: ContextTypes.DEFAULT_TYPE):
    """Job to update the download status message."""
    job_data = context.job.data
    chat_id = job_data["chat_id"]
    message_id = job_data["message_id"]
    
    mega_session = context.chat_data.get("mega_session")
    if not mega_session:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text="Session closed."
        )
        context.job.schedule_removal()
        return

    # Check for over-quota retries
    period = job_data.get("retry_period", 1)
    if any([dl.over_quota for dl in mega_session.current_dls]):
        status_text = "Current downloads:\n```\n"
        status_text += "\n".join([tl.getStatus_telegram() for tl in mega_session.current_dls])
        status_text += "\n```"
        status_text += f"\nOver quota. Retrying connection in {period}s"
        
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=status_text, parse_mode=ParseMode.MARKDOWN
        )
        job_data["retry_period"] = 2 ** period
        context.job.data = job_data
        # Reschedule the job with the new delay
        context.job_queue.run_once(status_update_job, period, data=job_data, name=f"status_{chat_id}")
        return

    # Regular update
    if any([not dl.is_finished for dl in mega_session.current_dls]):
        status_text = "Current downloads:\n```\n"
        status_text += "\n".join([tl.getStatus_telegram() for tl in mega_session.current_dls])
        status_text += "\n```"
        
        keyboard = [[
            InlineKeyboardButton("⏸ Pause", callback_data="pause"),
            InlineKeyboardButton("▶ Resume", callback_data="resume")
        ]]
        
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=status_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logging.warning(f"Failed to edit status message: {e}")
        # Reschedule for next update
        context.job_queue.run_once(status_update_job, 2, data=job_data, name=f"status_{chat_id}")
    else:
        # All downloads finished
        status_text = "All downloads finished:\n```\n"
        status_text += "\n".join([tl.getStatus_telegram() for tl in mega_session.current_dls])
        status_text += "\n```"
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=status_text, parse_mode=ParseMode.MARKDOWN
        )
        mega_session.current_dls.clear()
        context.chat_data["mega_session"] = None  # Clear session
        context.job.schedule_removal() # Stop the job

# --- Bot Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Mega Bot started. Send /dl <link> to begin.")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong")

async def ls(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mega_session = context.chat_data.get("mega_session")
    if mega_session:
        files = []
        mega_session.ls_telegram(mega_session._listener.cwd, files, 0)
        output = "```\n" + "\n".join(
            f"{i} {n['name']}" for i, n in enumerate(files)
        ) + "\n```"
        await update.message.reply_text(output, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("No active session. Start with /dl.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mega_session = context.chat_data.get("mega_session")
    if mega_session:
        mega_session._api.cancelTransfers(MegaTransfer.TYPE_DOWNLOAD)
        pwd = mega_session.pwd()
        mega_session.current_dls.clear()
        context.chat_data["mega_session"] = None
        
        # Stop any running status jobs for this chat
        jobs = context.job_queue.get_jobs_by_name(f"status_{update.effective_chat.id}")
        for job in jobs:
            job.schedule_removal()
            
        await update.message.reply_text(f"Cancelling download and closing session for `{pwd}`", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("No active session to cancel.")
    return ConversationHandler.END

# --- /dl Conversation ---

async def dl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Starts the /dl conversation."""
    if not context.args:
        await update.message.reply_text("Usage: /dl <category> <link> [--dir optional_subdir]")
        return ConversationHandler.END

    if context.chat_data.get("mega_session"):
        await update.message.reply_text("A session is already active. Use /cancel before starting a new one.")
        return ConversationHandler.END

    try:
        cat = context.args[0]
        link = context.args[1]
        flags = " ".join(context.args[2:])
    except IndexError:
        await update.message.reply_text("Usage: /dl <category> <link> [--dir optional_subdir]")
        return ConversationHandler.END

    match cat:
        case 'f' | 's':
            dir_path = '/downloads'
        case _:
            await update.message.reply_text("Category doesn't exist.")
            return ConversationHandler.END

    try:
        split_flags = shlex.split(flags)
        if "--dir" in split_flags:
            dir_path += "/" + split_flags[split_flags.index("--dir") + 1].strip()
            os.makedirs(dir_path, exist_ok=True)
    except Exception as e:
        await update.message.reply_text(f"Error parsing flags or creating directory: {e}")
        return ConversationHandler.END
    
    context.chat_data["download_dir"] = dir_path
    await update.message.reply_text("Initializing session...")

    api = MegaApi(API_KEY, None, None, "megabot-telegram")
    listener = RequestListener()
    mega_session = MegaSession(api, listener)
    context.chat_data["mega_session"] = mega_session

    if any(f in link for f in ["folder", "#F!"]):
        api.loginToFolder(link.strip(), listener)
        mega_session.wait()
        
        folder_name = mega_session.pwd()
        await update.message.reply_text(f"Opened folder: `{folder_name}`", parse_mode=ParseMode.MARKDOWN)
        
        try:
            files = []
            mega_session.ls_telegram(mega_session._listener.cwd, files, 0)
            mega_session.files_list = files  # Save for next step
            
            output = "```\n" + "\n".join(
                f"{i} {n['name']}" for i, n in enumerate(files)
            ) + "\n```"
            await update.message.reply_text(output, parse_mode=ParseMode.MARKDOWN)
            await update.message.reply_text("Choose files to download (e.g., '1,3,5-7'). Send /cancel to abort.")
            return AWAIT_FILE_CHOICE
        
        except Exception as e:
            await update.message.reply_text(f"Couldn't open `{link}`: {e}", parse_mode=ParseMode.MARKDOWN)
            context.chat_data["mega_session"] = None
            return ConversationHandler.END
    
    else:
        # Single file link
        api.getPublicNode(link.strip(), listener)
        mega_session.wait()
        files = []
        mega_session.ls_telegram(mega_session._listener.cwd, files, 0)
        mega_session.files_list = files # Save for callback
        
        keyboard = [[
            InlineKeyboardButton("✅ Download", callback_data="dl_confirm"),
            InlineKeyboardButton("❌ Cancel", callback_data="dl_cancel")
        ]]
        await update.message.reply_text(
            f"Found file:\n```\n{files[0]['name']}\n```\nDo you want to download?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode=ParseMode.MARKDOWN
        )
        return AWAIT_LINK_CONFIRM

async def handle_file_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the user's file selection message."""
    mega_session = context.chat_data.get("mega_session")
    dir_path = context.chat_data.get("download_dir", "/downloads")
    
    if not mega_session:
        await update.message.reply_text("Session expired. Please start again with /dl.")
        return ConversationHandler.END

    try:
        selected_indices = expand_ranges(update.message.text)
    except Exception as e:
        await update.message.reply_text(f"Invalid format. Try again (e.g., '1,3,5-7') or /cancel. Error: {e}")
        return AWAIT_FILE_CHOICE # Stay in this state

    status_message = await update.message.reply_text("Starting downloads...")
    
    for n in selected_indices:
        try:
            handle = mega_session.files_list[n]["handle"]
            node = mega_session._api.getNodeByHandle(handle)
            node = mega_session._api.authorizeNode(node)
            mega_session.download(node, dir_path)
        except Exception as e:
            await update.message.reply_text(f"Error downloading file {n}: {e}")

    if mega_session.current_dls:
        job_data = {"chat_id": update.effective_chat.id, "message_id": status_message.message_id}
        context.job_queue.run_once(status_update_job, 0, data=job_data, name=f"status_{update.effective_chat.id}")

    return ConversationHandler.END

async def handle_link_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the inline keyboard button press for single files."""
    query = update.callback_query
    await query.answer()

    mega_session = context.chat_data.get("mega_session")
    dir_path = context.chat_data.get("download_dir", "/downloads")
    
    if not mega_session:
        await query.edit_message_text("Session expired. Please start again with /dl.")
        return ConversationHandler.END

    if query.data == "dl_confirm":
        await query.edit_message_text("Starting download...")
        try:
            node = mega_session._listener.cwd
            mega_session.download(node, dir_path)
            
            job_data = {"chat_id": update.effective_chat.id, "message_id": query.message.message_id}
            context.job_queue.run_once(status_update_job, 0, data=job_data, name=f"status_{update.effective_chat.id}")
            
        except Exception as e:
            logging.error(f"Error downloading: {e}")
            await query.edit_message_text(f"Error downloading: {e}")
            
    elif query.data == "dl_cancel":
        await query.edit_message_text("Download cancelled.")
        context.chat_data["mega_session"] = None

    return ConversationHandler.END

# --- Pause/Resume Callback ---

async def pause_resume_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles pause/resume button presses from status messages."""
    query = update.callback_query
    mega_session = context.chat_data.get("mega_session")
    
    if not mega_session:
        await query.answer("This session is no longer active.")
        return

    pause = query.data == "pause"
    mega_session._api.pauseTransfers(pause)
    await query.answer(f"Transfers {'paused' if pause else 'resumed'}")

# --- Main Function ---

async def main():
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Conversation handler for the /dl command
    dl_handler = ConversationHandler(
        entry_points=[CommandHandler("dl", dl_command)],
        states={
            AWAIT_FILE_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_file_selection)],
            AWAIT_LINK_CONFIRM: [CallbackQueryHandler(handle_link_callback, pattern="^(dl_confirm|dl_cancel)$")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        conversation_timeout=600 # 10 minutes
    )

    application.add_handler(dl_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ping", ping))
    application.add_handler(CommandHandler("ls", ls))
    application.add_handler(CommandHandler("cancel", cancel)) # Standalone cancel
    application.add_handler(CallbackQueryHandler(pause_resume_callback, pattern="^(pause|resume)$"))

    logging.info("Starting bot...")
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
