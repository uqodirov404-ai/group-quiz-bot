import os

ADMIN_ID = int(os.environ.get("ADMIN_ID", "162634410"))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
NEON_DATABASE_URL = os.environ.get("NEON_DATABASE_URL", "")

QUIZ_BOT_TOKEN = os.environ.get("QUIZ_BOT_TOKEN", "")
QUIZ_DB_PATH = os.environ.get("QUIZ_DB_PATH", "quiz_database.db")
QUIZ_EXCEL_PATH = os.environ.get("QUIZ_EXCEL_PATH", "lib_6a104385a7508.xlsx")

ESSE_BOT_TOKEN = os.environ.get("ESSE_BOT_TOKEN", "")
WEBAPP_URL_ESSE = os.environ.get("WEBAPP_URL_ESSE", "")

SAVOLJAVOB_BOT_TOKEN = os.environ.get("SAVOLJAVOB_BOT_TOKEN", "")
