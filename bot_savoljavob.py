"""
Telegram Savol-Javob Bot
========================
Guruhda sessiya davomida kim necha marta xabar yuborganini kuzatadi.
Sessiya tugaganda qatnashganlar va qatnashmaganlar statistikasi chiqariladi.

Buyruqlar:
  /boshladik  — Admin, sessiyani boshlaydi
  /yakunladik — Admin, sessiyani to'xtatadi va statistikani chiqaradi
  /holat      — Admin, joriy holat
"""

import logging
import html
import os
import asyncio
import threading
from datetime import datetime

# flask import removed
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ChatMemberStatus, ParseMode

from config import SAVOLJAVOB_BOT_TOKEN as BOT_TOKEN, ADMIN_ID
import database_savoljavob as db

# -----------------------------------------------------------------
# Logging
# -----------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# -----------------------------------------------------------------
# Flask server disabled (FastAPI main.py will handle health checks)
def run_flask():
    pass


# -----------------------------------------------------------------
# Yordamchi funksiyalar
# -----------------------------------------------------------------

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Xabar yuboruvchi guruh admin yoki egasimi tekshiradi."""
    try:
        if update.message and update.message.sender_chat and update.message.sender_chat.id == update.effective_chat.id:
            return True
        member = await context.bot.get_chat_member(
            update.effective_chat.id,
            update.effective_user.id,
        )
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except Exception as e:
        logger.error("is_admin da xatolik: %s", e)
        # Agar telegramdan xatolik qaytsa (anonim foydalanuvchi va h.k.), xavfsizlik yuzasidan o'tkazmaymiz
        # Lekin egasi bo'lsa va is_admin qulasa, return True qilib yuborish xavfli. 
        # Mayli, False qaytaramiz. Agar u rostan e'tibor bermayotgan bo'lsa logsda ko'rinadi.
        return False


def esc(text: str) -> str:
    """HTML maxsus belgilarini xavfsiz ko'rinishga o'tkazadi."""
    return html.escape(str(text))


async def check_approval(update: Update, context: ContextTypes.DEFAULT_TYPE, silent: bool = False) -> bool:
    """Guruh ruxsat etilganligini tekshiradi."""
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return True

    if ADMIN_ID and chat.id == ADMIN_ID:
        return True

    status = await asyncio.to_thread(db.get_group_status, chat.id)

    if status == 'approved':
        return True

    if status == 'rejected':
        if not silent:
            await context.bot.send_message(chat.id, "Kechirasiz, ushbu guruhda botdan foydalanish taqiqlangan.")
            await context.bot.leave_chat(chat.id)
        return False

    if status == 'pending':
        if not silent:
            await context.bot.send_message(
                chat.id, 
                "Kechirasiz, men bu guruhda ishlashim uchun dasturchi ruxsati kerak. Iltimos @Umidjon_Qodirov ga murojaat qiling."
            )
        return False

    if status is None:
        await asyncio.to_thread(db.request_group_approval, chat.id, chat.title)
        if not silent:
            await context.bot.send_message(
                chat.id,
                "Kechirasiz, men bu guruhda ishlashim uchun dasturchi ruxsati kerak. Iltimos @Umidjon_Qodirov ga murojaat qiling."
            )

        if ADMIN_ID:
            keyboard = [
                [
                    InlineKeyboardButton("✅ Ruxsat berish", callback_data=f"approve_{chat.id}"),
                    InlineKeyboardButton("❌ Rad etish", callback_data=f"reject_{chat.id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                ADMIN_ID,
                f"Yangi guruh botni ishlatmoqchi!\n\nGuruh nomi: <b>{esc(chat.title)}</b>\nID: <code>{chat.id}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
        return False

    return False


async def admin_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admindan kelgan tugma (Inline Keyboard) bosilishini boshqaradi."""
    query = update.callback_query
    user = query.from_user

    if ADMIN_ID and user.id != ADMIN_ID:
        await query.answer("Sizda bunga huquq yo'q!", show_alert=True)
        return

    await query.answer()
    data = query.data

    if data.startswith("approve_"):
        chat_id = int(data.split("_")[1])
        await asyncio.to_thread(db.set_group_status, chat_id, "approved")
        await query.edit_message_text(f"{query.message.text}\n\n<b>✅ Ruxsat berildi!</b>", parse_mode=ParseMode.HTML)
        try:
            await context.bot.send_message(chat_id, "✅ Ruxsat olindi, ishni boshlashimiz mumkin!")
        except Exception as e:
            logger.error("Guruhga xabar yuborishda xatolik: %s", e)

    elif data.startswith("reject_"):
        chat_id = int(data.split("_")[1])
        await asyncio.to_thread(db.set_group_status, chat_id, "rejected")
        await query.edit_message_text(f"{query.message.text}\n\n<b>❌ Rad etildi!</b>", parse_mode=ParseMode.HTML)
        try:
            await context.bot.send_message(chat_id, "❌ Ruxsat rad etildi. Bot guruhdan chiqib ketmoqda.")
            await context.bot.leave_chat(chat_id)
        except Exception as e:
            logger.error("Guruhdan chiqishda xatolik: %s", e)

    elif data.startswith("revoke_"):
        chat_id = int(data.split("_")[1])
        await asyncio.to_thread(db.set_group_status, chat_id, "rejected")
        await query.edit_message_text(f"{query.message.text}\n\n<b>❌ Ruxsat bekor qilindi va bot guruhdan chiqib ketmoqda!</b>", parse_mode=ParseMode.HTML)
        try:
            await context.bot.send_message(chat_id, "❌ Dasturchi tomonidan ruxsat bekor qilindi. Bot guruhdan chiqib ketmoqda.")
            await context.bot.leave_chat(chat_id)
        except Exception as e:
            logger.error("Guruhdan chiqishda xatolik: %s", e)


