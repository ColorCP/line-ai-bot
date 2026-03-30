# ============================================================
# LINE Bot + OpenAI + SQLite 多層記憶 AI 助理
# ============================================================
#
# 【程式用途】
# 這支程式是一個使用 FastAPI 建立的 LINE Bot 後端服務，
# 主要功能是接收 LINE 使用者傳來的訊息，交給 OpenAI 模型處理，
# 再把 AI 回覆傳回 LINE，形成一個可對話的 AI 助理。
#
# 這個版本不只是一般聊天機器人，
# 還加入了「短期記憶 + 長期記憶 + 摘要記憶」三層記憶機制，
# 讓 AI 可以更像真正助理，記住使用者的重要資訊與對話脈絡。
#
# ------------------------------------------------------------
# 【核心功能】
# 1. 接收 LINE 使用者文字訊息
#    - 透過 /webhook 接收 LINE Messaging API 傳來的事件
#    - 只處理文字訊息，忽略圖片、貼圖、影片等其他型態
#
# 2. 呼叫 OpenAI 產生回答
#    - 把系統提示詞、使用者近期對話、長期記憶、摘要記憶一起送給 OpenAI
#    - 由 AI 根據上下文產生更連貫的回覆
#
# 3. 短期記憶（recent messages）
#    - 把最近幾筆原始對話存在 messages 資料表
#    - 每次回答前讀取最近的對話內容，讓 AI 記得前面剛聊過什麼
#
# 4. 長期記憶（user profile memory）
#    - 會用 AI 自動分析使用者輸入
#    - 如果偵測到值得長期記住的資訊，例如：
#      姓名、職業、家人、語言偏好、目標、長期喜好
#    - 就會寫入 user_profiles 資料表
#    - 後續回答時可優先參考這些資訊
#
# 5. 摘要記憶（conversation summary）
#    - 如果原始對話累積太多，程式會把較舊的內容整理成摘要
#    - 摘要會存入 conversation_summaries 資料表
#    - 這樣可以減少每次送給 OpenAI 的資料量，節省 token 與成本
#    - 同時保留較早期的重要背景資訊
#
# 6. 多使用者記憶隔離
#    - 每位 LINE 使用者都會有自己的 user_id
#    - 所有資料表都用 user_id 做區分
#    - 所以每個人只會讀到自己的短期記憶、長期記憶、摘要記憶
#    - 不會把 A 的資訊混到 B 身上
#
# 7. 記憶管理指令
#    - /clear  ：清除該使用者的全部記憶
#    - /memory ：查看該使用者目前已儲存的長期記憶
#
# ------------------------------------------------------------
# 【資料表說明】
# 1. messages
#    - 存放原始對話紀錄
#    - 欄位包含：
#      user_id / role / content / created_at
#    - role 可能是 user 或 assistant
#
# 2. user_profiles
#    - 存放長期記憶
#    - 例如：
#      name: 卡樂
#      job: 軟體工程師
#      family: 女兒叫面面
#      language: 繁體中文
#
# 3. conversation_summaries
#    - 存放較舊對話整理後的摘要
#    - 讓系統即使刪除部分舊對話，仍可保留重要脈絡
#
# ------------------------------------------------------------
# 【執行流程】
# 1. LINE 使用者傳送文字訊息到 Bot
# 2. LINE Platform 把訊息送到本程式的 /webhook
# 3. 程式讀取 user_id、訊息內容、reply_token
# 4. 程式先嘗試從這句話中抽取可長期保存的記憶
# 5. 程式檢查是否需要把舊對話做摘要
# 6. 程式組合：
#    - 長期記憶
#    - 摘要記憶
#    - 最近幾筆短期對話
#    - 使用者目前這句新訊息
# 7. 程式呼叫 OpenAI 取得回答
# 8. 把本次 user / assistant 對話寫入資料庫
# 9. 把 AI 回覆透過 LINE Reply API 傳回給使用者
#
# ------------------------------------------------------------
# 【使用技術】
# - FastAPI：建立 Web API / Webhook
# - LINE Messaging API：接收與回覆 LINE 訊息
# - OpenAI Chat Completions API：產生 AI 回答與記憶抽取/摘要
# - SQLite：本地資料庫，儲存聊天記錄與記憶
# - requests：發送 HTTP API 請求
#
# ------------------------------------------------------------
# 【注意事項】
# 1. 這個版本的記憶儲存在 SQLite 檔案 chat_memory.db
#    如果部署平台是暫存型檔案系統，重新部署後資料可能消失
#
# 2. 若未來要正式多人使用，建議改成 PostgreSQL / MySQL / Supabase
#
# 3. LINE_CHANNEL_ACCESS_TOKEN 與 OPENAI_API_KEY
#    必須先正確設定在環境變數中，否則無法正常執行
#
# 4. 這個程式目前只處理文字訊息
#    若未來要支援圖片、語音、行事曆、Gmail、任務提醒等功能，
#    可以再往下擴充
#
# ============================================================

