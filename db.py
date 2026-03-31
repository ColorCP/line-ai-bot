# ============================================================
# db.py
# ============================================================
# 功能：
# 1. 初始化 SQLite 資料庫
# 2. 儲存 / 讀取聊天訊息
# 3. 儲存 / 讀取使用者記憶
# 4. 儲存 / 讀取摘要
# 5. 相容舊版 conversation_summaries / user_profiles / summary / id 欄位
# 6. 儲存 / 讀取 Google OAuth state
# 7. 儲存 / 讀取 Google token
# 8. 相容舊程式使用的函式名稱
# ============================================================

import sqlite3
from datetime import datetime
from typing import Optional, List, Dict

DB_PATH = "app.db"


# ============================================================
# 共用：取得資料庫連線
# ============================================================
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ============================================================
# 相容舊程式用
# ============================================================
def get_db_connection():
    return get_conn()


def get_now_iso():
    return datetime.utcnow().isoformat()


# ============================================================
# 初始化資料庫
# 開發階段直接重建，避免舊 SQLite 結構干擾
# ============================================================
def init_db():
    conn = get_conn()
    cursor = conn.cursor()

    # 開發階段：直接刪除舊表
    cursor.execute("DROP TABLE IF EXISTS messages")
    cursor.execute("DROP TABLE IF EXISTS memories")
    cursor.execute("DROP TABLE IF EXISTS summaries")
    cursor.execute("DROP TABLE IF EXISTS conversation_summaries")
    cursor.execute("DROP TABLE IF EXISTS user_profiles")
    cursor.execute("DROP TABLE IF EXISTS oauth_states")
    cursor.execute("DROP TABLE IF EXISTS google_tokens")

    # --------------------------------------------------------
    # 聊天訊息表
    # --------------------------------------------------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # --------------------------------------------------------
    # 使用者記憶表
    # --------------------------------------------------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        memory_text TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # --------------------------------------------------------
    # 新版摘要表
    # --------------------------------------------------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS summaries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL UNIQUE,
        summary TEXT,
        summary_text TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # --------------------------------------------------------
    # 舊版摘要表（相容舊程式）
    # --------------------------------------------------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS conversation_summaries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL UNIQUE,
        summary TEXT,
        summary_text TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # --------------------------------------------------------
    # 使用者 Profile 表（相容舊程式）
    # 很多舊邏輯會直接讀這張表
    # --------------------------------------------------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL UNIQUE,
        profile_text TEXT,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # --------------------------------------------------------
    # OAuth state 表
    # --------------------------------------------------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS oauth_states (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        state TEXT NOT NULL UNIQUE,
        user_id TEXT NOT NULL,
        code_verifier TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # --------------------------------------------------------
    # Google token 表
    # --------------------------------------------------------
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
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()


# ============================================================
# 聊天訊息相關
# ============================================================
def save_message(user_id: str, role: str, content: str):
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO messages (user_id, role, content)
    VALUES (?, ?, ?)
    """, (user_id, role, content))

    conn.commit()
    conn.close()


def get_recent_messages(user_id: str, limit: int = 10) -> List[Dict]:
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT role, content, created_at
    FROM messages
    WHERE user_id = ?
    ORDER BY id DESC
    LIMIT ?
    """, (user_id, limit))

    rows = cursor.fetchall()
    conn.close()

    rows = list(reversed(rows))

    result = []
    for row in rows:
        result.append({
            "role": row["role"],
            "content": row["content"],
            "created_at": row["created_at"]
        })

    return result


def clear_all_user_memory(user_id: str):
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM memories WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM summaries WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM conversation_summaries WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM user_profiles WHERE user_id = ?", (user_id,))

    conn.commit()
    conn.close()


# ============================================================
# 記憶相關
# ============================================================
def save_memory(user_id: str, memory_text: str):
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO memories (user_id, memory_text)
    VALUES (?, ?)
    """, (user_id, memory_text))

    conn.commit()
    conn.close()


def get_user_memories(user_id: str, limit: int = 50) -> List[str]:
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT memory_text
    FROM memories
    WHERE user_id = ?
    ORDER BY id DESC
    LIMIT ?
    """, (user_id, limit))

    rows = cursor.fetchall()
    conn.close()

    return [row["memory_text"] for row in reversed(rows)]


# ============================================================
# 使用者 Profile（相容舊程式）
# ============================================================
def save_user_profile(user_id: str, profile_text: str):
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO user_profiles (user_id, profile_text, updated_at)
    VALUES (?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(user_id)
    DO UPDATE SET
        profile_text = excluded.profile_text,
        updated_at = CURRENT_TIMESTAMP
    """, (user_id, profile_text))

    conn.commit()
    conn.close()


def get_user_profile(user_id: str) -> str:
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT profile_text
    FROM user_profiles
    WHERE user_id = ?
    ORDER BY id DESC
    LIMIT 1
    """, (user_id,))

    row = cursor.fetchone()
    conn.close()

    if not row:
        return ""

    return row["profile_text"] or ""