def format_username(row: dict) -> str:
    """Foydalanuvchi nomini formatlaydi: @username yoki Ism Familiya."""
    if row.get("username"):
        return f"@{esc(row['username'])}"
    parts = []
    if row.get("first_name"):
        parts.append(esc(row["first_name"]))
    if row.get("last_name"):
        parts.append(esc(row["last_name"]))
    return " ".join(parts) if parts else f"User#{row['user_id']}"


def duration_text(started_at: str, ended_at: str) -> str:
    """Sessiya davomiyligini o'qiladigan matn ko'rinishida qaytaradi."""
    fmt = "%Y-%m-%dT%H:%M:%S.%f"
    try:
        start = datetime.strptime(started_at[:26], fmt)
        end = datetime.strptime(ended_at[:26], fmt)
    except ValueError:
        fmt2 = "%Y-%m-%dT%H:%M:%S"
        start = datetime.strptime(started_at[:19], fmt2)
        end = datetime.strptime(ended_at[:19], fmt2)

    delta = end - start
    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts = []
    if hours:
        parts.append(f"{hours} soat")
    if minutes:
        parts.append(f"{minutes} daqiqa")
    if seconds or not parts:
        parts.append(f"{seconds} soniya")
    return " ".join(parts)


MEDALS = ["🥇", "🥈", "🥉"]

OGOHLANTIRISH = """⚠️ <b>Online darsdagi ishtirok bo'yicha ogohlantirish</b>

Hurmatli darsda qatnashmaganlar,

Bugungi online darsda ishtirok etmaganingiz aniqlandi. O'quv jarayonidagi uzilishlar o'zlashtirish darajasiga salbiy ta'sir ko'rsatishi va akademik natijalaringizni pasaytirishi mumkinligini eslatib o'tmoqchiman.

Dars qoldirishning uzrli sababi bo'lsa, tegishli ma'lumotlarni taqdim etishingizni, aks holda, kelgusida bunday holat takrorlanmasligi kerakligini ma'lum qilaman. O'tkazib yuborilgan mavzularni mustaqil o'zlashtirib olishingiz va topshiriqlarni belgilangan muddatda topshirishingiz shart."""


