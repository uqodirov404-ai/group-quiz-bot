"""
Telegram Savol-Javob Bot
========================
Guruhda sessiya davomida kim necha marta xabar yuborganini kuzatadi.
Sessiya tugaganda qatnashganlar va qatnashmaganlar statistikasi chiqariladi.

Buyruqlar:
  /boshladik   — Admin, sessiyani boshlaydi
  /yakunladik  — Admin, sessiyani to'xtatadi va statistikani chiqaradi
  /holat       — Admin, joriy holat
  /statistika  — Admin, oxirgi 10 kunlik faollik statistikasi
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


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline Keyboard tugmalari bosilishini boshqaradi."""
    query = update.callback_query
    user = query.from_user
    data = query.data

    if data.startswith("act_check_"):
        parts = data.split("_")
        session_id = int(parts[2])
        timestamp = int(parts[3])
        
        import time
        elapsed = time.time() - timestamp
        if elapsed > 4 * 60:
            await query.answer("⌛ Vaqt tugadi! Faollikni tasdiqlash uchun 4 daqiqa berilgan edi.", show_alert=True)
            return

        active_sess = await asyncio.to_thread(db.get_active_session, query.message.chat_id)
        if not active_sess or active_sess["id"] != session_id:
            await query.answer("⚠️ Dars allaqachon yakunlangan!", show_alert=True)
            return

        await asyncio.to_thread(
            db.record_active_check,
            session_id=session_id,
            user_id=user.id,
            username=user.username,
            first_name=user.first_name
        )
        await query.answer("✅ Faolligingiz tasdiqlandi!", show_alert=True)
        return

    if ADMIN_ID and user.id != ADMIN_ID:
        await query.answer("Sizda bunga huquq yo'q!", show_alert=True)
        return

    await query.answer()

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

