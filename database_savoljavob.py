import psycopg2
import psycopg2.extras
from psycopg2 import pool
from contextlib import contextmanager
from datetime import datetime
from config import NEON_DATABASE_URL as DATABASE_URL

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
    """Bazani ishga tushiradi va jadvallarni yaratadi."""
    with get_db() as conn:
        with conn.cursor() as cursor:
            # Tasdiqlangan guruhlar jadvali
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS approved_groups (
                    chat_id BIGINT PRIMARY KEY,
                    group_name TEXT,
                    status TEXT DEFAULT 'pending', -- 'pending', 'approved', 'rejected'
                    requested_at TEXT NOT NULL
                )
            """)

            # Sessiyalar jadvali
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    is_active INTEGER DEFAULT 1
                )
            """)

            # Xabarlar jadvali
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    session_id INTEGER NOT NULL REFERENCES sessions(id),
                    chat_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    sent_at TEXT NOT NULL
                )
            """)

            # Guruh a'zolari jadvali — xabar yozgan barcha foydalanuvchilar
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS group_members (
                    id SERIAL PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    last_seen TEXT NOT NULL,
                    UNIQUE(chat_id, user_id)
                )
            """)
        conn.commit()


def get_group_status(chat_id: int) -> str | None:
    """Guruhning holatini qaytaradi ('pending', 'approved', 'rejected' yoki None)."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT status FROM approved_groups WHERE chat_id = %s", (chat_id,))
            row = cursor.fetchone()
            return row["status"] if row else None


def request_group_approval(chat_id: int, group_name: str):
    """Yangi guruh ruxsat so'rab bazaga yoziladi."""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO approved_groups (chat_id, group_name, status, requested_at)
                VALUES (%s, %s, 'pending', %s)
                ON CONFLICT(chat_id) DO UPDATE SET
                    status = 'pending',
                    group_name = EXCLUDED.group_name,
                    requested_at = EXCLUDED.requested_at
            """, (chat_id, group_name, datetime.now().isoformat()))
        conn.commit()


def set_group_status(chat_id: int, status: str):
    """Guruhning ruxsat holatini yangilaydi ('approved' yoki 'rejected')."""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE approved_groups SET status = %s WHERE chat_id = %s
            """, (status, chat_id))
        conn.commit()


def start_session(chat_id: int) -> int:
    """Yangi sessiyani boshlaydi. Sessiya ID sini qaytaradi."""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE sessions SET is_active = 0, ended_at = %s
                WHERE chat_id = %s AND is_active = 1
            """, (datetime.now().isoformat(), chat_id))

            cursor.execute("""
                INSERT INTO sessions (chat_id, started_at, is_active)
                VALUES (%s, %s, 1)
                RETURNING id
            """, (chat_id, datetime.now().isoformat()))
            session_id = cursor.fetchone()[0]
        conn.commit()
    return session_id


def end_session(chat_id: int) -> dict | None:
    """Aktiv sessiyani to'xtatadi. Sessiya ma'lumotlarini qaytaradi."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("""
                SELECT * FROM sessions WHERE chat_id = %s AND is_active = 1
            """, (chat_id,))
            session = cursor.fetchone()

            if not session:
                return None

            ended_at = datetime.now().isoformat()
            cursor.execute("""
                UPDATE sessions SET is_active = 0, ended_at = %s
                WHERE id = %s
            """, (ended_at, session["id"]))
        conn.commit()
    
    result = dict(session)
    result["ended_at"] = ended_at
    return result


def get_active_session(chat_id: int) -> dict | None:
    """Guruhning aktiv sessiyasini qaytaradi."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("""
                SELECT * FROM sessions WHERE chat_id = %s AND is_active = 1
            """, (chat_id,))
            row = cursor.fetchone()
            return dict(row) if row else None


def upsert_member(chat_id: int, user_id: int, username: str | None,
                  first_name: str | None, last_name: str | None):
    """
    Guruh a'zosini bazaga qo'shadi yoki yangilaydi.
    Har qanday xabar kelganda chaqiriladi (sessiyadan tashqarida ham).
    """
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO group_members (chat_id, user_id, username, first_name, last_name, last_seen)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(chat_id, user_id) DO UPDATE SET
                    username   = excluded.username,
                    first_name = excluded.first_name,
                    last_name  = excluded.last_name,
                    last_seen  = excluded.last_seen
            """, (chat_id, user_id, username, first_name, last_name, datetime.now().isoformat()))
        conn.commit()


