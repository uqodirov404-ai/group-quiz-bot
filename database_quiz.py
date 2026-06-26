import psycopg2
import psycopg2.extras
from psycopg2 import pool
from contextlib import contextmanager
import openpyxl
import os
import logging
from datetime import datetime
from config import NEON_DATABASE_URL as DATABASE_URL, QUIZ_EXCEL_PATH as EXCEL_PATH

logger = logging.getLogger(__name__)

db_pool = None

def init_pool():
    global db_pool
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL topilmadi! Baza manzili noto'g'ri.")
    if db_pool is None:
        db_pool = pool.ThreadedConnectionPool(1, 20, dsn=DATABASE_URL)

@contextmanager
def get_db():
    if db_pool is None:
        init_pool()
        
    conn = None
    is_direct_conn = False
    
    for _ in range(3):
        try:
            conn = db_pool.getconn()
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
            break
        except Exception:
            if conn:
                try:
                    db_pool.putconn(conn, close=True)
                except Exception:
                    pass
            conn = None
            
    if conn is None:
        try:
            conn = psycopg2.connect(dsn=DATABASE_URL)
            is_direct_conn = True
        except Exception as e:
            raise e

    try:
        yield conn
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        raise e
    finally:
        try:
            if is_direct_conn:
                conn.close()
            else:
                db_pool.putconn(conn)
        except Exception:
            pass

def init_db():
    with get_db() as conn:
        with conn.cursor() as cursor:
            # quiz_groups table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS quiz_groups (
                    group_id BIGINT PRIMARY KEY,
                    title TEXT,
                    status TEXT DEFAULT 'pending', -- pending, approved, rejected, disabled
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    approved_at TIMESTAMP
                )
            ''')
            
            # quiz_questions table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS quiz_questions (
                    id SERIAL PRIMARY KEY,
                    topic TEXT,
                    question_num INTEGER,
                    question_text TEXT,
                    answer_text TEXT
                )
            ''')
            
            # quiz_active_quizzes table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS quiz_active_quizzes (
                    group_id BIGINT PRIMARY KEY,
                    topic TEXT,
                    interval_seconds INTEGER,
                    current_question_index INTEGER DEFAULT 0,
                    current_msg_id INTEGER,
                    is_active INTEGER DEFAULT 0,
                    message_thread_id BIGINT
                )
            ''')
            
            # quiz_quiz_scores table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS quiz_quiz_scores (
                    group_id BIGINT,
                    user_id BIGINT,
                    first_name TEXT,
                    username TEXT,
                    score INTEGER DEFAULT 0,
                    PRIMARY KEY (group_id, user_id)
                )
            ''')
            
            # quiz_settings table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS quiz_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            
            # Pre-approve the test group ID to persist
            cursor.execute('''
                INSERT INTO quiz_groups (group_id, title, status, approved_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (group_id) DO NOTHING
            ''', (-1003642185233, "Test Group", "approved"))
            
            # Pre-approve KUZGI ATT 86+ JAMOA group
            cursor.execute('''
                INSERT INTO quiz_groups (group_id, title, status, approved_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (group_id) DO NOTHING
            ''', (-1003956030872, "KUZGI ATT 86+ JAMOA", "approved"))
            
        conn.commit()
    
    # Automatically import Q&A if the table is empty
    if is_questions_empty():
        import_excel_to_db()

def is_questions_empty():
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM quiz_questions")
            count = cursor.fetchone()[0]
            return count == 0

def import_excel_to_db(custom_path=None):
    path_to_use = custom_path if custom_path else EXCEL_PATH
    print(f"Excel faylidan savollarni bazaga import qilish boshlandi: {path_to_use}")
    if not os.path.exists(path_to_use):
        logger.error(f"Excel fayli topilmadi: {path_to_use}")
        return 0
        
    try:
        wb = openpyxl.load_workbook(path_to_use, data_only=True)
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
            
            if val_id_str == "Savol №" or val_id_str.startswith("ADABIYOT FANIDAN") or val_id_str.startswith("Maktab darsliklari"):
                continue
                
            if val_id and (val_q is None and val_ans is None):
                current_topic = val_id_str
                continue
                
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
            with get_db() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("DELETE FROM quiz_questions")
                    cursor.executemany('''
                        INSERT INTO quiz_questions (topic, question_num, question_text, answer_text)
                        VALUES (%s, %s, %s, %s)
                    ''', questions_to_insert)
                conn.commit()
            print(f"Muvaffaqiyatli yuklandi: {len(questions_to_insert)} ta savol.")
            return len(questions_to_insert)
        return 0
    except Exception as e:
        logger.error(f"Excel importda xatolik: {e}")
        print(f"Xatolik yuz berdi: {e}")
        return 0

