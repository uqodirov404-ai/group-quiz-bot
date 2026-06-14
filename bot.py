import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ContextTypes,
    filters
)
from config import BOT_TOKEN, ADMIN_ID
import database as db
from ai_grader import check_answer_with_ai

logger = logging.getLogger(__name__)

# Topics pagination page size
PAGE_SIZE = 8

def get_topic_keyboard(page: int = 0):
    topics = db.get_topics()
    total_topics = len(topics)
    total_pages = (total_topics + PAGE_SIZE - 1) // PAGE_SIZE
    
    start_idx = page * PAGE_SIZE
    end_idx = min(start_idx + PAGE_SIZE, total_topics)
    
    keyboard = []
    for idx in range(start_idx, end_idx):
        topic = topics[idx]
        # Storing topic index instead of name to avoid 64-byte limit in callback_data
        keyboard.append([InlineKeyboardButton(topic[:45], callback_data=f"seltop_{idx}")])
        
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Oldingi", callback_data=f"page_{page-1}"))
    nav_buttons.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Keyingi ➡️", callback_data=f"page_{page+1}"))
        
    keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton("🔙 Bekor qilish", callback_data="cancel_quiz")])
    return InlineKeyboardMarkup(keyboard)

def get_interval_keyboard(topic_idx: int):
    keyboard = [
        [
            InlineKeyboardButton("10 soniya", callback_data=f"quizstart_{topic_idx}_10"),
            InlineKeyboardButton("20 soniya", callback_data=f"quizstart_{topic_idx}_20"),
            InlineKeyboardButton("30 soniya", callback_data=f"quizstart_{topic_idx}_30")
        ],
        [
            InlineKeyboardButton("1 daqiqa (60s)", callback_data=f"quizstart_{topic_idx}_60"),
            InlineKeyboardButton("2 daqiqa (120s)", callback_data=f"quizstart_{topic_idx}_120")
        ],
        [
            InlineKeyboardButton("🔙 Orqaga", callback_data="page_0")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# Start Command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type in ["group", "supergroup"]:
        # Group start does nothing or outputs welcome if approved
        grp = db.get_group(chat.id)
        if grp and grp['status'] == 'approved':
            await update.message.reply_text("🤖 Bot faol. O'yinni boshlash uchun adminlar `/test` buyrug'ini berishlari mumkin.")
        return
        
    welcome_text = (
        f"Assalomu alaykum, {user.first_name}! 👋\n\n"
        "Men guruhlarda savol-javob o'yinini o'tkazadigan botman.\n"
        "Meni biror guruhga qo'shing, so'ngra bot egasi tasdiqlaganidan keyin guruhda test o'tkazishingiz mumkin."
    )
    if user.id == ADMIN_ID:
        welcome_text += "\n\nSiz bot egasisiz. Guruhlarni boshqarish uchun `/groups` buyrug'ini yuboring."
        
    await update.message.reply_text(welcome_text)

# Chat Member Join/Leave Handler
async def my_chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    my_member = update.my_chat_member
    if not my_member:
        return
        
    chat = my_member.chat
    new_status = my_member.new_chat_member.status
    
    # Check if the bot was added to the group
    if new_status in ["member", "administrator"]:
        grp = db.get_group(chat.id)
        
        # If group is already approved, do nothing
        if grp and grp['status'] == 'approved':
            await context.bot.send_message(
                chat_id=chat.id,
                text="🎉 Bot qaytadan faollashtirildi! Adminlar `/test` orqali o'yin boshlashlari mumkin."
            )
            return
            
        # Register new group as pending
        db.save_group(chat.id, chat.title, status='pending')
        
        # Notify the group
        await context.bot.send_message(
            chat_id=chat.id,
            text=(
                f"🤖 **Salom! Men guruh savol-javob botiman.**\n\n"
                f"Ushbu guruhda botdan foydalanish uchun bot egasining tasdig'i kutilmoqda.\n"
                f"Raqamli so'rov yuborildi. Iltimos, bot egasi ruxsat berishini kuting.\n"
                f"Guruh admini bot egasi bilan bog'lanishi mumkin."
            )
        )
        
        # Notify the Admin
        admin_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("Ruxsat berish ✅", callback_data=f"grp_approve_{chat.id}"),
                InlineKeyboardButton("Rad etish ❌", callback_data=f"grp_reject_{chat.id}")
            ]
        ])
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"📥 **Yangi guruhga qo'shilish so'rovi:**\n\n"
                f"Guruh nomi: **{chat.title}**\n"
                f"Guruh ID: `{chat.id}`\n\n"
                f"Botni ushbu guruhda ishga tushirishga ruxsat berasizmi?"
            ),
            reply_markup=admin_keyboard
        )
    elif new_status in ["kicked", "left"]:
        # Update group status to disabled
        db.update_group_status(chat.id, 'disabled')