# ============================================================
# 摘要相關（新版）
# ============================================================
def save_or_update_summary(user_id: str, summary_text: str):
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO summaries (user_id, summary, summary_text, updated_at)
    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(user_id)
    DO UPDATE SET
        summary = excluded.summary,
        summary_text = excluded.summary_text,
        updated_at = CURRENT_TIMESTAMP
    """, (user_id, summary_text, summary_text))

    conn.commit()
    conn.close()


def get_summary(user_id: str) -> str:
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT summary_text, summary
    FROM summaries
    WHERE user_id = ?
    ORDER BY id DESC
    LIMIT 1
    """, (user_id,))

    row = cursor.fetchone()
    conn.close()

    if not row:
        return ""

    return row["summary_text"] or row["summary"] or ""


# ============================================================
# 摘要相關（舊版相容）
# ============================================================
def save_conversation_summary(user_id: str, summary_text: str):
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO conversation_summaries (user_id, summary, summary_text, updated_at)
    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(user_id)
    DO UPDATE SET
        summary = excluded.summary,
        summary_text = excluded.summary_text,
        updated_at = CURRENT_TIMESTAMP
    """, (user_id, summary_text, summary_text))

    conn.commit()
    conn.close()


def get_conversation_summary(user_id: str) -> str:
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT summary_text, summary
    FROM conversation_summaries
    WHERE user_id = ?
    ORDER BY id DESC
    LIMIT 1
    """, (user_id,))

    row = cursor.fetchone()
    conn.close()

    if not row:
        return ""

    return row["summary_text"] or row["summary"] or ""


# ============================================================
# 建立給 memory_service 用的整合函式
# ============================================================
def build_memory_context(user_id: str) -> Dict:
    profile_text = get_user_profile(user_id)
    profile_memories = get_user_memories(user_id, limit=50)

    # 如果 user_profiles 沒資料，就退回 memories 組合
    if not profile_text:
        profile_text = "\n".join(profile_memories)

    summary_text = get_summary(user_id)
    if not summary_text:
        summary_text = get_conversation_summary(user_id)

    recent_messages = get_recent_messages(user_id, limit=10)

    return {
        "profile_text": profile_text,
        "summary_text": summary_text,
        "recent_messages": recent_messages
    }


# ============================================================
# OAuth state 相關
# ============================================================
def save_oauth_state(state: str, user_id: str, code_verifier: str):
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT OR REPLACE INTO oauth_states (state, user_id, code_verifier)
    VALUES (?, ?, ?)
    """, (state, user_id, code_verifier))

    conn.commit()
    conn.close()


def get_oauth_state_data(state: str) -> Optional[Dict]:
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT user_id, code_verifier
    FROM oauth_states
    WHERE state = ?
    """, (state,))

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "user_id": row["user_id"],
        "code_verifier": row["code_verifier"]
    }


def delete_oauth_state(state: str):
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
    DELETE FROM oauth_states
    WHERE state = ?
    """, (state,))

    conn.commit()
    conn.close()


# ============================================================
# Google Token 相關
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
    conn = get_conn()
    cursor = conn.cursor()

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
        updated_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(user_id)
    DO UPDATE SET
        access_token = excluded.access_token,
        refresh_token = excluded.refresh_token,
        token_uri = excluded.token_uri,
        client_id = excluded.client_id,
        client_secret = excluded.client_secret,
        scopes = excluded.scopes,
        expiry = excluded.expiry,
        updated_at = CURRENT_TIMESTAMP
    """, (
        user_id,
        access_token,
        refresh_token,
        token_uri,
        client_id,
        client_secret,
        scopes,
        expiry
    ))

    conn.commit()
    conn.close()


def get_google_token(user_id: str) -> Optional[Dict]:
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT
        user_id,
        access_token,
        refresh_token,
        token_uri,
        client_id,
        client_secret,
        scopes,
        expiry,
        updated_at
    FROM google_tokens
    WHERE user_id = ?
    ORDER BY id DESC
    LIMIT 1
    """, (user_id,))

    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "user_id": row["user_id"],
        "access_token": row["access_token"],
        "refresh_token": row["refresh_token"],
        "token_uri": row["token_uri"],
        "client_id": row["client_id"],
        "client_secret": row["client_secret"],
        "scopes": row["scopes"],
        "expiry": row["expiry"],
        "updated_at": row["updated_at"]
    }


def get_google_token_by_user_id(user_id: str) -> Optional[Dict]:
    return get_google_token(user_id)


def delete_google_token(user_id: str):
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
    DELETE FROM google_tokens
    WHERE user_id = ?
    """, (user_id,))

    conn.commit()
    conn.close()
