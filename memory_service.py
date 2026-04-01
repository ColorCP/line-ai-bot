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
#
# 這一版修正重點：
# 1. 相容 openai_service.py 的記憶抽取格式（list[str]）
# 2. 修正 string indices must be integers, not 'str'
# 3. 加入必要的防呆處理
# ============================================================

from db import get_db_connection, get_now_iso
from openai_service import extract_profile_memories_from_text, summarize_messages_for_memory


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

    # 因為是 DESC 查出來，所以這裡反轉成正常時間順序
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
        memory_type = str(item.get("type", "")).strip()
        memory_value = str(item.get("value", "")).strip()

        if not memory_value:
            continue

        if memory_type:
            profile_lines.append(f"{memory_type}: {memory_value}")
        else:
            profile_lines.append(memory_value)

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


# ============================================================
# 自動抽取並寫入長期記憶
# ============================================================
def auto_extract_and_save_profile_memories(user_id: str, user_msg: str):
    """
    自動從使用者輸入中抽取長期記憶並寫入資料庫

    目前相容的 memories 格式：
    1. list[str]
       例如：
       [
           "使用者名字是卡樂",
           "使用者喜歡 Lexus IS"
       ]

    2. list[dict]
       例如：
       [
           {"type": "name", "value": "卡樂"},
           {"type": "preference", "value": "喜歡 Lexus IS"}
       ]

    若遇到字串，就先統一存成 memory_type = "fact"
    """
    memories = extract_profile_memories_from_text(user_msg)

    if not memories:
        return

    for item in memories:
        # ----------------------------------------------------
        # 情況 1：item 是 dict
        # ----------------------------------------------------
        if isinstance(item, dict):
            memory_type = str(item.get("type", "")).strip() or "fact"
            memory_value = str(item.get("value", "")).strip()

            if memory_value:
                upsert_profile_memory(user_id, memory_type, memory_value)

            continue

        # ----------------------------------------------------
        # 情況 2：item 是字串
        # ----------------------------------------------------
        memory_value = str(item).strip()

        if not memory_value:
            continue

        # 目前字串型記憶統一先當作 fact 存
        upsert_profile_memory(user_id, "fact", memory_value)


# ============================================================
# 對話太多時，自動摘要
# ============================================================
def summarize_if_needed(user_id: str, threshold: int = 20, chunk_size: int = 12):
    """
    如果某位使用者的短期對話累積太多，
    就把較舊對話濃縮成摘要後存起來，並刪除舊訊息。
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*)
        FROM messages
        WHERE user_id = ?
    """, (user_id,))

    total_count = cursor.fetchone()[0]

    if total_count < threshold:
        conn.close()
        return

    cursor.execute("""
        SELECT id, role, content
        FROM messages
        WHERE user_id = ?
        ORDER BY id ASC
        LIMIT ?
    """, (user_id, chunk_size))

    rows = cursor.fetchall()

    if not rows:
        conn.close()
        return

    old_messages = []
    message_ids = []

    for row in rows:
        message_id, role, content = row
        message_ids.append(message_id)
        old_messages.append({
            "role": role,
            "content": content
        })

    conn.close()

    summary_text = summarize_messages_for_memory(old_messages)

    # 如果摘要失敗或空字串，就不要存
    if summary_text and str(summary_text).strip():
        save_summary(user_id, summary_text)

    # 刪除已經被拿去摘要的舊訊息
    conn = get_db_connection()
    cursor = conn.cursor()

    placeholders = ",".join(["?"] * len(message_ids))
    sql = f"DELETE FROM messages WHERE id IN ({placeholders})"
    cursor.execute(sql, message_ids)

    conn.commit()
    conn.close()