# /groups command for admin
async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return
        
    groups = db.get_all_groups()
    if not groups:
        await update.message.reply_text("Hozircha hech qanday guruh ro'yxatdan o'tmagan.")
        return
        
    text = "📋 **Guruhlar ro'yxati:**\n\n"
    keyboard = []
    for g in groups:
        status_emoji = "⏳" if g['status'] == 'pending' else "✅" if g['status'] == 'approved' else "❌" if g['status'] == 'rejected' else "📴"
        text += f"{status_emoji} **{g['title']}**\nID: `{g['group_id']}`\nHolati: `{g['status']}`\n\n"
        
        # Generate toggle buttons
        if g['status'] == 'approved':
            keyboard.append([InlineKeyboardButton(f"🚫 {g['title'][:20]} o'chirish", callback_data=f"adm_disable_{g['group_id']}")])
        else:
            keyboard.append([InlineKeyboardButton(f"✅ {g['title'][:20]} faollashtirish", callback_data=f"adm_approve_{g['group_id']}")])
            
    await update.message.reply_text(
        text, 
        parse_mode="Markdown", 
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
    )

# /test command in groups
async def test_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("⚠️ Ushbu buyruq faqat guruhlarda ishlaydi.")
        return
        
    # Check if group is approved
    grp = db.get_group(chat.id)
    if not grp or grp['status'] != 'approved':
        await update.message.reply_text("❌ Guruh uchun bot faollashtirilmagan yoki o'chirib qo'yilgan. Iltimos bot egasiga murojaat qiling.")
        return
        
    # Check if user is admin
    try:
        member = await context.bot.get_chat_member(chat_id=chat.id, user_id=user.id)
        if member.status not in ["administrator", "creator"] and user.id != ADMIN_ID:
            await update.message.reply_text("⚠️ Ushbu buyruqni faqat guruh adminlari ishlata oladi.")
            return
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        return
        
    # Check if a quiz is already active
    active = db.get_active_quiz(chat.id)
    if active:
        await update.message.reply_text("⚠️ Ushbu guruhda allaqachon faol o'yin ketmoqda. Uni to'xtatish va natijalarni ko'rish uchun `/natija` yozing.")
        return
        
    # Present topic selection
    await update.message.reply_text(
        "📚 **Savol-javob o'yini uchun mavzuni tanlang:**",
        reply_markup=get_topic_keyboard(0)
    )

# /natija command to cancel current game and show results
async def natija_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    
    if chat.type not in ["group", "supergroup"]:
        return
        
    active = db.get_active_quiz(chat.id)
    if not active:
        await update.message.reply_text("❌ Guruhda faol o'yin topilmadi.")
        return
        
    # Check if admin
    member = await context.bot.get_chat_member(chat_id=chat.id, user_id=user.id)
    if member.status not in ["administrator", "creator"] and user.id != ADMIN_ID:
        await update.message.reply_text("⚠️ Faqat guruh adminlari o'yinni to'xtata oladi.")
        return
        
    # Get scores before ending
    scores = db.get_quiz_scores(chat.id)
    db.end_quiz(chat.id)
    
    if scores:
        stats_text = (
            f"🏆 **Natijalar (Mavzu: {active['topic']}):**\n\n"
        )
        for rank, s in enumerate(scores, 1):
            user_mention = s['first_name']
            if s['username']:
                user_mention = f"@{s['username']}"
            stats_text += f"{rank}. {user_mention} — **{s['score']} ball**\n"
    else:
        stats_text = "Hech kim ball to'play olmadi."
        
    # Clear session values
    context.chat_data.clear()
    await update.message.reply_text(
        f"⏹ **O'yin to'xtatildi!**\n\n{stats_text}", 
        parse_mode="Markdown"
    )

