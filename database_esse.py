import psycopg2
from psycopg2 import pool
from contextlib import contextmanager
from datetime import datetime
from config import NEON_DATABASE_URL as DATABASE_URL
import logging

logger = logging.getLogger(__name__)

try:
    db_pool = psycopg2.pool.ThreadedConnectionPool(1, 20, dsn=DATABASE_URL)
except Exception as e:
    print(f"Baza ulanishida xato: {e}")
    db_pool = None

@contextmanager
def get_db():
    if not db_pool:
        yield None
        return
    
    conn = None
    is_direct_conn = False
    for _ in range(3):
        try:
            conn = db_pool.getconn()
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
            break # Connection is healthy
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
            logger.error(f"Database direct connection error: {e}")
            yield None
            return

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
    if not db_pool: return
    with get_db() as conn:
        with conn.cursor() as cursor:
            # users jadvali
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    first_name TEXT,
                    username TEXT,
                    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # Add balance column if not exists
            cursor.execute('''
                ALTER TABLE users ADD COLUMN IF NOT EXISTS balance BIGINT DEFAULT 0
            ''')
            
            # essays (AI)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS essays (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id),
                    topic TEXT,
                    criteria TEXT,
                    essay_text TEXT,
                    result_text TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # experts
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS experts (
                    user_id BIGINT PRIMARY KEY REFERENCES users(user_id),
                    status TEXT DEFAULT 'pending', -- pending, active, rejected
                    bio TEXT,
                    rating FLOAT DEFAULT 0.0,
                    reviews_count INT DEFAULT 0,
                    total_earned BIGINT DEFAULT 0,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # essays_human
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS essays_human (
                    id SERIAL PRIMARY KEY,
                    user_id BIGINT REFERENCES users(user_id),
                    expert_id BIGINT REFERENCES experts(user_id),
                    topic TEXT,
                    criteria TEXT,
                    essay_text TEXT,
                    photo_file_id TEXT,
                    status TEXT DEFAULT 'pending_payment', -- pending_payment, checking, done
                    receipt_photo_id TEXT,
                    score FLOAT,
                    feedback TEXT,
                    price BIGINT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    checked_at TIMESTAMP
                )
            ''')
            
            # channels
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS channels (
                    channel_id TEXT PRIMARY KEY,
                    title TEXT,
                    url TEXT
                )
            ''')
            
            # settings
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            
            # Set default price
            cursor.execute('''
                INSERT INTO settings (key, value) VALUES ('expert_price', '20000')
                ON CONFLICT (key) DO NOTHING
            ''')
            
            cursor.execute('''
                INSERT INTO settings (key, value) VALUES ('payment_card', '8600123456789012')
                ON CONFLICT (key) DO NOTHING
            ''')
            
        conn.commit()

init_db()

def save_user(user_id: int, first_name: str, username: str):
    if not db_pool: return
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                INSERT INTO users (user_id, first_name, username) 
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET first_name=EXCLUDED.first_name, username=EXCLUDED.username
            ''', (user_id, first_name, username))
        conn.commit()

def get_user(user_id: int):
    if not db_pool: return None
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
            return cursor.fetchone()

def update_balance(user_id: int, amount: int):
    if not db_pool: return
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (amount, user_id))
        conn.commit()

def get_setting(key: str) -> str:
    if not db_pool: return ""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT value FROM settings WHERE key = %s", (key,))
            row = cursor.fetchone()
            return row[0] if row else ""

def set_setting(key: str, value: str):
    if not db_pool: return
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                INSERT INTO settings (key, value) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value
            ''', (key, value))
        conn.commit()

def get_channels():
    if not db_pool: return []
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT channel_id, title, url FROM channels")
            return cursor.fetchall()

def add_channel(channel_id: str, title: str, url: str):
    if not db_pool: return
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                INSERT INTO channels (channel_id, title, url) VALUES (%s, %s, %s)
                ON CONFLICT (channel_id) DO UPDATE SET title=EXCLUDED.title, url=EXCLUDED.url
            ''', (channel_id, title, url))
        conn.commit()

def remove_channel(channel_id: int):
    if not db_pool: return
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM channels WHERE channel_id = %s", (channel_id,))
        conn.commit()

def add_expert_application(user_id: int, bio: str):
    if not db_pool: return
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                INSERT INTO experts (user_id, status, bio) VALUES (%s, 'pending', %s)
                ON CONFLICT (user_id) DO UPDATE SET bio=EXCLUDED.bio, status='pending'
            ''', (user_id, bio))
        conn.commit()