# ============================================================
# 【檔案結構導覽（快速閱讀指南）】
# ============================================================
#
# 這支程式依功能分成幾個區塊，閱讀或維護時可以照這個順序看：
#
# ------------------------------------------------------------
# 1️⃣ 基本設定區（最上面）
# ------------------------------------------------------------
# - 匯入套件（FastAPI / requests / sqlite3 / os / datetime）
# - 建立 FastAPI app
# - 讀取環境變數（LINE token、OpenAI API key）
# - 設定資料庫路徑 DB_PATH
#
# 👉 這一區主要是「初始化環境」
#
#
# ------------------------------------------------------------
# 2️⃣ 資料庫初始化（init_db）
# ------------------------------------------------------------
# - 建立三張表：
#   ① messages（短期對話記憶）
#   ② user_profiles（長期記憶）
#   ③ conversation_summaries（摘要記憶）
#
# 👉 這一區負責「AI 的記憶結構建立」
#
#
# ------------------------------------------------------------
# 3️⃣ 基本資料庫操作（messages）
# ------------------------------------------------------------
# - save_message()         → 存一筆對話
# - get_recent_messages()  → 取最近對話（短期記憶）
# - clear_user_messages()  → 清除對話
#
# 👉 對應「短期記憶（聊天上下文）」
#
#
# ------------------------------------------------------------
# 4️⃣ 長期記憶模組（user_profiles）
# ------------------------------------------------------------
# - upsert_profile_memory() → 新增或更新記憶
# - get_profile_memories()  → 取得所有長期記憶
# - clear_user_profiles()   → 清除長期記憶
#
# 👉 對應「人格 / 使用者資訊」
#    例如：名字、職業、家人、喜好
#
#
# ------------------------------------------------------------
# 5️⃣ 摘要記憶模組（conversation_summaries）
# ------------------------------------------------------------
# - save_summary()           → 存摘要
# - get_latest_summary()     → 取最新摘要
# - clear_user_summaries()   → 清除摘要
#
# 👉 用來壓縮舊對話，避免 token 過多
#
#
# ------------------------------------------------------------
# 6️⃣ LINE API 模組
# ------------------------------------------------------------
# - reply() → 把訊息回傳給 LINE 使用者
#
# 👉 負責「輸出給使用者」
#
#
# ------------------------------------------------------------
# 7️⃣ OpenAI API 模組
# ------------------------------------------------------------
# - call_openai() → 統一呼叫 OpenAI
#
# 👉 所有 AI 功能（聊天 / 摘要 / 記憶抽取）都走這裡
#
#
# ------------------------------------------------------------
# 8️⃣ 記憶處理邏輯（核心）
# ------------------------------------------------------------
# - extract_and_store_profile_memory()
#   → 從使用者輸入中抽取長期記憶
#
# - generate_and_save_summary_if_needed()
#   → 對話過多時，自動做摘要
#
# - build_memory_context()
#   → 組合：
#      長期記憶 + 摘要 + 短期對話
#
# 👉 這區是「AI 變聰明的關鍵」
#
#
# ------------------------------------------------------------
# 9️⃣ AI 主流程
# ------------------------------------------------------------
# - call_ai()
#
# 流程：
#   使用者輸入 →
#   抽取長期記憶 →
#   檢查是否需要摘要 →
#   組合所有記憶 →
#   呼叫 OpenAI →
#   回傳結果 →
#   存回資料庫
#
# 👉 這是整個系統最重要的核心
#
#
# ------------------------------------------------------------
# 🔟 Webhook（系統入口）
# ------------------------------------------------------------
# - /webhook
#
# 流程：
#   LINE → webhook →
#   解析 user_id →
#   判斷指令（/clear /memory） →
#   呼叫 AI →
#   回覆 LINE
#
# 👉 這是整個系統「進來的入口」
#
#
# ------------------------------------------------------------
# 11️⃣ 測試 API
# ------------------------------------------------------------
# - /
#
# 👉 用來確認 server 是否正常運作
#
#
# ============================================================
# 【開發者快速理解一句話版本】
# ============================================================
#
# LINE 傳訊息進來 →
# 用 user_id 找記憶 →
# 組合（短期 + 長期 + 摘要） →
# 丟給 OpenAI →
# 回答 →
# 存回記憶 →
# 回 LINE
#
# ============================================================

