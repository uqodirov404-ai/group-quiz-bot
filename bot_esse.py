import json
import logging
import asyncio
import os
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler, ConversationHandler

from config import BOT_TOKEN
import database_esse as db
import ai_engine

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

async def send_long_message(bot, chat_id, text, parse_mode="HTML", reply_markup=None):
    if len(text) <= 4000:
        try:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode, reply_markup=reply_markup)
        except Exception:
            await bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
        return

    chunks = []
    temp_text = text
    while len(temp_text) > 4000:
        split_idx = temp_text.rfind('\n', 0, 4000)
        if split_idx == -1 or split_idx < 3000:
            split_idx = 4000
        chunks.append(temp_text[:split_idx])
        temp_text = temp_text[split_idx:]
    if temp_text:
        chunks.append(temp_text)

    for i, chunk in enumerate(chunks):
        markup = reply_markup if i == len(chunks) - 1 else None
        try:
            await bot.send_message(chat_id=chat_id, text=chunk, parse_mode=parse_mode, reply_markup=markup)
        except Exception:
            clean_chunk = chunk.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
            await bot.send_message(chat_id=chat_id, text=clean_chunk, reply_markup=markup)

ADMIN_ID = 162634410

(RECEIPT, EXPERT_BIO, EXPERT_FEEDBACK, ADMIN_PRICE, ADMIN_CARD, ADMIN_CHANNEL_ID, ADMIN_CHANNEL_URL, ADMIN_CHANNEL_DEL, ADMIN_MSG_TO_USER, AI_UPLOAD, HUMAN_UPLOAD) = range(11)

def get_main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🤖 AI Tekshiruv (Bepul)")],
        [KeyboardButton("👨‍🏫 Ekspertga tekshirtirish (Pullik)")],
        [KeyboardButton("👤 Kabinet")],
        [KeyboardButton("🎓 Ekspert bo'lish")]
    ], resize_keyboard=True)

def get_cancel_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("🔙 Bekor qilish")]], resize_keyboard=True)

def get_done_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("✅ Tayyor"), KeyboardButton("🔙 Bekor qilish")]], resize_keyboard=True)