def record_message(session_id: int, chat_id: int, user_id: int,
                   username: str | None, first_name: str | None, last_name: str | None):
    """Sessiya davomida yuborilgan xabarni saqlaydi."""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO messages (session_id, chat_id, user_id, username, first_name, last_name, sent_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (session_id, chat_id, user_id, username, first_name, last_name, datetime.now().isoformat()))
        conn.commit()


def get_session_stats(session_id: int) -> list[dict]:
    """Sessiyada qatnashganlar va ularning xabar sonini qaytaradi."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("""
                SELECT
                    user_id,
                    username,
                    first_name,
                    last_name,
                    COUNT(*) AS message_count
                FROM messages
                WHERE session_id = %s
                GROUP BY user_id, username, first_name, last_name
                ORDER BY message_count DESC
            """, (session_id,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]


def get_session_total_messages(session_id: int) -> int:
    """Sessiyada jami xabarlar sonini qaytaradi."""
    with get_db() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM messages WHERE session_id = %s", (session_id,))
            return cursor.fetchone()[0]


def get_absent_members(chat_id: int, session_id: int) -> list[dict]:
    """
    Guruhda avval xabar yozgan, lekin bu sessiyada qatnashmagan
    foydalanuvchilar ro'yxatini qaytaradi.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("""
                SELECT gm.user_id, gm.username, gm.first_name, gm.last_name
                FROM group_members gm
                WHERE gm.chat_id = %s
                  AND gm.user_id NOT IN (
                      SELECT DISTINCT user_id FROM messages WHERE session_id = %s
                  )
                ORDER BY gm.first_name, gm.username
            """, (chat_id, session_id))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

def get_approved_groups() -> list[dict]:
    """Barcha tasdiqlangan guruhlarni qaytaradi."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT chat_id, group_name FROM approved_groups WHERE status = 'approved'")
            rows = cursor.fetchall()
            return [dict(row) for row in rows]


def get_member_stats_last_n_days(chat_id: int, days: int = 10) -> dict:
    """
    Oxirgi N kun ichidagi sessiyalar va har bir a'zoning qatnashish statistikasini qaytaradi.
    Returns: {
        'total_sessions': int,
        'members': [{'user_id', 'username', 'first_name', 'last_name', 'sessions_attended', 'total_sessions'}]
    }
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            # Oxirgi N kundagi tugallangan sessiyalarni topish
            cursor.execute("""
                SELECT id, started_at, ended_at
                FROM sessions
                WHERE chat_id = %s
                  AND is_active = 0
                  AND started_at >= (NOW() - INTERVAL '%s days')::text
                ORDER BY started_at DESC
            """, (chat_id, days))
            sessions = cursor.fetchall()
            total_sessions = len(sessions)

            if total_sessions == 0:
                return {'total_sessions': 0, 'members': []}

            session_ids = [s['id'] for s in sessions]

            # Har bir a'zo uchun nechta sessiyada qatnashganini hisoblash
            cursor.execute("""
                SELECT
                    gm.user_id,
                    gm.username,
                    gm.first_name,
                    gm.last_name,
                    COUNT(DISTINCT m.session_id) AS sessions_attended
                FROM group_members gm
                LEFT JOIN messages m
                    ON m.user_id = gm.user_id
                    AND m.chat_id = gm.chat_id
                    AND m.session_id = ANY(%s)
                WHERE gm.chat_id = %s
                GROUP BY gm.user_id, gm.username, gm.first_name, gm.last_name
                ORDER BY sessions_attended DESC, gm.first_name
            """, (session_ids, chat_id))
            members = cursor.fetchall()

            result_members = []
            for m in members:
                result_members.append({
                    'user_id': m['user_id'],
                    'username': m['username'],
                    'first_name': m['first_name'],
                    'last_name': m['last_name'],
                    'sessions_attended': m['sessions_attended'],
                    'total_sessions': total_sessions,
                })

            return {'total_sessions': total_sessions, 'members': result_members}

