# 匯入 FastAPI 框架，用來建立 API server
from fastapi import FastAPI, Request

# 回傳 JSON 格式用
from fastapi.responses import JSONResponse

# 用來呼叫外部 API（LINE / OpenAI）
import requests

# 用來讀取環境變數（API KEY）
import os

# SQLite 資料庫（用來做記憶）
import sqlite3

# 取得現在時間（存記憶時間用）
from datetime import datetime


# 建立 FastAPI 應用
app = FastAPI()


# 從系統環境變數取得 LINE token
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

# 從系統環境變數取得 OpenAI API key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


# 資料庫檔案名稱（會在同一資料夾產生一個 .db 檔）
DB_PATH = "chat_memory.db"


# =========================
# 資料庫初始化
# =========================
def init_db():
    # 連接 SQLite（如果不存在會自動建立）
    conn = sqlite3.connect(DB_PATH)

    # 建立 cursor（用來操作 SQL）
    cursor = conn.cursor()

    # 建立資料表（如果不存在才建立）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,   -- 自動編號
            user_id TEXT NOT NULL,                  -- LINE 使用者 ID
            role TEXT NOT NULL,                     -- user 或 assistant
            content TEXT NOT NULL,                  -- 訊息內容
            created_at TEXT NOT NULL                -- 時間
        )
    """)

    # 儲存變更
    conn.commit()

    # 關閉資料庫
    conn.close()


# 啟動時先建立資料庫
init_db()


# =========================
# 資料庫工具函式
# =========================

# 儲存一筆訊息（user 或 AI）
def save_message(user_id: str, role: str, content: str):

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 寫入資料
    cursor.execute("""
        INSERT INTO messages (user_id, role, content, created_at)
        VALUES (?, ?, ?, ?)
    """, (
        user_id,                      # 使用者 ID
        role,                         # user / assistant
        content,                      # 訊息內容
        datetime.now().isoformat()    # 現在時間
    ))

    conn.commit()
    conn.close()


# 取得某個使用者最近的對話紀錄
def get_recent_messages(user_id: str, limit: int = 10):

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 抓最近 N 筆（最新的在前面）
    cursor.execute("""
        SELECT role, content
        FROM messages
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
    """, (user_id, limit))

    rows = cursor.fetchall()
    conn.close()

    # 因為剛剛是 DESC（最新在前），要反轉回正常順序
    rows.reverse()

    messages = []

    # 轉成 OpenAI 需要的格式
    for role, content in rows:
        messages.append({
            "role": role,
            "content": content
        })

    return messages


# 清除某個使用者所有記憶
def clear_user_memory(user_id: str):

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 刪除該 user 所有資料
    cursor.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))

    conn.commit()
    conn.close()


# =========================
# LINE 回覆函式
# =========================
def reply(reply_token: str, text: str):

    # LINE 回覆 API
    url = "https://api.line.me/v2/bot/message/reply"

    # HTTP headers
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }

    # 傳送內容
    payload = {
        "replyToken": reply_token,
        "messages": [
            {
                "type": "text",
                "text": text[:5000]  # LINE 限制最大長度
            }
        ]
    }

    # 發送請求
    response = requests.post(url, headers=headers, json=payload)

    # 印出結果（debug 用）
    print("LINE reply status:", response.status_code, response.text)


# =========================
# OpenAI 呼叫函式（核心 AI）
# =========================
def call_ai(user_id: str, user_msg: str) -> str:

    url = "https://api.openai.com/v1/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}"
    }

    # 取得該使用者歷史記憶
    history = get_recent_messages(user_id, limit=10)

    # 系統角色（AI人格設定）
    system_prompt = {
        "role": "system",
        "content": (
            "你是一位貼心、清楚、使用繁體中文回答的 AI 助理。"
            "你會根據使用者過去對話內容延續上下文，"
            "但不要捏造不存在的記憶。"
        )
    }

    # 組合完整對話（系統 + 歷史 + 新問題）
    messages = [system_prompt] + history + [
        {"role": "user", "content": user_msg}
    ]

    payload = {
        "model": "gpt-4o-mini",
        "messages": messages,
        "temperature": 0.7
    }

    # 呼叫 OpenAI
    response = requests.post(url, headers=headers, json=payload)

    # 如果錯誤會直接丟 exception
    response.raise_for_status()

    result = response.json()

    # 取出 AI 回答
    ai_reply = result["choices"][0]["message"]["content"]

    # 存入資料庫（記憶）
    save_message(user_id, "user", user_msg)
    save_message(user_id, "assistant", ai_reply)

    return ai_reply


# =========================
# 測試 API（打開網址用）
# =========================
@app.get("/")
def root():
    return {"status": "ok"}


# =========================
# LINE webhook（入口）
# =========================
@app.post("/webhook")
async def webhook(request: Request):

    # 取得 LINE 傳來的 JSON
    body = await request.json()

    print("Webhook body:", body)

    events = body.get("events", [])

    for event in events:

        # 只處理 message 類型
        if event.get("type") != "message":
            continue

        message = event.get("message", {})

        # 只處理文字
        if message.get("type") != "text":
            continue

        source = event.get("source", {})

        # 取得 LINE 使用者 ID（超重要）
        user_id = source.get("userId")

        # 使用者輸入文字
        user_msg = message.get("text", "").strip()

        # LINE 回覆 token
        reply_token = event.get("replyToken")

        # 如果抓不到 user_id
        if not user_id:
            reply(reply_token, "無法取得使用者資訊。")
            continue

        # 測試用：清除記憶
        if user_msg == "/clear":
            clear_user_memory(user_id)
            reply(reply_token, "你的對話記憶已清除。")
            continue

        try:
            # 呼叫 AI（帶記憶）
            ai_reply = call_ai(user_id, user_msg)

        except Exception as e:
            print("call_ai error:", str(e))
            ai_reply = f"AI 呼叫失敗：{str(e)}"

        # 回覆 LINE
        reply(reply_token, ai_reply)

    return JSONResponse({"status": "ok"})
