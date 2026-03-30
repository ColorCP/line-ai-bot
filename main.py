from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import requests
import os
import sqlite3
from datetime import datetime

app = FastAPI()

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

DB_PATH = "chat_memory.db"


# =========================
# 資料庫初始化
# =========================
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 對話紀錄表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


init_db()


# =========================
# 資料庫工具函式
# =========================
def save_message(user_id: str, role: str, content: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO messages (user_id, role, content, created_at)
        VALUES (?, ?, ?, ?)
    """, (user_id, role, content, datetime.now().isoformat()))

    conn.commit()
    conn.close()


def get_recent_messages(user_id: str, limit: int = 10):
    """
    取出該 user 最近幾筆對話
    limit=10 代表取最近 10 則資料（user + assistant 混合）
    """
    conn = sqlite3.connect(DB_PATH)
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

    # 因為剛剛是 DESC 取出，要再反轉回正常時間順序
    rows.reverse()

    messages = []
    for role, content in rows:
        messages.append({
            "role": role,
            "content": content
        })

    return messages


def clear_user_memory(user_id: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


# =========================
# LINE 回覆函式
# =========================
def reply(reply_token: str, text: str):
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
                "text": text[:5000]  # LINE 單則文字有長度限制，先保守截斷
            }
        ]
    }

    response = requests.post(url, headers=headers, json=payload)
    print("LINE reply status:", response.status_code, response.text)


# =========================
# OpenAI 呼叫函式
# =========================
def call_ai(user_id: str, user_msg: str) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}"
    }

    # 讀取該使用者最近對話紀錄
    history = get_recent_messages(user_id, limit=10)

    # 系統提示詞
    system_prompt = {
        "role": "system",
        "content": (
            "你是一位貼心、清楚、使用繁體中文回答的 AI 助理。"
            "你會根據使用者過去對話內容延續上下文，"
            "但不要捏造不存在的記憶。"
        )
    }

    messages = [system_prompt] + history + [
        {"role": "user", "content": user_msg}
    ]

    payload = {
        "model": "gpt-4o-mini",
        "messages": messages,
        "temperature": 0.7
    }

    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()

    result = response.json()
    ai_reply = result["choices"][0]["message"]["content"]

    # 寫入這次對話
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
# LINE webhook
# =========================
@app.post("/webhook")
async def webhook(request: Request):
    body = await request.json()
    print("Webhook body:", body)

    events = body.get("events", [])

    for event in events:
        if event.get("type") != "message":
            continue

        message = event.get("message", {})
        if message.get("type") != "text":
            continue

        source = event.get("source", {})
        user_id = source.get("userId")
        user_msg = message.get("text", "").strip()
        reply_token = event.get("replyToken")

        if not user_id:
            reply(reply_token, "無法取得使用者資訊。")
            continue

        # 你可以先做一個清除記憶指令，方便測試
        if user_msg == "/clear":
            clear_user_memory(user_id)
            reply(reply_token, "你的對話記憶已清除。")
            continue

        try:
            ai_reply = call_ai(user_id, user_msg)
        except Exception as e:
            print("call_ai error:", str(e))
            ai_reply = f"AI 呼叫失敗：{str(e)}"

        reply(reply_token, ai_reply)

    return JSONResponse({"status": "ok"})
