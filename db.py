# ============================================================
# db.py
# ============================================================
# 這支檔案負責：
# 1. 建立 SQLite 資料庫連線
# 2. 初始化所有需要的資料表
# 3. 提供基本資料庫操作函式
#
# 目前先建立 4 張表：
# - messages：短期對話記憶
# - user_profiles：長期記憶
# - conversation_summaries：摘要記憶
# - google_tokens：每位 LINE 使用者綁定自己的 Google OAuth token
# ============================================================

import sqlite3
from datetime import datetime


# SQLite 資料庫檔名
DB_PATH = "chat_memory.db"


def get_db_connection():
    """
    建立並回傳 SQLite 連線
    """
    conn = sqlite3.connect(DB_PATH)
    return conn


def init_db():
    """
    初始化資料庫與所有資料表
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # ========================================================
    # messages：短期對話記憶
    # ========================================================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # ========================================================
    # user_profiles：長期記憶
    # memory_type 例如：
    # - name
    # - job
    # - family
    # - preference
    # - language
    # - goal
    # ========================================================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            memory_type TEXT NOT NULL,
            memory_value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # ========================================================
    # conversation_summaries：對話摘要記憶
    # ========================================================
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversation_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            summary TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # ========================================================
    # google_tokens：每個 LINE user 綁自己的 Google token
    # 這是未來產品化的重要基礎
    # ========================================================
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

    conn.commit()
    conn.close()


def get_now_iso():
    """
    回傳現在時間的 ISO 字串格式
    """
    return datetime.now().isoformat()