def build_stats_message(session: dict, stats: list[dict],
                        total: int, absent: list[dict]) -> str:
    """Statistika xabarini HTML formatda tuzadi."""
    dur = duration_text(session["started_at"], session["ended_at"])
    participant_count = len(stats)

    lines = [
        "📊 <b>Sessiya Statistikasi</b>",
        f"⏱ Dars davomiyligi: <b>{dur}</b>",
        "",
        "🏆 <b>Eng faol ishtirokchilar:</b>",
    ]

    for i, row in enumerate(stats):
        medal = MEDALS[i] if i < len(MEDALS) else f"{i + 1}."
        name = format_username(row)
        lines.append(f"{medal} {name} — <b>{row['message_count']}</b>")

    lines += [
        "",
        f"👥 Jami ishtirokchilar: <b>{participant_count}</b> nafar",
    ]

    if absent:
        lines.append("")
        lines.append(f"😶 <b>Darsda ishtirok etmaganlar ({len(absent)} nafar):</b>")
        for row in absent:
            name = format_username(row)
            lines.append(f"• {name}")

    lines += [
        "",
        "📌 <i>Qatnashmaganlar diqqatiga: Natija osmondan tushmaydi.</i>",
    ]

    return "\n".join(lines)


# -----------------------------------------------------------------
# Handler-lar
# -----------------------------------------------------------------

async def cmd_boshladik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_approval(update, context):
        return

    chat = update.effective_chat
    user = update.effective_user

    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("❗ Bu buyruq faqat guruhlarda ishlaydi.")
        return

    if not await is_admin(update, context):
        await update.message.reply_text("❌ Faqat guruh adminlari sessiyani boshlay oladi.")
        return

    existing = await asyncio.to_thread(db.get_active_session, chat.id)
    if existing:
        await update.message.reply_text(
            "⚠️ Sessiya allaqachon boshlangan!\n"
            "To'xtatish uchun /yakunladik deb yozing."
        )
        return

    await asyncio.to_thread(db.start_session, chat.id)
    logger.info("Sessiya boshlandi: chat_id=%s, admin=%s", chat.id, user.id)

    await update.message.reply_text(
        "✅ <b>Sessiya boshlandi!</b>\n\n"
        "Endi barcha xabarlar hisoblanadi.\n"
        "To'xtatish uchun /yakunladik deb yozing.",
        parse_mode=ParseMode.HTML,
    )


async def cmd_yakunladik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_approval(update, context):
        return

    chat = update.effective_chat
    user = update.effective_user

    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("❗ Bu buyruq faqat guruhlarda ishlaydi.")
        return

    if not await is_admin(update, context):
        await update.message.reply_text("❌ Faqat guruh adminlari sessiyani yakunlay oladi.")
        return

    session = await asyncio.to_thread(db.end_session, chat.id)
    if not session:
        await update.message.reply_text(
            "⚠️ Hozir aktiv sessiya yo'q.\n"
            "Boshlash uchun /boshladik deb yozing."
        )
        return

    logger.info("Sessiya yakunlandi: chat_id=%s, session_id=%s", chat.id, session["id"])

    stats = await asyncio.to_thread(db.get_session_stats, session["id"])
    total = await asyncio.to_thread(db.get_session_total_messages, session["id"])
    absent = await asyncio.to_thread(db.get_absent_members, chat.id, session["id"])

    if not stats:
        await update.message.reply_text(
            "📊 Sessiya yakunlandi, lekin hech kim xabar yozmadi."
        )
        return

    message = build_stats_message(session, stats, total, absent)
    await update.message.reply_text(message, parse_mode=ParseMode.HTML)

    if absent:
        await update.message.reply_text(OGOHLANTIRISH, parse_mode=ParseMode.HTML)




