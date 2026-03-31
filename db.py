# ============================================================
# db.py
# ============================================================
# 功能：
# 1. 初始化 SQLite 資料庫
# 2. 提供 memory_service.py 使用的 messages / user_profiles / conversation_summaries
# 3. 提供 google_oauth_service.py 使用的 oauth_states
# 4. 提供 calendar_service.py 使用的 google_tokens
# 5. 保留舊函式名稱相容
#
# 注意：
# 目前是修復 / 測試階段
# init_db() 會直接 DROP TABLE 再重建
# 所以每次啟動都會清空資料
# ============================================================

import sqlite3
from datetime import datetime
from typing import Optional, Dict

DB_PATH = "app.db"


# ============================================================
# 共用：取得 SQLite 連線
# ============================================================
def get_conn():
    """
    建立 SQLite 連線
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ============================================================
# 相容舊程式用
# ============================================================
def get_db_connection():
    """
    舊程式相容用
    memory_service.py 會 import 這個名稱
    """
    return get_conn()


def get_now_iso():
    """
    回傳目前 UTC 時間（ISO 格式）
    """
    return datetime.utcnow().isoformat()


# ============================================================
# 初始化資料庫
# ============================================================
def init_db():
    """
    初始化所有需要的資料表

    目前為了避免舊表結構殘留，
    啟動時會直接刪除舊表再重建。
    """
    conn = get_conn()
    cursor = conn.cursor()

    # --------------------------------------------------------
    # 開發 / 修復階段：直接重建表
    # --------------------------------------------------------
    cursor.execute("DROP TABLE IF EXISTS messages")
    cursor.execute("DROP TABLE IF EXISTS user_profiles")
    cursor.execute("DROP TABLE IF EXISTS conversation_summaries")
    cursor.execute("DROP TABLE IF EXISTS oauth_states")
    cursor.execute("DROP TABLE IF EXISTS google_tokens")

    # 如果以前你有其他版本的表，也一起清掉，避免干擾
    cursor.execute("DROP TABLE IF EXISTS memories")
    cursor.execute("DROP TABLE IF EXISTS summaries")

    # --------------------------------------------------------
    # 短期記憶：messages
    # 給 memory_service.py 使用
    # --------------------------------------------------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    # --------------------------------------------------------
    # 長期記憶：user_profiles
    # 給 memory_service.py 使用
    # 欄位要完全符合你目前的 memory_service.py：
    # id / user_id / memory_type / memory_value / updated_at
    # --------------------------------------------------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        memory_type TEXT NOT NULL,
        memory_value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """)

    # --------------------------------------------------------
    # 摘要記憶：conversation_summaries
    # 給 memory_service.py 使用
    # 欄位要完全符合你目前的 memory_service.py：
    # id / user_id / summary / created_at
    # --------------------------------------------------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS conversation_summaries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        summary TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    # --------------------------------------------------------
    # OAuth state
    # 給 google_oauth_service.py 使用
    # --------------------------------------------------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS oauth_states (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        state TEXT NOT NULL UNIQUE,
        user_id TEXT NOT NULL,
        code_verifier TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    # --------------------------------------------------------
    # Google Token
    # 給 calendar_service.py / google_oauth_service.py 使用
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
        updated_at TEXT NOT NULL
    )
    """)

    conn.commit()
    conn.close()


# ============================================================
# Google OAuth state 相關
# 給 google_oauth_service.py 用
# ============================================================
def save_oauth_state(state: str, user_id: str, code_verifier: str):
    """
    儲存 OAuth state 與 PKCE code_verifier
    """
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT OR REPLACE INTO oauth_states (
        state, user_id, code_verifier, created_at
    )
    VALUES (?, ?, ?, ?)
    """, (
        state,
        user_id,
        code_verifier,
        get_now_iso()
    ))

    conn.commit()
    conn.close()


def get_oauth_state_data(state: str) -> Optional[Dict]:
    """
    根據 state 查詢 user_id 與 code_verifier
    """
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT user_id, code_verifier
    FROM oauth_states
    WHERE state = ?
    ORDER BY id DESC
    LIMIT 1
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
    """
    刪除已使用過的 OAuth state
    """
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
# 給 calendar_service.py / google_oauth_service.py 用
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
    """
    儲存或更新 Google OAuth token
    """
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
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(user_id)
    DO UPDATE SET
        access_token = excluded.access_token,
        refresh_token = excluded.refresh_token,
        token_uri = excluded.token_uri,
        client_id = excluded.client_id,
        client_secret = excluded.client_secret,
        scopes = excluded.scopes,
        expiry = excluded.expiry,
        updated_at = excluded.updated_at
    """, (
        user_id,
        access_token,
        refresh_token,
        token_uri,
        client_id,
        client_secret,
        scopes,
        expiry,
        get_now_iso()
    ))

    conn.commit()
    conn.close()


def get_google_token_by_user_id(user_id: str) -> Optional[Dict]:
    """
    給 calendar_service.py 使用
    """
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


def get_google_token(user_id: str) -> Optional[Dict]:
    """
    相容另一種命名
    """
    return get_google_token_by_user_id(user_id)


def delete_google_token(user_id: str):
    """
    刪除指定使用者的 Google token
    """
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
    DELETE FROM google_tokens
    WHERE user_id = ?
    """, (user_id,))

    conn.commit()
    conn.close()