# Callback Query Handler
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user = update.effective_user
    
    await query.answer()
    
    # 1. Admin approve/reject group joins
    if data.startswith("grp_approve_"):
        grp_id = int(data.split("_")[2])
        db.update_group_status(grp_id, 'approved')
        await query.edit_message_text(f"✅ Guruh tasdiqlandi (ID: `{grp_id}`).")
        
        # Notify the group chat
        try:
            await context.bot.send_message(
                chat_id=grp_id,
                text="🎉 **Bot egasi guruhda botdan foydalanishga ruxsat berdi!**\nGuruh adminlari `/test` orqali o'yinni boshlashlari mumkin."
            )
        except:
            pass
        return
        
    elif data.startswith("grp_reject_"):
        grp_id = int(data.split("_")[2])
        db.update_group_status(grp_id, 'rejected')
        await query.edit_message_text(f"❌ Guruh arizasi rad etildi (ID: `{grp_id}`).")
        
        # Notify group and leave
        try:
            await context.bot.send_message(
                chat_id=grp_id,
                text="❌ **Arizangiz rad etildi.** Bot guruhni tark etmoqda..."
            )
            await context.bot.leave_chat(chat_id=grp_id)
        except:
            pass
        return
        
    # 2. Admin dashboard management
    elif data.startswith("adm_approve_"):
        grp_id = int(data.split("_")[2])
        db.update_group_status(grp_id, 'approved')
        await query.message.reply_text(f"Guruh faollashtirildi: `{grp_id}`")
        # Refresh group list
        await list_groups(update, context)
        return
        
    elif data.startswith("adm_disable_"):
        grp_id = int(data.split("_")[2])
        db.update_group_status(grp_id, 'disabled')
        await query.message.reply_text(f"Guruh o'chirib qo'yildi: `{grp_id}`")
        # Refresh group list
        await list_groups(update, context)
        return
        
    # 3. Topic selection pagination
    elif data.startswith("page_"):
        page = int(data.split("_")[1])
        await query.edit_message_reply_markup(reply_markup=get_topic_keyboard(page))
        return
        
    elif data.startswith("seltop_"):
        topic_idx = int(data.split("_")[1])
        # Ask for interval
        await query.edit_message_text(
            f"⏱ **Mavzu tanlandi.** Savollar orasidagi vaqt oralig'ini belgilang:",
            reply_markup=get_interval_keyboard(topic_idx)
        )
        return
        
    elif data.startswith("quizstart_"):
        parts = data.split("_")
        topic_idx = int(parts[1])
        interval = int(parts[2])
        
        chat_id = query.message.chat_id
        thread_id = query.message.message_thread_id
        topics = db.get_topics()
        
        if topic_idx >= len(topics):
            await query.edit_message_text("❌ Xatolik: Mavzu topilmadi.")
            return
            
        topic = topics[topic_idx]
        questions = db.get_questions_by_topic(topic)
        
        if not questions:
            await query.edit_message_text("❌ Tanlangan mavzuda savollar mavjud emas.")
            return
            
        # Start game loop
        db.save_quiz(chat_id, topic, interval, thread_id)
        db.clear_scores(chat_id)
        
        # Clear inline selection text
        await query.edit_message_text(f"🎮 **O'yin boshlanmoqda!** \nMavzu: *{topic}*\nSavollar oralig'i: *{interval} soniya*", parse_mode="Markdown")
        
        # Start game task
        asyncio.create_task(run_quiz_game(context, chat_id, questions, interval, thread_id))
        return
        
    elif data == "cancel_quiz":
        await query.edit_message_text("❌ O'yin sozlashi bekor qilindi.")
        return