def get_pending_experts():
    if not db_pool: return []
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT e.user_id, u.first_name, e.bio 
                FROM experts e 
                JOIN users u ON e.user_id = u.user_id 
                WHERE e.status = 'pending'
            ''')
            return cursor.fetchall()

def update_expert_status(user_id: int, status: str):
    if not db_pool: return
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE experts SET status = %s WHERE user_id = %s", (status, user_id))
        conn.commit()

def get_active_experts():
    if not db_pool: return []
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT e.user_id, u.first_name, e.bio, e.rating, e.reviews_count 
                FROM experts e 
                JOIN users u ON e.user_id = u.user_id 
                WHERE e.status = 'active'
            ''')
            return cursor.fetchall()

def get_expert(user_id: int):
    if not db_pool: return None
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM experts WHERE user_id = %s", (user_id,))
            return cursor.fetchone()

def create_human_essay(user_id: int, expert_id: int, topic: str, criteria: str, essay_text: str, photo_file_id: str, price: int):
    if not db_pool: return None
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                INSERT INTO essays_human (user_id, expert_id, topic, criteria, essay_text, photo_file_id, status, price)
                VALUES (%s, %s, %s, %s, %s, %s, 'pending_payment', %s)
                RETURNING id
            ''', (user_id, expert_id, topic, criteria, essay_text, photo_file_id, price))
            conn.commit()
            return cursor.fetchone()[0]

def update_human_essay_receipt(essay_id: int, receipt_photo_id: str):
    if not db_pool: return
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE essays_human SET receipt_photo_id = %s WHERE id = %s", (receipt_photo_id, essay_id))
        conn.commit()

def update_human_essay_status(essay_id: int, status: str):
    if not db_pool: return
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE essays_human SET status = %s WHERE id = %s", (status, essay_id))
        conn.commit()

def get_human_essay(essay_id: int):
    if not db_pool: return None
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM essays_human WHERE id = %s", (essay_id,))
            return cursor.fetchone()

def get_expert_pending_essays(expert_id: int):
    if not db_pool: return []
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM essays_human WHERE expert_id = %s AND status = 'checking'", (expert_id,))
            return cursor.fetchall()

def finish_human_essay(essay_id: int, score: float, feedback: str):
    if not db_pool: return
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                UPDATE essays_human 
                SET status = 'done', score = %s, feedback = %s, checked_at = CURRENT_TIMESTAMP
                WHERE id = %s
            ''', (score, feedback, essay_id))
            
            # Ekspert pullini hisoblash (statistikada)
            cursor.execute("SELECT expert_id, price FROM essays_human WHERE id = %s", (essay_id,))
            row = cursor.fetchone()
            if row:
                cursor.execute("UPDATE experts SET total_earned = total_earned + %s WHERE user_id = %s", (row[1], row[0]))
        conn.commit()

def rate_expert(expert_id: int, new_rating: int):
    if not db_pool: return
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT rating, reviews_count FROM experts WHERE user_id = %s", (expert_id,))
            row = cursor.fetchone()
            if row:
                curr_rating = row[0]
                count = row[1]
                total = curr_rating * count
                new_count = count + 1
                updated_rating = (total + new_rating) / new_count
                cursor.execute("UPDATE experts SET rating = %s, reviews_count = %s WHERE user_id = %s", (updated_rating, new_count, expert_id))
        conn.commit()

def save_essay(user_id: int, topic: str, criteria: str, essay_text: str, result_text: str):
    if not db_pool: return
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                INSERT INTO essays (user_id, topic, criteria, essay_text, result_text)
                VALUES (%s, %s, %s, %s, %s)
            ''', (user_id, topic, criteria, essay_text, result_text))
        conn.commit()

def get_stats(user_id: int):
    if not db_pool: return 0
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM essays WHERE user_id = %s", (user_id,))
            ai_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM essays_human WHERE user_id = %s", (user_id,))
            human_count = cursor.fetchone()[0]
            return ai_count + human_count

def reset_expert_earnings(expert_id: int):
    if not db_pool: return
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE experts SET total_earned = 0 WHERE user_id = %s", (expert_id,))
        conn.commit()
