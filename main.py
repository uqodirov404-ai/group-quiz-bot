import logging
import asyncio
import os
import threading
import requests
import aiofiles
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, File, UploadFile, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from telegram import Update
from telegram.ext import ContextTypes

import config
import database_quiz as db_quiz
import database_esse as db_esse
import database_savoljavob as db_savoljavob

import bot_quiz
import bot_esse
import bot_savoljavob
from ai_engine import check_essay_text, check_essay_image

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Detect if webhook should be active
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://group-quiz-bot.onrender.com")
RUN_WEBHOOK = "onrender.com" in WEBAPP_URL or os.environ.get("RUN_WEBHOOK", "false").lower() == "true"

# Build individual applications
app_quiz = bot_quiz.build_application()
app_esse = bot_esse.build_application()
app_savoljavob = bot_savoljavob.build_application()

# Background cleanup job for Quiz bot
async def quiz_cleanup_job_callback(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Background cleanup check started...")
    last_cleanup_str = db_quiz.get_setting("last_cleanup_time", "")
    now = datetime.now()
    
    if not last_cleanup_str:
        db_quiz.set_setting("last_cleanup_time", now.isoformat())
        logger.info("Initial cleanup time set.")
        return
        
    try:
        last_cleanup = datetime.fromisoformat(last_cleanup_str)
    except Exception as e:
        logger.error(f"Error parsing last_cleanup_time: {e}")
        db_quiz.set_setting("last_cleanup_time", now.isoformat())
        return
        
    if now - last_cleanup >= timedelta(days=10):
        if not db_quiz.is_any_quiz_active():
            logger.info("Performing 10-day server/database cleanup...")
            try:
                conn = db_quiz.get_db_connection()
                conn.execute("VACUUM")
                conn.close()
                db_quiz.set_setting("last_cleanup_time", now.isoformat())
                
                await context.bot.send_message(
                    chat_id=config.ADMIN_ID,
                    text="🧹 **Tizim tozalash xabari:**\n\n10 kunlik bazani tozalash va optimallashtirish (`VACUUM`) ishlari muvaffaqiyatli bajarildi!"
                )
                logger.info("Cleanup completed successfully.")
            except Exception as ex:
                logger.error(f"Error running database vacuum: {ex}")
        else:
            logger.info("Cleanup skipped because a quiz is currently active. Will retry next time.")

@app.on_event("startup")
async def startup_event():
    # 1. Initialize databases
    db_quiz.init_db()
    db_esse.init_db()
    db_savoljavob.init_db()
    
    if RUN_WEBHOOK:
        # Initialize and start Quiz Bot
        await app_quiz.initialize()
        await app_quiz.start()
        
        # Schedule cleanup job for Quiz Bot
        if app_quiz.job_queue:
            app_quiz.job_queue.run_repeating(
                quiz_cleanup_job_callback,
                interval=14400, # 4 hours
                first=10
            )
            logger.info("Background cleanup job scheduled for Quiz Bot.")
            
        webhook_url_quiz = f"{WEBAPP_URL}/webhook-quiz"
        await app_quiz.bot.set_webhook(webhook_url_quiz)
        logger.info(f"Quiz Bot Webhook set to: {webhook_url_quiz}")
        
        # Initialize and start Esse Bot
        await app_esse.initialize()
        await app_esse.start()
        webhook_url_esse = f"{WEBAPP_URL}/webhook-esse"
        await app_esse.bot.set_webhook(webhook_url_esse)
        logger.info(f"Esse Bot Webhook set to: {webhook_url_esse}")
        
        # Initialize and start SavolJavob Bot
        await app_savoljavob.initialize()
        await app_savoljavob.start()
        webhook_url_sj = f"{WEBAPP_URL}/webhook-savoljavob"
        await app_savoljavob.bot.set_webhook(webhook_url_sj)
        logger.info(f"SavolJavob Bot Webhook set to: {webhook_url_sj}")
    else:
        # Delete webhooks for local polling
        for bot_token in [config.QUIZ_BOT_TOKEN, config.ESSE_BOT_TOKEN, config.SAVOLJAVOB_BOT_TOKEN]:
            try:
                requests.get(f"https://api.telegram.org/bot{bot_token}/deleteWebhook")
            except Exception as e:
                logger.error(f"Error deleting webhook: {e}")
        logger.info("Webhooks deleted for local polling.")

@app.on_event("shutdown")
async def shutdown_event():
    if RUN_WEBHOOK:
        await app_quiz.stop()
        await app_quiz.shutdown()
        
        await app_esse.stop()
        await app_esse.shutdown()
        
        await app_savoljavob.stop()
        await app_savoljavob.shutdown()

# Webhook Endpoints
@app.post("/webhook-quiz")
async def webhook_quiz(request: Request):
    if not RUN_WEBHOOK:
        return JSONResponse(status_code=404, content={"status": "not_active"})
    try:
        data = await request.json()
        update = Update.de_json(data, app_quiz.bot)
        await app_quiz.process_update(update)
    except Exception as e:
        logger.error(f"Error Quiz Bot webhook: {e}")
    return JSONResponse(content={"status": "ok"})

@app.post("/webhook-esse")
async def webhook_esse(request: Request):
    if not RUN_WEBHOOK:
        return JSONResponse(status_code=404, content={"status": "not_active"})
    try:
        data = await request.json()
        update = Update.de_json(data, app_esse.bot)
        await app_esse.process_update(update)
    except Exception as e:
        logger.error(f"Error Esse Bot webhook: {e}")
    return JSONResponse(content={"status": "ok"})

@app.post("/webhook-savoljavob")
async def webhook_savoljavob(request: Request):
    if not RUN_WEBHOOK:
        return JSONResponse(status_code=404, content={"status": "not_active"})
    try:
        data = await request.json()
        update = Update.de_json(data, app_savoljavob.bot)
        await app_savoljavob.process_update(update)
    except Exception as e:
        logger.error(f"Error SavolJavob Bot webhook: {e}")
    return JSONResponse(content={"status": "ok"})

# Essay Webapp Frontend Static & JS Routes
@app.get("/")
async def read_index():
    index_path = os.path.join(os.path.dirname(__file__), "webapp", "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Server is running</h1>")

@app.get("/app.js")
async def read_js():
    js_path = os.path.join(os.path.dirname(__file__), "webapp", "app.js")
    if os.path.exists(js_path):
        with open(js_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read(), media_type="application/javascript")
    return JSONResponse(status_code=404, content={"status": "not_found"})

# Essay Webapp Upload Route
@app.post("/upload")
async def upload_essay(
    user_id: int = Form(...),
    criteria: str = Form(...),
    topic: str = Form(""),
    text: str = Form(""),
    file: UploadFile = File(None)
):
    try:
        requests.post(
            f"https://api.telegram.org/bot{config.ESSE_BOT_TOKEN}/sendMessage",
            json={"chat_id": user_id, "text": "⏳ Essengiz qabul qilindi. AI uni tekshirmoqda, kuting..."}
        )

        async def process_and_send():
            result = ""
            try:
                if file and file.filename:
                    file_location = f"temp_{user_id}_{file.filename}"
                    async with aiofiles.open(file_location, 'wb') as out_file:
                        content = await file.read()
                        await out_file.write(content)
                    
                    result = await check_essay_image(file_location, criteria, topic)
                    os.remove(file_location)
                elif text:
                    result = await check_essay_text(text, criteria, topic)
                else:
                    result = "⚠️ Iltimos, esse matnini yozing yoki rasm yuklang!"
            except Exception as e:
                result = f"Xatolik yuz berdi: {str(e)}"
            
            requests.post(
                f"https://api.telegram.org/bot{config.ESSE_BOT_TOKEN}/sendMessage",
                json={"chat_id": user_id, "text": result, "parse_mode": "Markdown"}
            )
            
        asyncio.create_task(process_and_send())
        return JSONResponse(content={"status": "ok"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})

@app.get("/status")
async def get_status():
    return JSONResponse(content={
        "status": "running", 
        "webhook": RUN_WEBHOOK,
        "bots": ["group-quiz-bot", "esse-expert-ai-bot", "telegram-savol-javob-bot"]
    })

def main():
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Unified FastAPI Web Server running on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