def insert_questions(questions_list):
    questions_to_insert = []
    for idx, q in enumerate(questions_list, 1):
        questions_to_insert.append((
            q.get('topic') or "Umumiy adabiyot",
            idx,
            q['question_text'].strip(),
            q['answer_text'].strip()
        ))
        
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM quiz_questions")
            cursor.executemany('''
                INSERT INTO quiz_questions (topic, question_num, question_text, answer_text)
                VALUES (%s, %s, %s, %s)
            ''', questions_to_insert)
        conn.commit()
    return len(questions_to_insert)

# Groups helpers
def save_group(group_id: int, title: str, status='pending'):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                INSERT INTO quiz_groups (group_id, title, status)
                VALUES (%s, %s, %s)
                ON CONFLICT(group_id) DO UPDATE SET title=EXCLUDED.title
            ''', (group_id, title, status))
        conn.commit()

def get_group(group_id: int):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT * FROM quiz_groups WHERE group_id = %s", (group_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

def update_group_status(group_id: int, status: str):
    with get_db() as conn:
        with conn.cursor() as cursor:
            if status == 'approved':
                cursor.execute('''
                    UPDATE quiz_groups 
                    SET status = %s, approved_at = CURRENT_TIMESTAMP 
                    WHERE group_id = %s
                ''', (status, group_id))
            else:
                cursor.execute('''
                    UPDATE quiz_groups SET status = %s WHERE group_id = %s
                ''', (status, group_id))
        conn.commit()

def get_all_groups():
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT * FROM quiz_groups ORDER BY added_at DESC")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

# Topics and Questions helpers
def get_topics():
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT DISTINCT topic FROM quiz_questions ORDER BY topic ASC")
            rows = cursor.fetchall()
            return [r[0] for r in rows]

def get_questions_by_topic(topic: str):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute('''
                SELECT id, topic, question_num, question_text, answer_text 
                FROM quiz_questions 
                WHERE topic = %s 
                ORDER BY question_num ASC
            ''', (topic,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

# Active Quiz helpers
def save_quiz(group_id: int, topic: str, interval_seconds: int, thread_id: int = None):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                INSERT INTO quiz_active_quizzes (group_id, topic, interval_seconds, current_question_index, is_active, message_thread_id)
                VALUES (%s, %s, %s, 0, 1, %s)
                ON CONFLICT(group_id) DO UPDATE SET
                    topic = EXCLUDED.topic,
                    interval_seconds = EXCLUDED.interval_seconds,
                    current_question_index = 0,
                    is_active = 1,
                    message_thread_id = EXCLUDED.message_thread_id
            ''', (group_id, topic, interval_seconds, thread_id))
        conn.commit()

def get_active_quiz(group_id: int):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT * FROM quiz_active_quizzes WHERE group_id = %s AND is_active = 1", (group_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

def update_quiz_question(group_id: int, index: int, msg_id: int):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                UPDATE quiz_active_quizzes 
                SET current_question_index = %s, current_msg_id = %s 
                WHERE group_id = %s
            ''', (index, msg_id, group_id))
        conn.commit()

def end_quiz(group_id: int):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE quiz_active_quizzes SET is_active = 0 WHERE group_id = %s", (group_id,))
        conn.commit()

def is_any_quiz_active():
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM quiz_active_quizzes WHERE is_active = 1")
            count = cursor.fetchone()[0]
            return count > 0

# Quiz Scores helpers
def add_score(group_id: int, user_id: int, first_name: str, username: str):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                INSERT INTO quiz_quiz_scores (group_id, user_id, first_name, username, score)
                VALUES (%s, %s, %s, %s, 1)
                ON CONFLICT(group_id, user_id) DO UPDATE SET score = quiz_quiz_scores.score + 1
            ''', (group_id, user_id, first_name, username))
        conn.commit()

def register_participant(group_id: int, user_id: int, first_name: str, username: str):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                INSERT INTO quiz_quiz_scores (group_id, user_id, first_name, username, score)
                VALUES (%s, %s, %s, %s, 0)
                ON CONFLICT(group_id, user_id) DO NOTHING
            ''', (group_id, user_id, first_name, username))
        conn.commit()

def get_quiz_scores(group_id: int):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute('''
                SELECT user_id, first_name, username, score 
                FROM quiz_quiz_scores 
                WHERE group_id = %s 
                ORDER BY score DESC, first_name ASC
            ''', (group_id,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

def clear_scores(group_id: int):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM quiz_quiz_scores WHERE group_id = %s", (group_id,))
        conn.commit()

# Settings helpers
def get_setting(key: str, default: str = "") -> str:
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT value FROM quiz_settings WHERE key = %s", (key,))
            row = cursor.fetchone()
            return row[0] if row else default

def set_setting(key: str, value: str):
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                INSERT INTO quiz_settings (key, value)
                VALUES (%s, %s)
                ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value
            ''', (key, value))
        conn.commit()
