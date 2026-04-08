"""
==============================================
  MEGA.NZ TELEGRAM RENAMER BOT
  By: Claude | Full Bulk Rename Support
==============================================
"""

import logging
import asyncio
import re
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from mega import Mega

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

WAITING_PATTERN = 1
user_sessions = {}
rename_jobs = {}


def get_session(user_id):
    return user_sessions.get(user_id)


def all_files_recursive(m, folder_node=None):
    files = m.get_files()
    result = []
    for fid, node in files.items():
        if node.get("t") == 0:
            result.append((fid, node))
    return result


def build_new_name(old_name: str, pattern: str, replacement: str, index: int) -> str:
    name, ext = os.path.splitext(old_name)

    if pattern == "prefix":
        return f"{replacement}{old_name}"

    elif pattern == "suffix":
        return f"{name}{replacement}{ext}"

    elif pattern == "replace":
        parts = replacement.split("|", 1)
        if len(parts) == 2:
            return old_name.replace(parts[0], parts[1])
        return old_name

    elif pattern == "regex":
        parts = replacement.split("|", 1)
        if len(parts) == 2:
            try:
                return re.sub(parts[0], parts[1], old_name)
            except re.error:
                return old_name
        return old_name

    elif pattern == "template":
        return replacement.replace("{n}", name).replace("{i}", str(index)).replace("{ext}", ext)

    elif pattern == "number":
        return f"{str(index).zfill(5)}{ext}"

    return old_name


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🚀 *MEGA.NZ BULK RENAMER BOT*\n\n"
        "এই bot দিয়ে Mega.nz এর হাজার হাজার file একসাথে rename করো!\n\n"
        "📌 *Commands:*\n"
        "  `/login email password` — Mega.nz login\n"
        "  `/logout` — Logout\n"
        "  `/stats` — Total files count\n"
        "  `/listfolders` — Folder list দেখো\n"
        "  `/renameall` — সব file rename করো\n"
        "  `/cancel` — চলমান rename বন্ধ করো\n\n"
        "🔧 *Rename Patterns:*\n"
        "  `prefix:MyName_` → সব file এর আগে যোগ করো\n"
        "  `suffix:_HD` → সব file এর পরে যোগ করো\n"
        "  `replace:old|new` → নাম replace করো\n"
        "  `regex:pattern|repl` → Regex দিয়ে rename\n"
        "  `template:{n}_{i}{ext}` → Custom template\n"
        "  `number` → Sequential numbers (00001.mp4)\n"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def login_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    args = ctx.args

    if len(args) < 2:
        await update.message.reply_text(
            "❌ Usage: `/login email password`", parse_mode="Markdown"
        )
        return

    email, password = args[0], args[1]
    await update.message.reply_text("🔄 Mega.nz এ login হচ্ছে...")

    try:
        mega = Mega()
        m = mega.login(email, password)
        user_sessions[uid] = {"mega": mega, "m": m, "email": email}
        await update.message.reply_text(
            f"✅ *Login সফল!*\n📧 {email}\n\nএখন `/stats` দিয়ে file count দেখো।",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Login ব্যর্থ!\nError: `{e}`", parse_mode="Markdown")


async def logout_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in user_sessions:
        del user_sessions[uid]
        await update.message.reply_text("✅ Logout হয়ে গেছে।")
    else:
        await update.message.reply_text("⚠️ আপনি login করেননি।")


async def stats_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    sess = get_session(uid)
    if not sess:
        await update.message.reply_text("❌ আগে `/login email password` করো।", parse_mode="Markdown")
        return

    await update.message.reply_text("🔄 File count করা হচ্ছে...")
    try:
        m = sess["m"]
        files = all_files_recursive(m)
        total = len(files)
        await update.message.reply_text(
            f"📊 *Mega.nz Stats*\n\n"
            f"📁 Total Files: `{total:,}`\n"
            f"📧 Account: `{sess['email']}`",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: `{e}`", parse_mode="Markdown")


async def listfolders_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    sess = get_session(uid)
    if not sess:
        await update.message.reply_text("❌ আগে `/login` করো।", parse_mode="Markdown")
        return

    try:
        m = sess["m"]
        all_nodes = m.get_files()
        folders = [(fid, n) for fid, n in all_nodes.items() if n.get("t") == 1 and n.get("a")]
        if not folders:
            await update.message.reply_text("📂 কোনো folder পাওয়া যায়নি।")
            return

        lines = ["📂 *Folder List:*\n"]
        for fid, node in folders[:50]:
            name = node.get("a", {}).get("n", "Unknown")
            lines.append(f"• `{name}`")

        if len(folders) > 50:
            lines.append(f"\n_...এবং আরো {len(folders)-50}টি folder_")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: `{e}`", parse_mode="Markdown")


async def renameall_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    sess = get_session(uid)
    if not sess:
        await update.message.reply_text("❌ আগে `/login` করো।", parse_mode="Markdown")
        return

    keyboard = [
        [InlineKeyboardButton("🔤 Prefix যোগ করো", callback_data="pattern_prefix")],
        [InlineKeyboardButton("🔡 Suffix যোগ করো", callback_data="pattern_suffix")],
        [InlineKeyboardButton("🔄 Text Replace", callback_data="pattern_replace")],
        [InlineKeyboardButton("🔢 Sequential Numbers", callback_data="pattern_number")],
        [InlineKeyboardButton("🛠 Regex Replace", callback_data="pattern_regex")],
        [InlineKeyboardButton("📝 Custom Template", callback_data="pattern_template")],
    ]
    await update.message.reply_text(
        "🎯 *কোন ধরনের Rename করতে চাও?*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    data = query.data

    if data.startswith("pattern_"):
        pattern = data.replace("pattern_", "")
        ctx.user_data["rename_pattern"] = pattern

        if pattern == "number":
            ctx.user_data["rename_replacement"] = ""
            await query.edit_message_text(
                "🔢 সব file কে `00001.ext`, `00002.ext` ... এভাবে rename করা হবে।\n\n"
                "শুরু করতে `/startrenaming` দাও।",
                parse_mode="Markdown"
            )
        elif pattern == "prefix":
            await query.edit_message_text(
                "✏️ Prefix টাইপ করো:\n\nExample: `Movie_2024_`\n\n"
                "_(এই text সব file এর নামের আগে যোগ হবে)_",
                parse_mode="Markdown"
            )
            ctx.user_data["awaiting_input"] = True
        elif pattern == "suffix":
            await query.edit_message_text(
                "✏️ Suffix টাইপ করো:\n\nExample: `_HD`\n\n"
                "_(Extension এর আগে যোগ হবে)_",
                parse_mode="Markdown"
            )
            ctx.user_data["awaiting_input"] = True
        elif pattern == "replace":
            await query.edit_message_text(
                "✏️ Format: `পুরনো_text|নতুন_text`\n\nExample: `Episode|EP`",
                parse_mode="Markdown"
            )
            ctx.user_data["awaiting_input"] = True
        elif pattern == "regex":
            await query.edit_message_text(
                "✏️ Regex Format: `pattern|replacement`\n\nExample: `\\s+|_` (space কে underscore করবে)",
                parse_mode="Markdown"
            )
            ctx.user_data["awaiting_input"] = True
        elif pattern == "template":
            await query.edit_message_text(
                "✏️ Template লেখো:\n\n"
                "`{n}` = original name\n"
                "`{i}` = index number\n"
                "`{ext}` = extension\n\n"
                "Example: `Series_{i}_{n}{ext}`",
                parse_mode="Markdown"
            )
            ctx.user_data["awaiting_input"] = True

    elif data == "confirm_rename":
        await query.edit_message_text("🚀 Rename শুরু হচ্ছে...")
        await do_bulk_rename(query.message, uid, ctx)

    elif data == "cancel_rename":
        await query.edit_message_text("❌ Rename বাতিল করা হয়েছে।")
        ctx.user_data.clear()


async def message_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if not ctx.user_data.get("awaiting_input"):
        return

    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    ctx.user_data["rename_replacement"] = text
    ctx.user_data["awaiting_input"] = False

    pattern = ctx.user_data.get("rename_pattern", "")

    example_old = "My_Movie_Episode_01.mp4"
    example_new = build_new_name(example_old, pattern, text, 1)

    keyboard = [
        [InlineKeyboardButton("✅ শুরু করো!", callback_data="confirm_rename"),
         InlineKeyboardButton("❌ বাতিল", callback_data="cancel_rename")]
    ]
    await update.message.reply_text(
        f"👁 *Preview:*\n\n"
        f"📄 আগে: `{example_old}`\n"
        f"📄 পরে: `{example_new}`\n\n"
        f"সব file এই নিয়মে rename হবে। নিশ্চিত?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def startrenaming_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if ctx.user_data.get("rename_pattern") == "number":
        await update.message.reply_text("🚀 Rename শুরু হচ্ছে...")
        await do_bulk_rename(update.message, uid, ctx)
    else:
        await update.message.reply_text("⚠️ আগে `/renameall` দিয়ে pattern সেট করো।", parse_mode="Markdown")


async def cancel_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid in rename_jobs:
        rename_jobs[uid]["cancelled"] = True
        await update.message.reply_text("🛑 Rename job বন্ধ করার request পাঠানো হয়েছে...")
    else:
        await update.message.reply_text("⚠️ কোনো চলমান job নেই।")


async def do_bulk_rename(message, uid: int, ctx: ContextTypes.DEFAULT_TYPE):
    sess = get_session(uid)
    if not sess:
        await message.reply_text("❌ Session শেষ হয়ে গেছে। আবার `/login` করো।", parse_mode="Markdown")
        return

    pattern = ctx.user_data.get("rename_pattern", "prefix")
    replacement = ctx.user_data.get("rename_replacement", "")

    m = sess["m"]

    rename_jobs[uid] = {"running": True, "cancelled": False}

    try:
        files = all_files_recursive(m)
        total = len(files)

        if total == 0:
            await message.reply_text("📂 কোনো file পাওয়া যায়নি।")
            return

        status_msg = await message.reply_text(
            f"🔄 *Rename শুরু হয়েছে!*\n\n"
            f"📊 Total Files: `{total:,}`\n"
            f"✅ Done: `0`\n"
            f"❌ Failed: `0`\n\n"
            f"_/cancel দিয়ে বন্ধ করতে পারো_",
            parse_mode="Markdown"
        )

        done = 0
        failed = 0
        UPDATE_EVERY = 50

        for idx, (fid, node) in enumerate(files, start=1):
            if rename_jobs.get(uid, {}).get("cancelled"):
                await status_msg.edit_text(
                    f"🛑 *Rename বন্ধ করা হয়েছে!*\n\n"
                    f"✅ Done: `{done:,}`\n"
                    f"❌ Failed: `{failed:,}`\n"
                    f"⏹ Cancelled at: `{idx:,}/{total:,}`",
                    parse_mode="Markdown"
                )
                break

            try:
                old_name = node.get("a", {}).get("n", "")
                if not old_name:
                    failed += 1
                    continue

                new_name = build_new_name(old_name, pattern, replacement, idx)

                if new_name == old_name:
                    done += 1
                    continue

                m.rename((fid, node), new_name)
                done += 1

            except Exception as e:
                logger.error(f"Rename failed for file at index {idx}: {e}")
                failed += 1

            if idx % UPDATE_EVERY == 0 or idx == total:
                percent = int((idx / total) * 100)
                bar_filled = percent // 5
                bar = "█" * bar_filled + "░" * (20 - bar_filled)

                try:
                    await status_msg.edit_text(
                        f"🔄 *Renaming...*\n\n"
                        f"`{bar}` {percent}%\n\n"
                        f"📊 Total: `{total:,}`\n"
                        f"✅ Done: `{done:,}`\n"
                        f"❌ Failed: `{failed:,}`\n"
                        f"🔢 Current: `{idx:,}/{total:,}`",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass

            await asyncio.sleep(0.5)

        else:
            await status_msg.edit_text(
                f"🎉 *Rename সম্পন্ন!*\n\n"
                f"📊 Total Files: `{total:,}`\n"
                f"✅ Successfully Renamed: `{done:,}`\n"
                f"❌ Failed: `{failed:,}`",
                parse_mode="Markdown"
            )

    except Exception as e:
        await message.reply_text(f"❌ Critical Error: `{e}`", parse_mode="Markdown")
    finally:
        rename_jobs.pop(uid, None)
        ctx.user_data.clear()


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass


def start_health_server():
    port = int(os.environ.get("PORT", 8000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"✅ Health check server on port {port}")
    server.serve_forever()


def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN environment variable is not set!")
        print("   Set it as a secret named BOT_TOKEN and restart the bot.")
        return

    threading.Thread(target=start_health_server, daemon=True).start()

    print("🤖 Mega Renamer Bot চালু হচ্ছে...")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("login", login_cmd))
    app.add_handler(CommandHandler("logout", logout_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("listfolders", listfolders_cmd))
    app.add_handler(CommandHandler("renameall", renameall_cmd))
    app.add_handler(CommandHandler("startrenaming", startrenaming_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    print("✅ Bot ready! Ctrl+C দিয়ে বন্ধ করো।")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
