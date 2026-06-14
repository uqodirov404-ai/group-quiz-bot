import logging
import asyncio
import os
import threading
import requests
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn
from telegram import Update
from telegram.ext import ContextTypes
import database as db
import bot
from config import ADMIN_ID, BOT_TOKEN

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# FastAPI app initialization
app = FastAPI()

# Check if running on Render
WEBAPP_URL = os.environ.get("WEBAPP_URL", "")
RUN_WEBHOOK = "onrender.com" in WEBAPP_URL or os.environ.get("RUN_WEBHOOK", "false").lower() == "true"

bot_app = bot.build_application()

async def cleanup_job_callback(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Background cleanup check started...")
    last_cleanup_str = db.get_setting("last_cleanup_time", "")
    now = datetime.now()
    
    if not last_cleanup_str:
        db.set_setting("last_cleanup_time", now.isoformat())
        logger.info("Initial cleanup time set.")
        return
        
    try:
        last_cleanup = datetime.fromisoformat(last_cleanup_str)
    except Exception as e:
        logger.error(f"Error parsing last_cleanup_time: {e}")
        db.set_setting("last_cleanup_time", now.isoformat())
        return
        
    if now - last_cleanup >= timedelta(days=10):
        if not db.is_any_quiz_active():
            logger.info("Performing 10-day server/database cleanup...")
            try:
                conn = db.get_db_connection()
                conn.execute("VACUUM")
                conn.close()
                
                db.set_setting("last_cleanup_time", now.isoformat())
                
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text="🧹 **Tizim tozalash xabari:**\n\n10 kunlik bazani tozalash va optimallashtirish (`VACUUM`) ishlari muvaffaqiyatli bajarildi!"
                )
                logger.info("Cleanup completed successfully.")
            except Exception as ex:
                logger.error(f"Error running database vacuum: {ex}")
        else:
            logger.info("Cleanup skipped because a quiz is currently active in a group. Will retry next time.")

@app.on_event("startup")
async def startup_event():
    # Initialize DB tables and Q&A from Excel
    db.init_db()
    
    if RUN_WEBHOOK:
        # Initialize Telegram application for webhooks
        await bot_app.initialize()
        await bot_app.start()
        
        # Schedule cleanup job
        if bot_app.job_queue:
            bot_app.job_queue.run_repeating(
                cleanup_job_callback,
                interval=14400, # 4 hours
                first=10
            )
            logger.info("Background cleanup job scheduled under Webhook mode.")
            
        webhook_url = f"{WEBAPP_URL}/webhook"
        await bot_app.bot.set_webhook(webhook_url)
        logger.info(f"Webhook successfully set to: {webhook_url}")
    else:
        # Delete webhook so local polling works
        try:
            requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook")
            logger.info("Webhook deleted for local polling.")
        except Exception as e:
            logger.error(f"Error deleting webhook: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    if RUN_WEBHOOK:
        await bot_app.stop()
        await bot_app.shutdown()

@app.post("/webhook")
async def telegram_webhook(request: Request):
    if not RUN_WEBHOOK:
        return JSONResponse(status_code=404, content={"status": "not_active"})
    try:
        data = await request.json()
        update = Update.de_json(data, bot_app.bot)
        await bot_app.process_update(update)
    except Exception as e:
        logger.error(f"Error processing webhook update: {e}")
    return JSONResponse(content={"status": "ok"})

@app.get("/")
async def read_index():
    return JSONResponse(content={"status": "running", "webhook": RUN_WEBHOOK})

def run_local_polling():
    # Run polling in separate event loop for local development
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    local_app = bot.build_application()
    if local_app.job_queue:
        local_app.job_queue.run_repeating(
            cleanup_job_callback,
            interval=14400,
            first=10
        )
        logger.info("Background cleanup job scheduled under Polling mode.")
        
    logger.info("Savol-Javob Boti ishga tushmoqda (Polling)...")
    local_app.run_polling(stop_signals=())

def main():
    if not RUN_WEBHOOK:
        # Start local polling in a separate daemon thread
        polling_thread = threading.Thread(target=run_local_polling, daemon=True)
        polling_thread.start()
        
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"FastAPI Web Server running on port {port}...")
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