async def check_sub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    channels = db.get_channels()
    if not channels: return True
    is_sub = True
    keyboard = []
    for cid, title, url in channels:
        try:
            member = await context.bot.get_chat_member(chat_id=cid, user_id=user_id)
            if member.status in ['left', 'kicked']:
                is_sub = False
                keyboard.append([InlineKeyboardButton(title, url=url)])
        except Exception:
            is_sub = False
            keyboard.append([InlineKeyboardButton(title, url=url)])
    if not is_sub:
        keyboard.append([InlineKeyboardButton("Tasdiqlash ✅", callback_data="check_sub_btn")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        msg = "Botdan foydalanish uchun quyidagi kanallarga obuna bo'lishingiz majburiy:"
        if update.message:
            await update.message.reply_text(msg, reply_markup=reply_markup)
        elif update.callback_query:
            await update.callback_query.message.reply_text(msg, reply_markup=reply_markup)
        return False
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.save_user(user.id, user.first_name, user.username)
    if not await check_sub(update, context): return
    welcome_text = (
        f"Assalomu alaykum, {user.first_name}! 👋\n\n"
        "Siz bu yerda essengizni AI (Bepul) yoki haqiqiy Inson Eksperti (Pullik) orqali tekshirishingiz mumkin.\n"
    )
    await update.message.reply_text(welcome_text, reply_markup=get_main_keyboard())

async def general_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_sub(update, context): return
    user = update.effective_user
    text = update.message.text if update.message.text else ""
    
    if text == "🔙 Bekor qilish":
        await update.message.reply_text("Bosh menyu", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    if text == "📝 Esseni yuborish":
        if context.user_data.get('pending_essay_id'):
            await update.message.reply_text("Essengiz matnini yoki bir nechta rasmlarini yuboring.\nBarcha rasmlarni yuklab bo'lgach '✅ Tayyor' tugmasini bosing:", reply_markup=get_done_keyboard())
            context.user_data['human_photos'] = []
            context.user_data['human_text'] = ""
            return HUMAN_UPLOAD
        else:
            await update.message.reply_text("Sizda faol tekshiruv so'rovi yo'q.", reply_markup=get_main_keyboard())
            return ConversationHandler.END

    if text == "👤 Kabinet":
        stats = db.get_stats(user.id)
        user_db = db.get_user(user.id)
        balance = user_db[4] if user_db and len(user_db) > 4 else 0
        exp_db = db.get_expert(user.id)
        exp_text = ""
        if exp_db and exp_db[1] == 'active':
            stars = "⭐" * int(round(exp_db[3])) if exp_db[4] > 0 else "Yangi"
            exp_text = f"\n\n👨‍🏫 <b>Ekspert Profili</b>\nReyting: {stars} ({exp_db[4]} ta sharh)\nIshlangan pul: {exp_db[5]} UZS"
        msg = f"👤 <b>Kabinet</b>\n\nIsm: {user.first_name}\nJami tekshirilgan esselar: {stats}\nBalans: {balance} UZS{exp_text}"
        keyboard = []
        if user.id == ADMIN_ID:
            keyboard.append([InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")])
        if exp_db and exp_db[1] == 'active':
            keyboard.append([InlineKeyboardButton("📋 Yangi esselarni ko'rish", callback_data="expert_tasks")])
        await update.message.reply_text(msg, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)

    elif text == "🎓 Ekspert bo'lish":
        exp_db = db.get_expert(user.id)
        if exp_db:
            if exp_db[1] == 'active':
                await update.message.reply_text("Siz tasdiqlangan ekspertsiz!")
                return
            elif exp_db[1] == 'pending':
                await update.message.reply_text("Arizangiz ko'rib chiqilmoqda.")
                return
        await update.message.reply_text("O'zingiz haqingizda ma'lumot (bio), tajribangiz haqida yozing:", reply_markup=get_cancel_keyboard())
        return EXPERT_BIO

    elif text == "🤖 AI Tekshiruv (Bepul)":
        await update.message.reply_text("Essengiz matnini yoki bir nechta rasmlarini yuboring.\nBarcha rasmlarni yuklab bo'lgach '✅ Tayyor' tugmasini bosing:", reply_markup=get_done_keyboard())
        context.user_data['ai_photos'] = []
        context.user_data['ai_text'] = ""
        return AI_UPLOAD

    elif text == "👨‍🏫 Ekspertga tekshirtirish (Pullik)":
        experts = db.get_active_experts()
        if not experts:
            await update.message.reply_text("Faol ekspertlar yo'q.")
            return
        msg = "👨‍🏫 <b>Ekspertlar ro'yxati:</b>\n\n"
        keyboard = []
        for exp in experts:
            uid, fname, bio, rating, count = exp
            stars = "⭐" * int(round(rating)) if count > 0 else "Yangi"
            msg += f"👤 {fname}\n{stars} ({count} ta sharh)\n📝 {bio}\n\n"
            keyboard.append([InlineKeyboardButton(f"{fname} ni tanlash", callback_data=f"choose_exp_{uid}")])
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def receive_ai_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🔙 Bekor qilish":
        await update.message.reply_text("Bosh menyu", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        context.user_data['ai_photos'].append(file_id)
        await update.message.reply_text(f"Rasm qabul qilindi ({len(context.user_data['ai_photos'])} ta). Yana yuborishingiz yoki '✅ Tayyor' tugmasini bosishingiz mumkin.", reply_markup=get_done_keyboard())
        return AI_UPLOAD
        
    if text and text != "✅ Tayyor":
        context.user_data['ai_text'] += text + "\n"
        await update.message.reply_text("Matn qabul qilindi. Yana yuborishingiz yoki '✅ Tayyor' tugmasini bosishingiz mumkin.", reply_markup=get_done_keyboard())
        return AI_UPLOAD

    if text == "✅ Tayyor":
        photos = context.user_data.get('ai_photos', [])
        essay_text = context.user_data.get('ai_text', "")
        
        if not photos and not essay_text.strip():
            await update.message.reply_text("Hech narsa yubormadingiz! Yoki rasm, yoki matn yuboring.", reply_markup=get_done_keyboard())
            return AI_UPLOAD
            
        await update.message.reply_text("⏳ Essengiz qabul qilindi. Sun'iy intellekt uni tekshirmoqda.\n\nBu jarayon 1-2 daqiqa vaqt olishi mumkin. Natija tayyor bo'lishi bilan sizga yuboramiz.", reply_markup=get_main_keyboard())
        
        # Process AI logic in background
        asyncio.create_task(process_ai_task(update, context, essay_text, photos))
        return ConversationHandler.END

async def process_ai_task(update, context, text, photos):
    try:
        user_id = update.effective_user.id
        
        if photos:
            paths = []
            for i, p_id in enumerate(photos):
                file_path = f"temp_{user_id}_{i}.jpg"
                file = await context.bot.get_file(p_id)
                await file.download_to_drive(file_path)
                paths.append(file_path)
            
            res = await ai_engine.check_essay_image(paths)
            
            for p in paths:
                try: os.remove(p)
                except: pass
                
            db.save_essay(user_id, "", "", text, res)
            await send_long_message(context.bot, user_id, f"🤖 <b>AI Xulosasi:</b>\n\n{res}", parse_mode="HTML")
        else:
            res = await ai_engine.check_essay_text("", text, "")
            db.save_essay(user_id, "", "", text, res)
            await send_long_message(context.bot, user_id, f"🤖 <b>AI Xulosasi:</b>\n\n{res}", parse_mode="HTML")
    except Exception as e:
        await context.bot.send_message(chat_id=user_id, text=f"Xatolik yuz berdi: {e}")

async def receive_human_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🔙 Bekor qilish":
        await update.message.reply_text("Bekor qilindi. Istalgan vaqtda yuborish uchun '📝 Esseni yuborish' tugmasini bosing.", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("📝 Esseni yuborish")]], resize_keyboard=True))
        return ConversationHandler.END

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        if 'human_photos' not in context.user_data: context.user_data['human_photos'] = []
        context.user_data['human_photos'].append(f"photo:{file_id}")
        await update.message.reply_text(f"Rasm qabul qilindi ({len(context.user_data['human_photos'])} ta). Yana yuboring yoki '✅ Tayyor' ni bosing.", reply_markup=get_done_keyboard())
        return HUMAN_UPLOAD

    if update.message.document:
        file_id = update.message.document.file_id
        if 'human_photos' not in context.user_data: context.user_data['human_photos'] = []
        context.user_data['human_photos'].append(f"doc:{file_id}")
        await update.message.reply_text(f"Hujjat (PDF/Word) qabul qilindi ({len(context.user_data['human_photos'])} ta). Yana yuboring yoki '✅ Tayyor' ni bosing.", reply_markup=get_done_keyboard())
        return HUMAN_UPLOAD
        
    if text and text != "✅ Tayyor":
        if 'human_text' not in context.user_data: context.user_data['human_text'] = ""
        context.user_data['human_text'] += text + "\n"
        await update.message.reply_text("Matn qabul qilindi. Yana yuboring yoki '✅ Tayyor' ni bosing.", reply_markup=get_done_keyboard())
        return HUMAN_UPLOAD

    if text == "✅ Tayyor":
        essay_id = context.user_data.get('pending_essay_id')
        photos = context.user_data.get('human_photos', [])
        essay_text = context.user_data.get('human_text', "")
        
        db.update_human_essay_status(essay_id, "checking")
        with db.get_db() as conn:
            with conn.cursor() as cursor:
                # Save all photos/docs ids concatenated by comma (simple fix for db text)
                photo_str = ",".join(photos) if photos else ""
                cursor.execute("UPDATE essays_human SET essay_text=%s, photo_file_id=%s WHERE id=%s", (essay_text, photo_str, essay_id))
            conn.commit()
            
        essay = db.get_human_essay(essay_id)
        exp_id = essay[2]
        
        await update.message.reply_text("Essengiz ekspertga yuborildi! Javobini kuting.", reply_markup=get_main_keyboard())
        await context.bot.send_message(chat_id=exp_id, text="🔔 Sizga yangi esse keldi! 'Kabinet' dagi 'Yangi esselarni ko'rish' tugmasi orqali ko'rishingiz mumkin.")
        
        context.user_data['pending_essay_id'] = None
        context.user_data['human_photos'] = []
        context.user_data['human_text'] = ""
        return ConversationHandler.END

async def receive_expert_bio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🔙 Bekor qilish":
        await update.message.reply_text("Bosh menyu", reply_markup=get_main_keyboard())
        return ConversationHandler.END
        
    db.add_expert_application(update.effective_user.id, update.message.text)
    await update.message.reply_text("Arizangiz adminga yuborildi! Arizani tasdiqlash uchun @Umidjon_Qodirov ga murojaat qiling.", reply_markup=get_main_keyboard())
    admin_text = f"🆕 <b>Yangi Ekspert Arizasi</b>\nID: {update.effective_user.id}\nFoydalanuvchi: {update.effective_user.first_name}\nBio: {update.message.text}"
    keyboard = [
        [InlineKeyboardButton("Qabul qilish", callback_data=f"exp_accept_{update.effective_user.id}"), InlineKeyboardButton("Rad etish", callback_data=f"exp_reject_{update.effective_user.id}")],
        [InlineKeyboardButton("Xabar yozish", callback_data=f"exp_msg_{update.effective_user.id}")]
    ]
    await context.bot.send_message(chat_id=ADMIN_ID, text=admin_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END

async def receive_admin_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🔙 Bekor qilish":
        await update.message.reply_text("Bekor qilindi", reply_markup=get_main_keyboard())
        return ConversationHandler.END
    db.set_setting("expert_price", update.message.text)
    await update.message.reply_text("Narx muvaffaqiyatli o'zgartirildi!", reply_markup=get_main_keyboard())
    return ConversationHandler.END

async def receive_admin_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🔙 Bekor qilish":
        await update.message.reply_text("Bekor qilindi", reply_markup=get_main_keyboard())
        return ConversationHandler.END
    db.set_setting("payment_card", update.message.text)
    await update.message.reply_text("Karta raqami muvaffaqiyatli o'zgartirildi!", reply_markup=get_main_keyboard())
    return ConversationHandler.END

def extract_telegram_username(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    if text.startswith('@'):
        return text
    if "t.me/" in text:
        parts = text.split("t.me/")
        if len(parts) > 1:
            sub = parts[1].split('/')[0]
            if sub and not sub.startswith('+') and sub != 'joinchat':
                return '@' + sub
    import re
    if re.match(r'^[a-zA-Z0-9_]+$', text):
        return '@' + text
    return ""

async def receive_admin_channel_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip() if update.message.text else ""
    if text == "🔙 Bekor qilish":
        await update.message.reply_text("Bekor qilindi", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    if '|' in text:
        parts = text.split('|')
        if len(parts) >= 3:
            cid = parts[0].strip()
            title = parts[1].strip()
            url = parts[2].strip()
            db.add_channel(cid, title, url)
            await update.message.reply_text(
                f"✅ Kanal muvaffaqiyatli qo'shildi!\n\nID: <code>{cid}</code>\nNomi: <b>{title}</b>\nHavola: {url}",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            return ConversationHandler.END
        elif len(parts) == 2:
            cid = parts[0].strip()
            url = parts[1].strip()
            title = "Kanal"
            try:
                chat = await context.bot.get_chat(cid)
                if chat.title:
                    title = chat.title
            except Exception:
                pass
            db.add_channel(cid, title, url)
            await update.message.reply_text(
                f"✅ Kanal muvaffaqiyatli qo'shildi!\n\nID: <code>{cid}</code>\nNomi: <b>{title}</b>\nHavola: {url}",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            return ConversationHandler.END

    username = extract_telegram_username(text)
    if username:
        try:
            chat = await context.bot.get_chat(username)
            cid = str(chat.id)
            title = chat.title
            url = text if (text.startswith("http://") or text.startswith("https://")) else f"https://t.me/{chat.username}"
            db.add_channel(cid, title, url)
            await update.message.reply_text(
                f"✅ Kanal muvaffaqiyatli qo'shildi!\n\nID: <code>{cid}</code>\nNomi: <b>{title}</b>\nHavola: {url}",
                parse_mode="HTML",
                reply_markup=get_main_keyboard()
            )
            return ConversationHandler.END
        except Exception as e:
            logger.error(f"Automatic channel resolve failed: {e}")
            await update.message.reply_text(
                f"❌ Kanalni avtomatik aniqlab bo'lmadi.\n"
                f"Sababi: Bot kanalda admin emas yoki xato havola.\n\n"
                f"Iltimos, kanal ID va nomini qo'lda quyidagi formatlardan birida kiriting:\n\n"
                f"1. <code>KanalID | Havola</code> (Bot avtomatik nomini oladi)\n"
                f"2. <code>KanalID | Nomi | Havola</code>\n\n"
                f"Masalan: <code>-100123456789 | https://t.me/kanal_linki</code>",
                parse_mode="HTML",
                reply_markup=get_cancel_keyboard()
            )
            return ADMIN_CHANNEL_ID

    if text.startswith('-') or text.isdigit():
        context.user_data['temp_channel_id'] = text
        await update.message.reply_text(
            "Kanal ssilkasi va nomini kiriting (Masalan: Bizning Kanal|https://t.me/kanal):",
            reply_markup=get_cancel_keyboard()
        )
        return ADMIN_CHANNEL_URL

    await update.message.reply_text(
        "Tushunarsiz format. Iltimos, kanal havolasini yuboring (masalan: @kanal yoki https://t.me/kanal) yoki quyidagi formatda kiriting:\n\n"
        "<code>KanalID | Havola</code>",
        parse_mode="HTML",
        reply_markup=get_cancel_keyboard()
    )
    return ADMIN_CHANNEL_ID

async def receive_admin_channel_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🔙 Bekor qilish":
        await update.message.reply_text("Bekor qilindi", reply_markup=get_main_keyboard())
        return ConversationHandler.END
    parts = update.message.text.split('|')
    if len(parts) == 2:
        db.add_channel(context.user_data['temp_channel_id'].strip(), parts[0].strip(), parts[1].strip())
        await update.message.reply_text("Kanal qo'shildi!", reply_markup=get_main_keyboard())
    else:
        await update.message.reply_text("Noto'g'ri format. Boshqatdan urinib ko'ring.", reply_markup=get_main_keyboard())
    return ConversationHandler.END

async def receive_admin_channel_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🔙 Bekor qilish":
        await update.message.reply_text("Bekor qilindi", reply_markup=get_main_keyboard())
        return ConversationHandler.END
    db.remove_channel(update.message.text.strip())
    await update.message.reply_text("Kanal o'chirildi!", reply_markup=get_main_keyboard())
    return ConversationHandler.END

async def receive_admin_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🔙 Bekor qilish":
        await update.message.reply_text("Bekor qilindi", reply_markup=get_main_keyboard())
        return ConversationHandler.END
    target_id = context.user_data.get('msg_target_id')
    if target_id:
        try:
            await context.bot.send_message(chat_id=target_id, text=f"👨‍💻 <b>Admindan xabar:</b>\n\n{update.message.text}", parse_mode="HTML")
            await update.message.reply_text("Xabar muvaffaqiyatli yetkazildi!", reply_markup=get_main_keyboard())
        except Exception as e:
            await update.message.reply_text(f"Xatolik: xabar yuborib bo'lmadi.\n{e}", reply_markup=get_main_keyboard())
    return ConversationHandler.END

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user = update.effective_user
    
    if data == "check_sub_btn":
        if await check_sub(update, context):
            await query.message.delete()
            await query.message.reply_text("Rahmat! Endi botdan foydalanishingiz mumkin.", reply_markup=get_main_keyboard())
        return

    if not await check_sub(update, context): return

    if data.startswith("exp_accept_") and user.id == ADMIN_ID:
        exp_id = int(data.split("_")[2])
        db.update_expert_status(exp_id, "active")
        await query.edit_message_text("Ekspert qabul qilindi!")
        await context.bot.send_message(chat_id=exp_id, text="Ekspertlik arizangiz qabul qilindi!")
        
    elif data.startswith("exp_reject_") and user.id == ADMIN_ID:
        exp_id = int(data.split("_")[2])
        db.update_expert_status(exp_id, "rejected")
        await query.edit_message_text("Ekspert rad etildi.")
        
    elif data.startswith("del_exp_") and user.id == ADMIN_ID:
        exp_id = int(data.split("_")[2])
        db.update_expert_status(exp_id, "rejected")
        await query.edit_message_text("Ekspert tizimdan o'chirildi!")
        try:
            await context.bot.send_message(chat_id=exp_id, text="Sizning ekspertlik huquqingiz admin tomonidan bekor qilindi.")
        except Exception:
            pass
        
    elif data.startswith("exp_msg_") and user.id == ADMIN_ID:
        exp_id = int(data.split("_")[2])
        context.user_data['msg_target_id'] = exp_id
        await query.message.reply_text(f"Foydalanuvchi ({exp_id}) ga yubormoqchi bo'lgan xabaringizni yozing:", reply_markup=get_cancel_keyboard())
        return ADMIN_MSG_TO_USER
        
    elif data.startswith("choose_exp_"):
        exp_id = int(data.split("_")[2])
        context.user_data['selected_expert'] = exp_id
        price = db.get_setting("expert_price") or "20000"
        card = db.get_setting("payment_card") or "Karta kiritilmagan"
        text = f"Siz ekspert tanladingiz.\n\n💳 Xizmat narxi: {price} UZS\nKarta raqami: <code>{card}</code>\n\nTo'lov cheki (skrinshot)ni yuboring."
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=get_cancel_keyboard())
        return RECEIPT

    elif data.startswith("pay_ok_") and user.id == ADMIN_ID:
        essay_id = int(data.split("_")[2])
        essay = db.get_human_essay(essay_id)
        if essay:
            db.update_human_essay_status(essay_id, "approved")
            await query.edit_message_caption(caption=query.message.caption + "\n\n✅ To'lov tasdiqlandi!")
            await context.bot.send_message(
                chat_id=essay[1], 
                text="✅ To'lov tasdiqlandi!\n\nEssengizni yuborishni boshlash uchun quyidagi <b>\"📝 Esseni yuborish\"</b> tugmasini bosing.", 
                parse_mode="HTML",
                reply_markup=ReplyKeyboardMarkup([[KeyboardButton("📝 Esseni yuborish")]], resize_keyboard=True)
            )
            if essay[1] not in context.application.user_data: context.application.user_data[essay[1]] = {}
            context.application.user_data[essay[1]]['pending_essay_id'] = essay_id
            context.application.user_data[essay[1]]['human_photos'] = []
            context.application.user_data[essay[1]]['human_text'] = ""
            
    elif data.startswith("pay_no_") and user.id == ADMIN_ID:
        essay_id = int(data.split("_")[2])
        essay = db.get_human_essay(essay_id)
        if essay:
            db.update_human_essay_status(essay_id, "rejected")
            await query.edit_message_caption(caption=query.message.caption + "\n\n❌ To'lov rad etildi!")
            try:
                await context.bot.send_message(chat_id=essay[1], text="❌ Kechirasiz, siz yuborgan to'lov cheki rad etildi. Iltimos, qaytadan tekshirib ko'ring yoki admin bilan bog'laning.")
            except:
                pass

    elif data.startswith("rate_"):
        parts = data.split("_")
        db.rate_expert(int(parts[1]), int(parts[2]))
        await query.edit_message_text(f"Rahmat! Siz ekspertga {parts[2]} ⭐ baho berdingiz.")

    elif data == "admin_panel" and user.id == ADMIN_ID:
        keyboard = [
            [InlineKeyboardButton("💰 Narx", callback_data="admin_set_price"), InlineKeyboardButton("💳 Karta", callback_data="admin_set_card")],
            [InlineKeyboardButton("📢 Kanal qo'shish", callback_data="admin_add_channel"), InlineKeyboardButton("🗑 Kanal o'chirish", callback_data="admin_del_channel")],
            [InlineKeyboardButton("📊 Ekspertlar hisoboti", callback_data="admin_expert_report"), InlineKeyboardButton("🗑 Ekspert o'chirish", callback_data="admin_del_expert")]
        ]
        await query.message.reply_text("⚙️ <b>Admin Panel</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data == "admin_set_price" and user.id == ADMIN_ID:
        await query.message.reply_text("Yangi narxni kiriting (masalan: 30000):", reply_markup=get_cancel_keyboard())
        return ADMIN_PRICE
    elif data == "admin_set_card" and user.id == ADMIN_ID:
        await query.message.reply_text("Yangi karta raqamini kiriting:", reply_markup=get_cancel_keyboard())
        return ADMIN_CARD
    elif data == "admin_add_channel" and user.id == ADMIN_ID:
        msg = (
            "📢 <b>Kanal qo'shish</b>\n\n"
            "Bot kanalda <b>admin</b> bo'lsa, kanal havolasini yuboring (masalan: <code>@kanal_username</code> yoki <code>https://t.me/kanal_username</code>).\n\n"
            "Agar kanal <b>xususiy (private)</b> bo'lsa, quyidagi formatda yuboring:\n"
            "<code>KanalID | Havola</code>\n\n"
            "Masalan: <code>-1001234567890 | https://t.me/+invite_link</code>"
        )
        await query.message.reply_text(msg, parse_mode="HTML", reply_markup=get_cancel_keyboard())
        return ADMIN_CHANNEL_ID
    elif data == "admin_del_channel" and user.id == ADMIN_ID:
        await query.message.reply_text("O'chiriladigan Kanal ID sini kiriting:", reply_markup=get_cancel_keyboard())
        return ADMIN_CHANNEL_DEL
    elif data == "admin_expert_report" and user.id == ADMIN_ID:
        experts = db.get_active_experts()
        report = "📊 <b>Ekspertlar daromadi:</b>\n\n"
        keyboard = []
        for exp in experts:
            with db.get_db() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT total_earned FROM experts WHERE user_id = %s", (exp[0],))
                    row = cursor.fetchone()
                    earned = row[0] if row else 0
            report += f"👤 {exp[1]}: {earned} UZS\n"
            keyboard.append([InlineKeyboardButton(f"🔄 {exp[1]} hisobini tozalash", callback_data=f"clear_exp_bal_{exp[0]}")])
        await query.message.reply_text(report, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)

    elif data.startswith("clear_exp_bal_") and user.id == ADMIN_ID:
        exp_id = int(data.split("_")[3])
        db.reset_expert_earnings(exp_id)
        user_info = db.get_user(exp_id)
        name = user_info[1] if user_info else f"ID: {exp_id}"
        await query.answer(f"{name} hisobi tozalandi!")
        
        experts = db.get_active_experts()
        report = f"✅ <b>{name} hisobi muvaffaqiyatli tozalandi!</b>\n\n📊 <b>Ekspertlar daromadi:</b>\n\n"
        keyboard = []
        for exp in experts:
            with db.get_db() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT total_earned FROM experts WHERE user_id = %s", (exp[0],))
                    row = cursor.fetchone()
                    earned = row[0] if row else 0
            report += f"👤 {exp[1]}: {earned} UZS\n"
            keyboard.append([InlineKeyboardButton(f"🔄 {exp[1]} hisobini tozalash", callback_data=f"clear_exp_bal_{exp[0]}")])
        await query.edit_message_text(report, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None)

    elif data == "admin_del_expert" and user.id == ADMIN_ID:
        experts = db.get_active_experts()
        if not experts:
            await query.message.reply_text("Faol ekspertlar yo'q.")
            return
        keyboard = []
        for exp in experts:
            keyboard.append([InlineKeyboardButton(f"🗑 {exp[1]}", callback_data=f"del_exp_{exp[0]}")])
        await query.message.reply_text("O'chirmoqchi bo'lgan ekspertni tanlang:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == "expert_tasks":
        essays = db.get_expert_pending_essays(user.id)
        if not essays:
            await query.message.reply_text("Yangi esselar yo'q.")
        else:
            for essay in essays:
                essay_id = essay[0]
                msg = f"📝 <b>Esse (#{essay_id})</b>\n\nMatn: {essay[5]}"
                keyboard = [[InlineKeyboardButton("Baholash", callback_data=f"exp_check_{essay_id}")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                photos_str = essay[6]
                if photos_str:
                    file_ids = photos_str.split(',')
                    for idx, fid in enumerate(file_ids):
                        markup = reply_markup if idx == len(file_ids) - 1 else None
                        
                        if fid.startswith("doc:"):
                            actual_fid = fid.split("doc:")[1]
                            await context.bot.send_document(
                                chat_id=user.id,
                                document=actual_fid,
                                caption=f"Esse #{essay_id} Fayl ({idx+1}/{len(file_ids)})" if len(file_ids) > 1 else f"Esse #{essay_id}",
                                reply_markup=markup
                            )
                        else:
                            actual_fid = fid.split("photo:")[1] if fid.startswith("photo:") else fid
                            await context.bot.send_photo(
                                chat_id=user.id,
                                photo=actual_fid,
                                caption=f"Esse #{essay_id} Rasm ({idx+1}/{len(file_ids)})" if len(file_ids) > 1 else f"Esse #{essay_id}",
                                reply_markup=markup
                            )
                else:
                    await context.bot.send_message(chat_id=user.id, text=msg, parse_mode="HTML", reply_markup=reply_markup)

    elif data.startswith("exp_check_"):
        context.user_data['checking_essay_id'] = int(data.split("_")[2])
        await query.message.reply_text(f"Esse uchun xulosa yozing:", reply_markup=get_cancel_keyboard())
        return EXPERT_FEEDBACK

    await query.answer()

async def receive_receipt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text and update.message.text == "🔙 Bekor qilish":
        await update.message.reply_text("Bekor qilindi", reply_markup=get_main_keyboard())
        return ConversationHandler.END
        
    file_id = None
    is_photo = False
    is_doc = False

    if update.message.photo:
        file_id = f"photo:{update.message.photo[-1].file_id}"
        is_photo = True
    elif update.message.document:
        file_id = f"doc:{update.message.document.file_id}"
        is_doc = True
    else:
        return RECEIPT

    price = int(db.get_setting("expert_price") or "20000")
    essay_id = db.create_human_essay(update.effective_user.id, context.user_data.get('selected_expert'), "Kutilmoqda", "Kutilmoqda", "", "", price)
    db.update_human_essay_receipt(essay_id, file_id)
    await update.message.reply_text("Chek qabul qilindi. Tasdiqlash kutilmoqda.", reply_markup=get_main_keyboard())
    
    keyboard = [[InlineKeyboardButton("To'lovni tasdiqlash", callback_data=f"pay_ok_{essay_id}"), InlineKeyboardButton("Rad etish", callback_data=f"pay_no_{essay_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if is_photo:
        actual_fid = file_id.split("photo:")[1]
        await context.bot.send_photo(chat_id=ADMIN_ID, photo=actual_fid, caption=f"To'lov cheki. Summa: {price} UZS", reply_markup=reply_markup)
    elif is_doc:
        actual_fid = file_id.split("doc:")[1]
        await context.bot.send_document(chat_id=ADMIN_ID, document=actual_fid, caption=f"To'lov cheki (hujjat). Summa: {price} UZS", reply_markup=reply_markup)

    return ConversationHandler.END

async def receive_expert_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text and update.message.text == "🔙 Bekor qilish":
        await update.message.reply_text("Bekor qilindi", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    essay_id = context.user_data.get('checking_essay_id')
    essay = db.get_human_essay(essay_id)
    if not essay:
        await update.message.reply_text("Esse topilmadi.", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    feedback_text = ""
    is_voice = False
    is_audio = False
    is_photo = False
    is_doc = False

    if update.message.voice:
        feedback_text = f"voice:{update.message.voice.file_id}"
        is_voice = True
    elif update.message.audio:
        feedback_text = f"audio:{update.message.audio.file_id}"
        is_audio = True
    elif update.message.photo:
        feedback_text = f"photo:{update.message.photo[-1].file_id}"
        is_photo = True
    elif update.message.document:
        feedback_text = f"doc:{update.message.document.file_id}"
        is_doc = True
    elif update.message.text:
        feedback_text = update.message.text
    else:
        await update.message.reply_text("Iltimos, matnli xulosa, ovozli xabar, rasm yoki hujjat yuboring:", reply_markup=get_cancel_keyboard())
        return EXPERT_FEEDBACK

    db.finish_human_essay(essay_id, 0, feedback_text)
    await update.message.reply_text("Javobingiz mijozga yuborildi!", reply_markup=get_main_keyboard())

    user_id = essay[1]
    expert_id = essay[2]
    keyboard = [[InlineKeyboardButton(f"{i}⭐", callback_data=f"rate_{expert_id}_{i}") for i in range(1, 6)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        if is_voice:
            voice_file_id = update.message.voice.file_id
            await context.bot.send_message(chat_id=user_id, text="👨‍🏫 <b>Ekspert javobi (ovozli xabar):</b>", parse_mode="HTML")
            try:
                await context.bot.send_voice(chat_id=user_id, voice=voice_file_id, reply_markup=reply_markup)
            except Exception as ev:
                if "voice_messages_forbidden" in str(ev).lower():
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="⚠️ Sizda ovozli xabarlarni qabul qilish taqiqlanganligi sababli, ekspert javobi fayl ko'rinishida yuborildi."
                    )
                    await context.bot.send_document(chat_id=user_id, document=voice_file_id, reply_markup=reply_markup)
                else:
                    raise ev
        elif is_audio:
            audio_file_id = update.message.audio.file_id
            await context.bot.send_message(chat_id=user_id, text="👨‍🏫 <b>Ekspert javobi (audio fayl):</b>", parse_mode="HTML")
            await context.bot.send_audio(chat_id=user_id, audio=audio_file_id, reply_markup=reply_markup)
        elif is_photo:
            photo_file_id = update.message.photo[-1].file_id
            await context.bot.send_message(chat_id=user_id, text="👨‍🏫 <b>Ekspert javobi (rasm):</b>", parse_mode="HTML")
            await context.bot.send_photo(chat_id=user_id, photo=photo_file_id, reply_markup=reply_markup)
        elif is_doc:
            doc_file_id = update.message.document.file_id
            await context.bot.send_message(chat_id=user_id, text="👨‍🏫 <b>Ekspert javobi (hujjat):</b>", parse_mode="HTML")
            await context.bot.send_document(chat_id=user_id, document=doc_file_id, reply_markup=reply_markup)
        else:
            msg = f"👨‍🏫 <b>Ekspert javobi:</b>\n\n{feedback_text}"
            await send_long_message(context.bot, user_id, msg, parse_mode="HTML", reply_markup=reply_markup)
    except Exception as send_err:
        logger.error(f"Failed to send feedback to client: {send_err}")
        await update.message.reply_text(f"❌ Xatolik yuz berdi: mijozga javobni yuborib bo'lmadi.\n({send_err})")
        return EXPERT_FEEDBACK

    return ConversationHandler.END

def build_application():
    app = Application.builder().token(BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^🎓 Ekspert bo'lish$"), general_handler),
            MessageHandler(filters.Regex("^🤖 AI Tekshiruv \\(Bepul\\)$"), general_handler),
            MessageHandler(filters.Regex("^👨‍🏫 Ekspertga tekshirtirish \\(Pullik\\)$"), general_handler),
            MessageHandler(filters.Regex("^📝 Esseni yuborish$"), general_handler),
            CallbackQueryHandler(callback_handler)
        ],
        states={
            EXPERT_BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_expert_bio)],
            RECEIPT: [MessageHandler(filters.PHOTO | filters.TEXT | filters.Document.ALL, receive_receipt)],
            EXPERT_FEEDBACK: [MessageHandler((filters.TEXT | filters.VOICE | filters.AUDIO | filters.PHOTO | filters.Document.ALL) & ~filters.COMMAND, receive_expert_feedback)],
            ADMIN_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_price)],
            ADMIN_CARD: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_card)],
            ADMIN_CHANNEL_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_channel_id)],
            ADMIN_CHANNEL_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_channel_url)],
            ADMIN_CHANNEL_DEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_channel_del)],
            ADMIN_MSG_TO_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_admin_msg)],
            AI_UPLOAD: [MessageHandler(filters.TEXT | filters.PHOTO, receive_ai_upload)],
            HUMAN_UPLOAD: [MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.ALL, receive_human_upload)],
        },
        fallbacks=[CommandHandler("start", start), MessageHandler(filters.Regex("^🔙 Bekor qilish$"), general_handler)],
        allow_reentry=True
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, general_handler))
    
    return app

def main():
    app = build_application()
    logger.info("Bot ishga tushmoqda (Polling)...")
    app.run_polling(stop_signals=())

if __name__ == "__main__":
    main()
