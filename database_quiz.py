import sqlite3
import openpyxl
import os
import logging
from config import QUIZ_DB_PATH as DB_PATH, QUIZ_EXCEL_PATH as EXCEL_PATH

logger = logging.getLogger(__name__)

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # groups table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS groups (
            group_id INTEGER PRIMARY KEY,
            title TEXT,
            status TEXT DEFAULT 'pending', -- pending, approved, rejected, disabled
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            approved_at TIMESTAMP
        )
    ''')
    
    # questions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT,
            question_num INTEGER,
            question_text TEXT,
            answer_text TEXT
        )
    ''')
    
    # active_quizzes table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS active_quizzes (
            group_id INTEGER PRIMARY KEY,
            topic TEXT,
            interval_seconds INTEGER,
            current_question_index INTEGER DEFAULT 0,
            current_msg_id INTEGER,
            is_active INTEGER DEFAULT 0,
            message_thread_id INTEGER
        )
    ''')
    
    # quiz_scores table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS quiz_scores (
            group_id INTEGER,
            user_id INTEGER,
            first_name TEXT,
            username TEXT,
            score INTEGER DEFAULT 0,
            PRIMARY KEY (group_id, user_id)
        )
    ''')
    
    # settings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    # Pre-approve the test group ID to persist across ephemeral container restarts
    cursor.execute('''
        INSERT OR IGNORE INTO groups (group_id, title, status, approved_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    ''', (-1003642185233, "Test Group", "approved"))
    
    conn.commit()
    conn.close()
    
    # Automatically import Q&A if the table is empty
    if is_questions_empty():
        import_excel_to_db()

def is_questions_empty():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM questions")
    count = cursor.fetchone()[0]
    conn.close()
    return count == 0

def import_excel_to_db():
    print("Excel faylidan savollarni bazaga import qilish boshlandi...")
    if not os.path.exists(EXCEL_PATH):
        logger.error(f"Excel fayli topilmadi: {EXCEL_PATH}")
        return
        
    try:
        wb = openpyxl.load_workbook(EXCEL_PATH, data_only=True)
        sheet = wb.active
        
        current_topic = None
        questions_to_insert = []
        
        for row in sheet.iter_rows(min_row=1):
            val_id = row[0].value
            val_q = row[1].value
            val_ans = row[2].value
            
            if val_id is None and val_q is None and val_ans is None:
                continue
                
            val_id_str = str(val_id).strip()
            
            # Skip headers or sheet titles
            if val_id_str == "Savol №" or val_id_str.startswith("ADABIYOT FANIDAN") or val_id_str.startswith("Maktab darsliklari"):
                continue
                
            # If second and third columns are empty, it's a topic header
            if val_id and (val_q is None and val_ans is None):
                current_topic = val_id_str
                continue
                
            # Save question
            if val_q and val_ans:
                if not current_topic:
                    current_topic = "Boshqa mavzular"
                    
                try:
                    q_num = int(float(val_id))
                except:
                    q_num = 0
                    
                questions_to_insert.append((
                    current_topic,
                    q_num,
                    str(val_q).strip(),
                    str(val_ans).strip()
                ))
                
        if questions_to_insert:
            conn = get_db_connection()
            cursor = conn.cursor()
            # Clear old questions just in case
            cursor.execute("DELETE FROM questions")
            cursor.executemany('''
                INSERT INTO questions (topic, question_num, question_text, answer_text)
                VALUES (?, ?, ?, ?)
            ''', questions_to_insert)
            conn.commit()
            conn.close()
            print(f"Muvaffaqiyatli yuklandi: {len(questions_to_insert)} ta savol.")
    except Exception as e:
        logger.error(f"Excel importda xatolik: {e}")
        print(f"Xatolik yuz berdi: {e}")

# Groups helpers
def save_group(group_id: int, title: str, status='pending'):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO groups (group_id, title, status)
        VALUES (?, ?, ?)
        ON CONFLICT(group_id) DO UPDATE SET title=EXCLUDED.title
    ''', (group_id, title, status))
    conn.commit()
    conn.close()

def get_group(group_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM groups WHERE group_id = ?", (group_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_group_status(group_id: int, status: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    if status == 'approved':
        cursor.execute('''
            UPDATE groups 
            SET status = ?, approved_at = CURRENT_TIMESTAMP 
            WHERE group_id = ?
        ''', (status, group_id))
    else:
        cursor.execute('''
            UPDATE groups SET status = ? WHERE group_id = ?
        ''', (status, group_id))
    conn.commit()
    conn.close()

def get_all_groups():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM groups ORDER BY added_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# Topics and Questions helpers
def get_topics():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT topic FROM questions ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_questions_by_topic(topic: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, topic, question_num, question_text, answer_text 
        FROM questions 
        WHERE topic = ? 
        ORDER BY question_num ASC
    ''', (topic,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# Active Quiz helpers
def save_quiz(group_id: int, topic: str, interval_seconds: int, thread_id: int = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO active_quizzes (group_id, topic, interval_seconds, current_question_index, is_active, message_thread_id)
        VALUES (?, ?, ?, 0, 1, ?)
    ''', (group_id, topic, interval_seconds, thread_id))
    conn.commit()
    conn.close()

def get_active_quiz(group_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM active_quizzes WHERE group_id = ? AND is_active = 1", (group_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_quiz_question(group_id: int, index: int, msg_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE active_quizzes 
        SET current_question_index = ?, current_msg_id = ? 
        WHERE group_id = ?
    ''', (index, msg_id, group_id))
    conn.commit()
    conn.close()

def end_quiz(group_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE active_quizzes SET is_active = 0 WHERE group_id = ?", (group_id,))
    conn.commit()
    conn.close()

def is_any_quiz_active():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM active_quizzes WHERE is_active = 1")
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0

# Quiz Scores helpers
def add_score(group_id: int, user_id: int, first_name: str, username: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO quiz_scores (group_id, user_id, first_name, username, score)
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(group_id, user_id) DO UPDATE SET score = score + 1
    ''', (group_id, user_id, first_name, username))
    conn.commit()
    conn.close()

def register_participant(group_id: int, user_id: int, first_name: str, username: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR IGNORE INTO quiz_scores (group_id, user_id, first_name, username, score)
        VALUES (?, ?, ?, ?, 0)
    ''', (group_id, user_id, first_name, username))
    conn.commit()
    conn.close()

def get_quiz_scores(group_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, first_name, username, score 
        FROM quiz_scores 
        WHERE group_id = ? 
        ORDER BY score DESC, first_name ASC
    ''', (group_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def clear_scores(group_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM quiz_scores WHERE group_id = ?", (group_id,))
    conn.commit()
    conn.close()

# Settings helpers
def get_setting(key: str, default: str = "") -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else default

def set_setting(key: str, value: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value
    ''', (key, value))
    conn.commit()
    conn.close()