async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private" or (ADMIN_ID and update.effective_user.id != ADMIN_ID):
        return
    try:
        with open("bot_log.txt", "r", encoding="utf-8") as f:
            lines = f.readlines()
            logs = "".join(lines[-50:])
            await update.message.reply_text(f"Oxirgi 50 ta loglar:\n\n<pre>{esc(logs)}</pre>", parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"Log o'qishda xatolik: {e}")

async def cmd_guruhlar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type != "private":
        await update.message.reply_text("⛔ Bu buyruq faqat shaxsiy xabarlarda ishlaydi.")
        return

    if ADMIN_ID and update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Bu buyruq faqat bot egasi uchun.")
        return

    groups = await asyncio.to_thread(db.get_approved_groups)
    if not groups:
        await update.message.reply_text("📋 Hozircha tasdiqlangan guruhlar yo'q.")
        return

    await update.message.reply_text("✅ <b>Tasdiqlangan guruhlar ro'yxati:</b>\n<i>Quyidagi tugmalar orqali guruhlardan ruxsatni bekor qilishingiz mumkin.</i>", parse_mode=ParseMode.HTML)

    for g in groups:
        keyboard = [[InlineKeyboardButton("❌ Ruxsatni bekor qilish", callback_data=f"revoke_{g['chat_id']}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"Guruh nomi: <b>{esc(g['group_name'])}</b>\nID: <code>{g['chat_id']}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )


async def cmd_holat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_approval(update, context):
        return

    chat = update.effective_chat

    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("❗ Bu buyruq faqat guruhlarda ishlaydi.")
        return

    if not await is_admin(update, context):
        await update.message.reply_text("❌ Faqat guruh adminlari holatni ko'ra oladi.")
        return

    session = await asyncio.to_thread(db.get_active_session, chat.id)
    if not session:
        await update.message.reply_text(
            "🔴 Hozir aktiv sessiya yo'q.\n"
            "Boshlash uchun /boshladik deb yozing."
        )
        return

    total = await asyncio.to_thread(db.get_session_total_messages, session["id"])
    stats = await asyncio.to_thread(db.get_session_stats, session["id"])
    participant_count = len(stats)

    await update.message.reply_text(
        f"🟢 <b>Sessiya faol</b>\n"
        f"👥 Ishtirokchilar: <b>{participant_count}</b> nafar\n"
        f"💬 Xabarlar: <b>{total}</b> ta",
        parse_mode=ParseMode.HTML,
    )


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_approval(update, context, silent=True):
        return

    chat = update.effective_chat
    user = update.effective_user
    message = update.effective_message

    if chat.type not in ("group", "supergroup"):
        return

    if user is None or user.is_bot:
        return

    if message and message.text and message.text.startswith("/"):
        return

    await asyncio.to_thread(
        db.upsert_member,
        chat_id=chat.id,
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
    )

    session = await asyncio.to_thread(db.get_active_session, chat.id)
    if not session:
        return

    await asyncio.to_thread(
        db.record_message,
        session_id=session["id"],
        chat_id=chat.id,
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
    )


# -----------------------------------------------------------------
# Asosiy funksiya
# -----------------------------------------------------------------

def build_application():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("boshladik", cmd_boshladik))
    app.add_handler(CommandHandler("yakunladik", cmd_yakunladik))
    app.add_handler(CommandHandler("holat", cmd_holat))
    app.add_handler(CommandHandler("guruhlar", cmd_guruhlar))
    app.add_handler(CommandHandler("logs", cmd_logs))
    app.add_handler(CallbackQueryHandler(admin_button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    
    return app

def main():
    db.init_db()
    logger.info("Baza tayyor. Bot ishga tushmoqda...")

    # Flask health serverini alohida threadda ishga tushiramiz
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("Health server ishga tushdi.")

    app = build_application()
    logger.info("Bot ishga tushdi. To'xtatish uchun Ctrl+C bosing.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
