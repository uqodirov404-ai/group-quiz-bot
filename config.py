import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "162634410"))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

EXCEL_PATH = os.environ.get("EXCEL_PATH", "lib_6a104385a7508.xlsx")
DB_PATH = os.environ.get("DB_PATH", "quiz_database.db")
