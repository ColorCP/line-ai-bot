# ============================================================
# main.py
# ============================================================
# 🔥 第 3 階段（正式版）
#
# 功能：
# 1. LINE webhook 接收訊息
# 2. 多使用者記憶（DB）
# 3. OpenAI 自然語言回覆
# 4. 意圖判斷（記憶 / 行事曆 / 綁定）
# 5. Google OAuth（多使用者）
# 6. Google Calendar 查詢 / 新增
#
# ============================================================

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
import requests
import os

# ===============================
# 自己的模組
# ===============================
from db import init_db
from memory_service import (
    save_message,
    build_memory_context,
    clear_all_user_memory,
    auto_extract_and_save_profile_memories,
    summarize_if_needed
)
from openai_service import (
    chat_with_memory,
    parse_calendar_query,
    parse_calendar_create
)
from intent_service import detect_user_intent
from google_oauth_service import (
    build_google_oauth_start_url,
    exchange_code_and_save_token
)
from calendar_service import (
    get_today_events_text,
    create_calendar_event
)


# ============================================================
# FastAPI 初始化
# ============================================================
app = FastAPI()

# LINE Token（Railway env）
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

# Railway 網址（很重要）
APP_BASE_URL = os.getenv("APP_BASE_URL")

# 啟動時初始化 DB
init_db()


# ============================================================
# LINE 回覆函式
# ============================================================
def reply(reply_token: str, text: str):
    """
    回覆 LINE 使用者訊息
    """
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

    response = requests.post(url, headers=headers, json=payload, timeout=30)

    print("LINE reply:", response.status_code, response.text)


# ============================================================
# 健康檢查
# ============================================================
@app.get("/")
def root():
    return {"status": "ok"}


# ============================================================
# 🔥 Google OAuth Start（這裡已修正：會直接跳轉）
# ============================================================
@app.get("/google/oauth/start")
def google_oauth_start(user_id: str):
    """
    使用者點 LINE 連結後會來這裡
    👉 直接跳轉到 Google 登入頁
    """

    if not APP_BASE_URL:
        return JSONResponse({"error": "APP_BASE_URL 尚未設定"}, status_code=500)

    try:
        # 產生 Google OAuth URL
        auth_url = build_google_oauth_start_url(
            user_id=user_id,
            base_url=APP_BASE_URL
        )

        # 🔥 關鍵：直接跳轉（不是回 JSON）
        return RedirectResponse(auth_url)

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ============================================================
# Google OAuth Callback
# ============================================================
@app.get("/google/oauth/callback")
def google_oauth_callback(code: str, state: str):
    """
    Google 登入完成後會打回這裡
    """

    if not APP_BASE_URL:
        return HTMLResponse("<h1>APP_BASE_URL 尚未設定</h1>", status_code=500)

    try:
        # 用 code 換 token 並存 DB
        user_id = exchange_code_and_save_token(
            code=code,
            state=state,
            base_url=APP_BASE_URL
        )

        # 成功頁面
        return HTMLResponse(f"""
        <html>
            <body style="font-family: Arial; padding: 40px;">
                <h2>✅ Google 行事曆綁定成功</h2>
                <p>LINE 使用者 ID：{user_id}</p>
                <p>請回 LINE 測試：</p>
                <ul>
                    <li>幫我看今天行程</li>
                    <li>明天下午三點安排會議</li>
                </ul>
            </body>
        </html>
        """)

    except Exception as e:
        return HTMLResponse(f"""
        <html>
            <body style="font-family: Arial; padding: 40px;">
                <h2>❌ 綁定失敗</h2>
                <p>{str(e)}</p>
            </body>
        </html>
        """, status_code=500)


# ============================================================
# LINE Webhook
# ============================================================
@app.post("/webhook")
async def webhook(request: Request):
    body = await request.json()
    print("Webhook:", body)

    events = body.get("events", [])

    for event in events:

        if event.get("type") != "message":
            continue

        message = event.get("message", {})
        if message.get("type") != "text":
            continue

        user_id = event["source"].get("userId")
        user_msg = message.get("text", "").strip()
        reply_token = event.get("replyToken")

        if not user_id:
            reply(reply_token, "無法取得使用者資訊")
            continue

        try:
            # ====================================================
            # 1. 判斷意圖
            # ====================================================
            intent = detect_user_intent(user_msg)

            # ====================================================
            # 2. 清除記憶
            # ====================================================
            if intent == "memory_forget":
                clear_all_user_memory(user_id)
                reply(reply_token, "我已經幫你清除記憶")
                continue

            # ====================================================
            # 3. Google 綁定
            # ====================================================
            if intent == "google_bind":
                if not APP_BASE_URL:
                    reply(reply_token, "系統尚未設定網址")
                    continue

                bind_url = f"{APP_BASE_URL}/google/oauth/start?user_id={user_id}"

                reply(reply_token, f"點擊綁定 Google 行事曆：\n{bind_url}")
                continue

            # ====================================================
            # 4. 查行事曆
            # ====================================================
            if intent == "calendar_query":
                result = get_today_events_text(user_id)
                reply(reply_token, result)
                continue

            # ====================================================
            # 5. 建立行事曆
            # ====================================================
            if intent == "calendar_create":

                parsed = parse_calendar_create(user_msg)

                if not all([parsed["date"], parsed["start"], parsed["end"], parsed["title"]]):
                    reply(reply_token, "我還無法解析你的行程，請再說清楚一點")
                    continue

                result = create_calendar_event(
                    user_id=user_id,
                    date_str=parsed["date"],
                    start_str=parsed["start"],
                    end_str=parsed["end"],
                    title=parsed["title"]
                )

                reply(reply_token, result["message"])
                continue

            # ====================================================
            # 6. 一般聊天（含記憶）
            # ====================================================
            auto_extract_and_save_profile_memories(user_id, user_msg)
            summarize_if_needed(user_id)

            memory_context = build_memory_context(user_id)

            ai_reply = chat_with_memory(
                user_msg=user_msg,
                profile_text=memory_context["profile_text"],
                summary_text=memory_context["summary_text"],
                recent_messages=memory_context["recent_messages"]
            )

            save_message(user_id, "user", user_msg)
            save_message(user_id, "assistant", ai_reply)

            reply(reply_token, ai_reply)

        except Exception as e:
            print("Error:", str(e))
            reply(reply_token, f"系統錯誤：{str(e)}")

    return JSONResponse({"status": "ok"})