# Active Quiz Game loop
async def run_quiz_game(context: ContextTypes.DEFAULT_TYPE, group_id: int, questions: list, interval_seconds: int, thread_id: int = None):
    # Clear local chat_data winner states
    context.chat_data.clear()
    
    consecutive_unanswered = 0
    
    for idx, q in enumerate(questions):
        # Check if the game is still active before posting next question
        active = db.get_active_quiz(group_id)
        if not active:
            logger.info(f"Quiz terminated by admin in group {group_id}")
            return
            
        # Send question
        text = (
            f"📖 **O'yin:** {idx+1}/{len(questions)}-savol\n"
            f"📚 **Mavzu:** {q['topic']}\n\n"
            f"❓ **SAVOL:**\n{q['question_text']}\n\n"
            f"💬 *Javob berish uchun ushbu xabarga javob (reply) yuboring!*"
        )
        try:
            msg = await context.bot.send_message(chat_id=group_id, text=text, message_thread_id=thread_id)
            # Save question index and msg id to database
            db.update_quiz_question(group_id, idx, msg.message_id)
        except Exception as e:
            logger.error(f"Failed to send question to group {group_id}: {e}")
            db.end_quiz(group_id)
            return
            
        # Wait for interval or correct answer
        answered_correctly = False
        for _ in range(interval_seconds):
            # Check if quiz is still active (was not cancelled)
            active = db.get_active_quiz(group_id)
            if not active:
                return
                
            # Check if winner registered in chat_data
            if context.chat_data.get(f"q_{idx}_winner"):
                answered_correctly = True
                break
                
            await asyncio.sleep(1)
            
        if answered_correctly:
            consecutive_unanswered = 0
            # Short pause before next question
            await asyncio.sleep(3)
        else:
            # Check again just in case a race condition happened in the last second
            if context.chat_data.get(f"q_{idx}_winner"):
                consecutive_unanswered = 0
                await asyncio.sleep(3)
                continue
                
            consecutive_unanswered += 1
            
            # Time's up, post correct answer
            time_up_text = (
                f"⏰ **Vaqt tugadi!**\n\n"
                f"Hech kim to'g'ri javob bermadi.\n"
                f"To'g'ri javob: *{q['answer_text']}*"
            )
            try:
                await context.bot.send_message(chat_id=group_id, text=time_up_text, parse_mode="Markdown", message_thread_id=thread_id)
            except Exception as e:
                logger.error(f"Error sending time's up: {e}")
                
            # If 3 consecutive questions are unanswered, end the game
            if consecutive_unanswered >= 3:
                try:
                    await context.bot.send_message(
                        chat_id=group_id,
                        text="⚠️ **Ketma-ket 3 ta savolga hech kim javob bermadi. O'yin to'xtatildi.**",
                        parse_mode="Markdown",
                        message_thread_id=thread_id
                    )
                except Exception as e:
                    logger.error(f"Error sending inactivity message: {e}")
                break
                
            await asyncio.sleep(3)
            
    # Game finished! Generate leaderboard
    scores = db.get_quiz_scores(group_id)
    if scores:
        stats_text = (
            f"🏆 **O'yin yakunlandi!** 🏆\n\n"
            f"📚 **Mavzu:** {questions[0]['topic']}\n\n"
            f"📊 **Natijalar (Reyting):**\n"
        )
        for rank, s in enumerate(scores, 1):
            user_mention = s['first_name']
            if s['username']:
                user_mention = f"@{s['username']}"
            stats_text += f"{rank}. {user_mention} — **{s['score']} ball**\n"
    else:
        stats_text = (
            f"🏁 **O'yin yakunlandi!**\n\n"
            f"📚 **Mavzu:** {questions[0]['topic']}\n\n"
            f"Hech kim to'g'ri javob bera olmadi va ball to'plamadi."
        )
        
    try:
        await context.bot.send_message(chat_id=group_id, text=stats_text, parse_mode="Markdown", message_thread_id=thread_id)
    except Exception as e:
        logger.error(f"Error sending scoreboard: {e}")
        
    db.end_quiz(group_id)
    context.chat_data.clear()

# Message Handler for Q&A in groups
async def group_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return
        
    chat_id = update.effective_chat.id
    
    # Verify if a quiz is active
    active = db.get_active_quiz(chat_id)
    if not active:
        return
        
    # Check if message is a reply to the bot's question message
    if not message.reply_to_message:
        return
        
    curr_msg_id = active['current_msg_id']
    if message.reply_to_message.message_id != curr_msg_id:
        return
        
    # Check if this question is already answered correctly
    q_idx = active['current_question_index']
    if context.chat_data.get(f"q_{q_idx}_winner"):
        return
        
    user_answer = message.text.strip()
    topic = active['topic']
    questions = db.get_questions_by_topic(topic)
    
    if q_idx >= len(questions):
        return
        
    current_q = questions[q_idx]
    
    # Grade the answer using AI Grader
    is_correct = await check_answer_with_ai(
        current_q['question_text'],
        current_q['answer_text'],
        user_answer
    )
    
    if is_correct:
        # Check double-entry protection (prevent race conditions)
        if context.chat_data.get(f"q_{q_idx}_winner"):
            return
            
        user = update.effective_user
        # Save winner state in local chat context
        context.chat_data[f"q_{q_idx}_winner"] = {
            'user_id': user.id,
            'first_name': user.first_name,
            'username': user.username
        }
        
        # Add score
        db.add_score(chat_id, user.id, user.first_name, user.username)
        
        # Send confirmation
        congrats_text = (
            f"🎉 **To'g'ri javob!**\n\n"
            f"Ishtirokchi: {user.first_name}\n"
            f"Qabul qilingan to'g'ri javob: *{current_q['answer_text']}*"
        )
        await message.reply_text(congrats_text, parse_mode="Markdown")

def build_application():
    # Setup handlers
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("groups", list_groups))
    app.add_handler(CommandHandler("test", test_command))
    app.add_handler(CommandHandler("natija", natija_command))
    
    # Callback queries
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    # Chat join/leave events
    app.add_handler(ChatMemberHandler(my_chat_member_handler, ChatMemberHandler.MY_CHAT_MEMBER))
    
    # Group message replies checking Q&A
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS, group_answer_handler))
    
    return app
