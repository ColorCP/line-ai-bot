# ============================================================
# db.py
# ============================================================

import sqlite3
from datetime import datetime


DB_PATH = "chat_memory.db"


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    return conn


def get_now_iso():
    return datetime.now().isoformat()


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            memory_type TEXT NOT NULL,
            memory_value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversation_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            summary TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS google_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL UNIQUE,
            access_token TEXT,
            refresh_token TEXT,
            token_uri TEXT,
            client_id TEXT,
            client_secret TEXT,
            scopes TEXT,
            expiry TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # OAuth state 暫存表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS google_oauth_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            state TEXT NOT NULL UNIQUE,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# Google token 資料操作
# ============================================================
def save_google_token(
    user_id: str,
    access_token: str,
    refresh_token: str,
    token_uri: str,
    client_id: str,
    client_secret: str,
    scopes: str,
    expiry: str
):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id
        FROM google_tokens
        WHERE user_id = ?
        LIMIT 1
    """, (user_id,))

    row = cursor.fetchone()

    if row:
        cursor.execute("""
            UPDATE google_tokens
            SET access_token = ?,
                refresh_token = ?,
                token_uri = ?,
                client_id = ?,
                client_secret = ?,
                scopes = ?,
                expiry = ?,
                updated_at = ?
            WHERE user_id = ?
        """, (
            access_token,
            refresh_token,
            token_uri,
            client_id,
            client_secret,
            scopes,
            expiry,
            get_now_iso(),
            user_id
        ))
    else:
        cursor.execute("""
            INSERT INTO google_tokens (
                user_id,
                access_token,
                refresh_token,
                token_uri,
                client_id,
                client_secret,
                scopes,
                expiry,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            access_token,
            refresh_token,
            token_uri,
            client_id,
            client_secret,
            scopes,
            expiry,
            get_now_iso(),
            get_now_iso()
        ))

    conn.commit()
    conn.close()


def get_google_token_by_user_id(user_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT access_token, refresh_token, token_uri, client_id, client_secret, scopes, expiry
        FROM google_tokens
        WHERE user_id = ?
        LIMIT 1
    """, (user_id,))

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "access_token": row[0],
        "refresh_token": row[1],
        "token_uri": row[2],
        "client_id": row[3],
        "client_secret": row[4],
        "scopes": row[5],
        "expiry": row[6]
    }


def delete_google_token(user_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM google_tokens
        WHERE user_id = ?
    """, (user_id,))

    conn.commit()
    conn.close()


# ============================================================
# OAuth state 暫存
# ============================================================
def save_oauth_state(state: str, user_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO google_oauth_states (state, user_id, created_at)
        VALUES (?, ?, ?)
    """, (state, user_id, get_now_iso()))

    conn.commit()
    conn.close()


def get_user_id_by_oauth_state(state: str):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT user_id
        FROM google_oauth_states
        WHERE state = ?
        LIMIT 1
    """, (state,))

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return row[0]


def delete_oauth_state(state: str):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM google_oauth_states
        WHERE state = ?
    """, (state,))

    conn.commit()
    conn.close()