# 匯入 FastAPI 框架，用來建立 API server
from fastapi import FastAPI, Request

# 用來回傳 JSON 格式資料
from fastapi.responses import JSONResponse

# 用來呼叫 LINE API 與 OpenAI API
import requests

# 讀取系統環境變數
import os

# SQLite 資料庫
import sqlite3

# 取得目前時間
from datetime import datetime


# 建立 FastAPI 應用
app = FastAPI()


# 從環境變數讀取 LINE Bot token
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

# 從環境變數讀取 OpenAI API key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


# SQLite 資料庫檔名
DB_PATH = "chat_memory.db"


# =========================
# 資料庫初始化
# =========================
def init_db():
    # 連接資料庫，如果檔案不存在會自動建立
    conn = sqlite3.connect(DB_PATH)

    # 建立操作 SQL 的 cursor
    cursor = conn.cursor()

    # 建立對話紀錄表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # 建立長期記憶表
    # 每筆記憶都有 type，例如 name / job / preference / family
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            memory_type TEXT NOT NULL,
            memory_value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    # 建立摘要記憶表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversation_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            summary TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # 儲存變更
    conn.commit()

    # 關閉資料庫
    conn.close()


# 啟動時初始化資料庫
init_db()


# =========================
# 基本資料庫工具
# =========================
def get_db_connection():
    # 建立新的 SQLite 連線
    return sqlite3.connect(DB_PATH)


# 儲存一筆原始對話
def save_message(user_id: str, role: str, content: str):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO messages (user_id, role, content, created_at)
        VALUES (?, ?, ?, ?)
    """, (
        user_id,
        role,
        content,
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()


# 取得最近幾筆對話
def get_recent_messages(user_id: str, limit: int = 12):
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

    # 反轉成正確時間順序
    rows.reverse()

    messages = []

    for role, content in rows:
        messages.append({
            "role": role,
            "content": content
        })

    return messages


# 清除某個使用者的所有原始對話
def clear_user_messages(user_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))

    conn.commit()
    conn.close()


# =========================
# 長期記憶工具
# =========================
def upsert_profile_memory(user_id: str, memory_type: str, memory_value: str):
    """
    如果同類型記憶已存在，就更新
    如果不存在，就新增
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # 先檢查是否已存在同一類型記憶
    cursor.execute("""
        SELECT id
        FROM user_profiles
        WHERE user_id = ? AND memory_type = ?
        ORDER BY id DESC
        LIMIT 1
    """, (user_id, memory_type))

    row = cursor.fetchone()

    if row:
        # 如果已存在，更新內容
        cursor.execute("""
            UPDATE user_profiles
            SET memory_value = ?, updated_at = ?
            WHERE id = ?
        """, (
            memory_value,
            datetime.now().isoformat(),
            row[0]
        ))
    else:
        # 如果不存在，新增一筆
        cursor.execute("""
            INSERT INTO user_profiles (user_id, memory_type, memory_value, updated_at)
            VALUES (?, ?, ?, ?)
        """, (
            user_id,
            memory_type,
            memory_value,
            datetime.now().isoformat()
        ))

    conn.commit()
    conn.close()


# 取得某個使用者所有長期記憶
def get_profile_memories(user_id: str):
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


