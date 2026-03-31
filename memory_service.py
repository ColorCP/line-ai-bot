# ============================================================
# memory_service.py
# ============================================================
# 這支檔案負責：
# 1. 短期記憶（messages）
# 2. 長期記憶（user_profiles）
# 3. 摘要記憶（conversation_summaries）
# 4. 清除使用者記憶
#
# 注意：
# 所有記憶都會依照 LINE 的 user_id 分開儲存，
# 所以未來多人使用時，不會互相混到記憶。
# ============================================================

from db import get_db_connection, get_now_iso


# ============================================================
# 短期記憶：messages
# ============================================================
def save_message(user_id: str, role: str, content: str):
    """
    儲存一筆對話紀錄
    role 只能是 user 或 assistant
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO messages (user_id, role, content, created_at)
        VALUES (?, ?, ?, ?)
    """, (
        user_id,
        role,
        content,
        get_now_iso()
    ))

    conn.commit()
    conn.close()


def get_recent_messages(user_id: str, limit: int = 12):
    """
    取得某位使用者最近幾筆對話
    這是短期記憶，主要讓 AI 接得上目前上下文
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT role, content
        FROM messages
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
    """, (user_id, limit))

    rows = cursor.fetchall()
    conn.close()

    # 由於剛剛是 DESC 查詢，這裡要反轉回正常時間順序
    rows.reverse()

    messages = []

    for role, content in rows:
        messages.append({
            "role": role,
            "content": content
        })

    return messages


def clear_user_messages(user_id: str):
    """
    清除某位使用者所有短期對話記憶
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM messages
        WHERE user_id = ?
    """, (user_id,))

    conn.commit()
    conn.close()


# ============================================================
# 長期記憶：user_profiles
# ============================================================
def upsert_profile_memory(user_id: str, memory_type: str, memory_value: str):
    """
    新增或更新某位使用者的長期記憶
    同一個 memory_type 若已存在，則更新成最新值
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id
        FROM user_profiles
        WHERE user_id = ? AND memory_type = ?
        ORDER BY id DESC
        LIMIT 1
    """, (user_id, memory_type))

    row = cursor.fetchone()

    if row:
        cursor.execute("""
            UPDATE user_profiles
            SET memory_value = ?, updated_at = ?
            WHERE id = ?
        """, (
            memory_value,
            get_now_iso(),
            row[0]
        ))
    else:
        cursor.execute("""
            INSERT INTO user_profiles (user_id, memory_type, memory_value, updated_at)
            VALUES (?, ?, ?, ?)
        """, (
            user_id,
            memory_type,
            memory_value,
            get_now_iso()
        ))

    conn.commit()
    conn.close()


def get_profile_memories(user_id: str):
    """
    取得某位使用者所有長期記憶
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT memory_type, memory_value
        FROM user_profiles
        WHERE user_id = ?
        ORDER BY id ASC
    """, (user_id,))

    rows = cursor.fetchall()
    conn.close()

    memories = []

    for memory_type, memory_value in rows:
        memories.append({
            "type": memory_type,
            "value": memory_value
        })

    return memories


def clear_user_profiles(user_id: str):
    """
    清除某位使用者所有長期記憶
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM user_profiles
        WHERE user_id = ?
    """, (user_id,))

    conn.commit()
    conn.close()


# ============================================================
# 摘要記憶：conversation_summaries
# ============================================================
def save_summary(user_id: str, summary: str):
    """
    儲存一筆摘要記憶
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO conversation_summaries (user_id, summary, created_at)
        VALUES (?, ?, ?)
    """, (
        user_id,
        summary,
        get_now_iso()
    ))

    conn.commit()
    conn.close()


def get_latest_summary(user_id: str):
    """
    取得某位使用者最新一筆摘要
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT summary
        FROM conversation_summaries
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT 1
    """, (user_id,))

    row = cursor.fetchone()
    conn.close()

    if row:
        return row[0]

    return ""


def clear_user_summaries(user_id: str):
    """
    清除某位使用者所有摘要記憶
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM conversation_summaries
        WHERE user_id = ?
    """, (user_id,))

    conn.commit()
    conn.close()


# ============================================================
# 組合記憶內容
# ============================================================
def build_memory_context(user_id: str):
    """
    組合：
    1. 長期記憶
    2. 最新摘要
    3. 最近對話
    給 AI 回覆時使用
    """
    latest_summary = get_latest_summary(user_id)
    profile_memories = get_profile_memories(user_id)
    recent_messages = get_recent_messages(user_id, limit=12)

    profile_lines = []

    for item in profile_memories:
        profile_lines.append(f"{item['type']}: {item['value']}")

    profile_text = "\n".join(profile_lines) if profile_lines else "無"
    summary_text = latest_summary if latest_summary else "無"

    return {
        "profile_text": profile_text,
        "summary_text": summary_text,
        "recent_messages": recent_messages
    }


def clear_all_user_memory(user_id: str):
    """
    一次清除某位使用者全部記憶
    """
    clear_user_messages(user_id)
    clear_user_profiles(user_id)
    clear_user_summaries(user_id)