async def auto_attention_check(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    session_id = job.data["session_id"]
    
    import time
    now_ts = int(time.time())
    
    keyboard = [
        [
            InlineKeyboardButton("🙋‍♂️ Shu yerdaman", callback_data=f"act_check_{session_id}_{now_ts}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text="<b>🔔 FAOLLIK TEKSHIRUVI!</b>\n\n"
                 "Hurmatli o'quvchilar, darsdamisiz? "
                 "Iltimos, <b>4 daqiqa</b> ichida quyidagi tugmani bosib, faolligingizni tasdiqlang!",
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
        
        # Schedule message close job after 4 minutes (240 seconds)
        context.job_queue.run_once(
            callback=close_attention_check,
            when=4 * 60,
            chat_id=chat_id,
            data={"message_id": msg.message_id, "session_id": session_id}
        )
    except Exception as e:
        logger.error("auto_attention_check yuborishda xatolik: %s", e)


async def close_attention_check(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    message_id = job.data["message_id"]
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="<b>🔔 FAOLLIK TEKSHIRUVI YAKUNLANDI</b>\n\n"
                 "Vaqt tugadi (4 daqiqa o'tdi).",
            parse_mode=ParseMode.HTML,
            reply_markup=None
        )
    except Exception as e:
        logger.error("close_attention_check da xatolik: %s", e)


async def cmd_boshladik(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_approval(update, context):
        return

    chat = update.effective_chat
    user = update.effective_user

    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("❗ Bu buyruq faqat guruhlarda ishlaydi.")
        return

    if not await is_admin(update, context):
        await update.message.reply_text("❌ Faqat guruh adminlari darsni boshlay oladi.")
        return

    existing = await asyncio.to_thread(db.get_active_session, chat.id)
    if existing:
        await update.message.reply_text(
            "⚠️ Dars allaqachon boshlangan!\n"
            "To'xtatish uchun /yakunladik deb yozing."
        )
        return

    session_id = await asyncio.to_thread(db.start_session, chat.id)
    logger.info("Dars boshlandi: chat_id=%s, admin=%s, session_id=%s", chat.id, user.id, session_id)

    # Avtomatik faollik tekshiruvi (har 15 daqiqada - 900 soniya)
    context.job_queue.run_repeating(
        callback=auto_attention_check,
        interval=15 * 60,
        first=15 * 60,
        chat_id=chat.id,
        name=f"check_{chat.id}",
        data={"session_id": session_id}
    )

    await update.message.reply_text(
        "✅ <b>Dars boshlandi!</b>\n\n"
        "Yo`qlama uchun + belgisini qoldiring.\n"
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
        await update.message.reply_text("❌ Faqat guruh adminlari darsni yakunlay oladi.")
        return

    session = await asyncio.to_thread(db.end_session, chat.id)
    if not session:
        await update.message.reply_text(
            "⚠️ Hozir aktiv dars yo'q.\n"
            "Boshlash uchun /boshladik deb yozing."
        )
        return

    # Faollik tekshiruvi joblarini bekor qilish
    jobs = context.job_queue.get_jobs_by_name(f"check_{chat.id}")
    for job in jobs:
        job.schedule_removal()

    logger.info("Dars yakunlandi: chat_id=%s, session_id=%s", chat.id, session["id"])

    stats = await asyncio.to_thread(db.get_session_stats, session["id"])
    total = await asyncio.to_thread(db.get_session_total_messages, session["id"])
    absent = await asyncio.to_thread(db.get_absent_members, chat.id, session["id"])
    checked_user_ids = await asyncio.to_thread(db.get_active_checked_users, session["id"])

    if not stats:
        await update.message.reply_text(
            "📊 Dars yakunlandi, lekin hech kim xabar yozmadi."
        )
        return

    try:
        dur = duration_text(session["started_at"], session["ended_at"])
        participant_count = len(stats)

        # 1-qism: Asosiy dars statistikasi va eng faol ishtirokchilar
        header_lines = [
            "📊 <b>Dars statistikasi</b>",
            f"⏱ Dars davomiyligi: <b>{dur}</b>",
            "",
            "🏆 <b>Eng faol ishtirokchilar:</b>",
        ]
        for i, row in enumerate(stats):
            medal = MEDALS[i] if i < len(MEDALS) else f"{i + 1}."
            name = format_username(row)
            status_symbol = "🙋‍♂️" if row["user_id"] in checked_user_ids else "❌"
            header_lines.append(f"{medal} {name} — <b>{row['message_count']}</b> [{status_symbol}]")
        header_lines += [
            "",
            f"👥 Jami ishtirokchilar: <b>{participant_count}</b> nafar",
        ]
        await update.message.reply_text("\n".join(header_lines), parse_mode=ParseMode.HTML)

        # 2-qism: Qatnashmaganlar
        if absent:
            absent_header = f"😶 <b>Darsda ishtirok etmaganlar ({len(absent)} nafar):</b>\n"
            absent_lines = []
            for row in absent:
                name = format_username(row)
                status_symbol = "🙋‍♂️" if row["user_id"] in checked_user_ids else "❌"
                absent_lines.append(f"• {name} [{status_symbol}]")

            current_chunk = absent_header
            for line in absent_lines:
                if len(current_chunk) + len(line) + 1 > 3900:
                    await update.message.reply_text(current_chunk, parse_mode=ParseMode.HTML)
                    current_chunk = ""
                current_chunk += line + "\n"

            if current_chunk.strip():
                await update.message.reply_text(current_chunk, parse_mode=ParseMode.HTML)

            # Ogohlantirish
            await update.message.reply_text(OGOHLANTIRISH, parse_mode=ParseMode.HTML)
        else:
            await update.message.reply_text(
                "📌 <i>Barcha a'zolar darsda qatnashdi! 👏</i>",
                parse_mode=ParseMode.HTML,
            )

    except Exception as e:
        logger.error("Statistika yuborishda xatolik: %s", e)
        await update.message.reply_text(
            f"📊 Dars yakunlandi.\n"
            f"👥 Ishtirokchilar: {len(stats)} nafar\n"
            f"😶 Qatnashmaganlar: {len(absent)} nafar\n\n"
            f"⚠️ Batafsil statistikani yuborishda xatolik yuz berdi."
        )


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


async def cmd_statistika(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Oxirgi 10 kundagi a'zolar faollik statistikasi."""
    if not await check_approval(update, context):
        return

    chat = update.effective_chat

    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text("❗ Bu buyruq faqat guruhlarda ishlaydi.")
        return

    if not await is_admin(update, context):
        await update.message.reply_text("❌ Faqat guruh adminlari statistikani ko'ra oladi.")
        return

    data = await asyncio.to_thread(db.get_member_stats_last_n_days, chat.id, 10)

    if data['total_sessions'] == 0:
        await update.message.reply_text(
            "📊 Oxirgi 10 kun ichida hech qanday yakunlangan sessiya topilmadi."
        )
        return

    total = data['total_sessions']
    members = data['members']

    active = []
    inactive = []
    for m in members:
        attended = m['sessions_attended']
        pct = round(attended / total * 100)
        entry = {**m, 'pct': pct}
        if pct >= 50:
            active.append(entry)
        else:
            inactive.append(entry)

    lines = [
        f"📊 <b>Oxirgi 10 kunlik statistika</b>",
        f"📅 Jami yakunlangan sessiyalar: <b>{total}</b> ta",
        "",
    ]

    if active:
        lines.append(f"✅ <b>Faol a'zolar ({len(active)} nafar):</b>")
        for i, m in enumerate(active, 1):
            name = format_username(m)
            lines.append(f"{i}. {name} — <b>{m['sessions_attended']}/{total}</b> sessiya ({m['pct']}%)")
        lines.append("")

    if inactive:
        lines.append(f"⚠️ <b>Nofaol a'zolar ({len(inactive)} nafar):</b>")
        for i, m in enumerate(inactive, 1):
            name = format_username(m)
            lines.append(f"{i}. {name} — <b>{m['sessions_attended']}/{total}</b> sessiya ({m['pct']}%)")

    message = "\n".join(lines)

    # Telegram 4096 belgi chegarasi uchun himoya
    if len(message) > 4000:
        mid = len(lines) // 2
        part1 = "\n".join(lines[:mid])
        part2 = "\n".join(lines[mid:])
        await update.message.reply_text(part1, parse_mode=ParseMode.HTML)
        await update.message.reply_text(part2, parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)


# -----------------------------------------------------------------
# Asosiy funksiya
# -----------------------------------------------------------------

def build_application():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("boshladik", cmd_boshladik))
    app.add_handler(CommandHandler("yakunladik", cmd_yakunladik))
    app.add_handler(CommandHandler("holat", cmd_holat))
    app.add_handler(CommandHandler("guruhlar", cmd_guruhlar))
    app.add_handler(CommandHandler("statistika", cmd_statistika))
    app.add_handler(CommandHandler("logs", cmd_logs))
    app.add_handler(CallbackQueryHandler(callback_query_handler))
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