# 清除某個使用者所有長期記憶
def clear_user_profiles(user_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM user_profiles WHERE user_id = ?", (user_id,))

    conn.commit()
    conn.close()


# =========================
# 摘要記憶工具
# =========================
def save_summary(user_id: str, summary: str):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO conversation_summaries (user_id, summary, created_at)
        VALUES (?, ?, ?)
    """, (
        user_id,
        summary,
        datetime.now().isoformat()
    ))

    conn.commit()
    conn.close()


# 取得最新一筆摘要
def get_latest_summary(user_id: str):
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


# 清除某個使用者所有摘要
def clear_user_summaries(user_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM conversation_summaries WHERE user_id = ?", (user_id,))

    conn.commit()
    conn.close()


# =========================
# LINE 回覆函式
# =========================
def reply(reply_token: str, text: str):
    # LINE 回覆訊息 API
    url = "https://api.line.me/v2/bot/message/reply"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }

    payload = {
        "replyToken": reply_token,
        "messages": [
            {
                "type": "text",
                "text": text[:5000]
            }
        ]
    }

    response = requests.post(url, headers=headers, json=payload)

    # 印出回覆結果，方便 debug
    print("LINE reply status:", response.status_code, response.text)


# =========================
# OpenAI 呼叫工具
# =========================
def call_openai(messages: list, temperature: float = 0.3) -> str:
    # OpenAI chat completions API
    url = "https://api.openai.com/v1/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}"
    }

    payload = {
        "model": "gpt-4o-mini",
        "messages": messages,
        "temperature": temperature
    }

    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()

    result = response.json()

    return result["choices"][0]["message"]["content"]


# =========================
# 長期記憶萃取
# =========================
def extract_and_store_profile_memory(user_id: str, user_msg: str):
    """
    用 AI 從使用者這句話中判斷有沒有值得長期記住的資訊
    然後用簡單規格化格式回傳，再寫入資料庫
    """
    extract_prompt = [
        {
            "role": "system",
            "content": (
                "你是一個記憶抽取器。"
                "請從使用者輸入中判斷是否有值得長期記住的個人資訊。"
                "例如：姓名、職業、家人名稱、語言偏好、長期喜好。"
                "如果沒有，回覆 NONE。"
                "如果有，請只用以下格式回覆，每行一筆：\n"
                "type:value\n"
                "type 只能是 name、job、family、preference、language、goal。\n"
                "不要輸出其他說明。"
            )
        },
        {
            "role": "user",
            "content": user_msg
        }
    ]

    try:
        result = call_openai(extract_prompt, temperature=0.0)
    except Exception as e:
        print("extract_and_store_profile_memory error:", str(e))
        return

    # 如果沒有可記憶內容
    if result.strip().upper() == "NONE":
        return

    # 一行一行解析
    lines = result.splitlines()

    for line in lines:
        line = line.strip()

        if not line:
            continue

        if ":" not in line:
            continue

        memory_type, memory_value = line.split(":", 1)

        memory_type = memory_type.strip()
        memory_value = memory_value.strip()

        if not memory_type or not memory_value:
            continue

        # 寫入長期記憶
        upsert_profile_memory(user_id, memory_type, memory_value)


# =========================
# 對話摘要產生
# =========================
def generate_and_save_summary_if_needed(user_id: str):
    """
    如果某個使用者對話太多，就把較舊對話做摘要
    這裡先用簡單規則：
    如果原始對話超過 20 筆，就做一次摘要
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # 計算此使用者共有幾筆原始對話
    cursor.execute("""
        SELECT COUNT(*)
        FROM messages
        WHERE user_id = ?
    """, (user_id,))

    total_count = cursor.fetchone()[0]

    # 如果還不多，就先不摘要
    if total_count < 20:
        conn.close()
        return

    # 抓較舊的 12 筆來摘要
    cursor.execute("""
        SELECT role, content
        FROM messages
        WHERE user_id = ?
        ORDER BY id ASC
        LIMIT 12
    """, (user_id,))

    old_rows = cursor.fetchall()

    if not old_rows:
        conn.close()
        return

    # 把舊對話組成文字
    old_text_parts = []

    for role, content in old_rows:
        old_text_parts.append(f"{role}: {content}")

    old_text = "\n".join(old_text_parts)

    conn.close()

    summary_prompt = [
        {
            "role": "system",
            "content": (
                "請把以下舊對話整理成精簡摘要，"
                "保留重要背景、需求、偏好、已確認資訊。"
                "請使用繁體中文，內容精簡但完整。"
            )
        },
        {
            "role": "user",
            "content": old_text
        }
    ]

    try:
        summary = call_openai(summary_prompt, temperature=0.2)
    except Exception as e:
        print("generate_and_save_summary_if_needed error:", str(e))
        return

    # 存摘要
    save_summary(user_id, summary)

    # 存完摘要後，把剛剛拿去摘要的舊資料刪掉，避免越積越多
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM messages
        WHERE id IN (
            SELECT id
            FROM messages
            WHERE user_id = ?
            ORDER BY id ASC
            LIMIT 12
        )
    """, (user_id,))

    conn.commit()
    conn.close()


# =========================
# 組合記憶內容
# =========================
def build_memory_context(user_id: str):
    """
    把摘要記憶 + 長期記憶 + 短期記憶組合起來
    """
    latest_summary = get_latest_summary(user_id)
    profile_memories = get_profile_memories(user_id)
    recent_messages = get_recent_messages(user_id, limit=12)

    profile_text_list = []

    for item in profile_memories:
        profile_text_list.append(f"{item['type']}: {item['value']}")

    profile_text = "\n".join(profile_text_list) if profile_text_list else "無"

    summary_text = latest_summary if latest_summary else "無"

    return summary_text, profile_text, recent_messages


# =========================
# AI 主回答函式
# =========================
def call_ai(user_id: str, user_msg: str) -> str:
    # 先嘗試抽取長期記憶
    extract_and_store_profile_memory(user_id, user_msg)

    # 如果對話太多，做摘要
    generate_and_save_summary_if_needed(user_id)

    # 組合記憶內容
    summary_text, profile_text, recent_messages = build_memory_context(user_id)

    # 系統提示詞
    system_prompt = {
        "role": "system",
        "content": (
            "你是一位貼心、清楚、使用繁體中文回答的 AI 助理。\n"
            "你要優先根據提供的長期記憶、摘要記憶、近期對話來回覆。\n"
            "如果記憶中沒有，就不要亂編。\n\n"
            f"【長期記憶】\n{profile_text}\n\n"
            f"【摘要記憶】\n{summary_text}\n"
        )
    }

    # 組合對話內容
    messages = [system_prompt] + recent_messages + [
        {"role": "user", "content": user_msg}
    ]

    # 呼叫 OpenAI 產生回覆
    ai_reply = call_openai(messages, temperature=0.7)

    # 儲存本次原始對話
    save_message(user_id, "user", user_msg)
    save_message(user_id, "assistant", ai_reply)

    return ai_reply


# =========================
# 測試首頁
# =========================
@app.get("/")
def root():
    return {"status": "ok"}


# =========================
# Webhook 入口
# =========================
@app.post("/webhook")
async def webhook(request: Request):
    # 讀取 LINE 傳進來的 JSON
    body = await request.json()

    print("Webhook body:", body)

    events = body.get("events", [])

    for event in events:
        # 只處理 message 類型
        if event.get("type") != "message":
            continue

        message = event.get("message", {})

        # 只處理文字訊息
        if message.get("type") != "text":
            continue

        source = event.get("source", {})

        # 取得 LINE 使用者 ID
        user_id = source.get("userId")

        # 取得使用者訊息
        user_msg = message.get("text", "").strip()

        # 取得回覆 token
        reply_token = event.get("replyToken")

        # 如果抓不到 user_id，直接回覆錯誤
        if not user_id:
            reply(reply_token, "無法取得使用者資訊。")
            continue

        # 清除全部記憶
        if user_msg == "/clear":
            clear_user_messages(user_id)
            clear_user_profiles(user_id)
            clear_user_summaries(user_id)
            reply(reply_token, "你的所有記憶已清除。")
            continue

        # 查看長期記憶
        if user_msg == "/memory":
            profile_memories = get_profile_memories(user_id)

            if not profile_memories:
                reply(reply_token, "目前沒有長期記憶。")
                continue

            lines = ["目前長期記憶如下："]

            for item in profile_memories:
                lines.append(f"- {item['type']}: {item['value']}")

            reply(reply_token, "\n".join(lines))
            continue

        try:
            # 呼叫 AI 回答
            ai_reply = call_ai(user_id, user_msg)
        except Exception as e:
            print("call_ai error:", str(e))
            ai_reply = f"AI 呼叫失敗：{str(e)}"

        # 回覆到 LINE
        reply(reply_token, ai_reply)

    return JSONResponse({"status": "ok"})
