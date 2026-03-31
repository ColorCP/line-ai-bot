# ============================================================
# main.py
# ============================================================
# 第 2 階段主程式
#
# 目前功能：
# 1. 接收 LINE 訊息
# 2. 讀取使用者記憶
# 3. 自動抽取長期記憶
# 4. 對話太多時自動摘要
# 5. 用 OpenAI 回覆一般聊天
# 6. 初步判斷意圖：
#    - google_bind
#    - calendar_query
#    - calendar_create
#    - memory_forget
#    - chat
#
# 目前 Google OAuth / Calendar 還是占位訊息，
# 第 3 階段會正式接上。
# ============================================================
# ============================================================
# main.py
# ============================================================

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse
import requests
import os

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


app = FastAPI()

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
APP_BASE_URL = os.getenv("APP_BASE_URL")


init_db()


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
                "text": text[:5000]
            }
        ]
    }

    response = requests.post(url, headers=headers, json=payload, timeout=30)
    print("LINE reply status:", response.status_code, response.text)


@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/google/oauth/start")
def google_oauth_start(user_id: str):
    """
    產生 Google OAuth 綁定網址
    """
    if not APP_BASE_URL:
        return JSONResponse({"error": "APP_BASE_URL 尚未設定"}, status_code=500)

    try:
        auth_url = build_google_oauth_start_url(user_id=user_id, base_url=APP_BASE_URL)
        return JSONResponse({"auth_url": auth_url})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/google/oauth/callback")
def google_oauth_callback(code: str, state: str):
    """
    Google 授權完成後的 callback
    """
    if not APP_BASE_URL:
        return HTMLResponse("<h1>APP_BASE_URL 尚未設定</h1>", status_code=500)

    try:
        user_id = exchange_code_and_save_token(
            code=code,
            state=state,
            base_url=APP_BASE_URL
        )

        return HTMLResponse(f"""
        <html>
            <body style="font-family: Arial; padding: 40px;">
                <h2>Google 行事曆綁定成功</h2>
                <p>LINE 使用者 ID：{user_id}</p>
                <p>你現在可以回到 LINE，直接使用自然語言查詢或新增行事曆。</p>
            </body>
        </html>
        """)
    except Exception as e:
        return HTMLResponse(f"""
        <html>
            <body style="font-family: Arial; padding: 40px;">
                <h2>Google 行事曆綁定失敗</h2>
                <p>{str(e)}</p>
            </body>
        </html>
        """, status_code=500)


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

        try:
            intent = detect_user_intent(user_msg)

            if intent == "memory_forget":
                clear_all_user_memory(user_id)
                reply(reply_token, "我已經幫你清除目前的記憶。")
                continue

            if intent == "google_bind":
                if not APP_BASE_URL:
                    reply(reply_token, "系統尚未完成 Google 綁定網址設定。")
                    continue

                bind_url = f"{APP_BASE_URL}/google/oauth/start?user_id={user_id}"
                reply(reply_token, f"請點這個連結完成 Google 行事曆綁定：\n{bind_url}")
                continue

            if intent == "calendar_query":
                parsed = parse_calendar_query(user_msg)

                if parsed.get("type") == "today":
                    result_text = get_today_events_text(user_id)
                    reply(reply_token, result_text)
                    continue

                reply(reply_token, "目前先支援查詢今天行程。")
                continue

            if intent == "calendar_create":
                parsed = parse_calendar_create(user_msg)

                date_str = parsed.get("date", "")
                start_str = parsed.get("start", "")
                end_str = parsed.get("end", "")
                title = parsed.get("title", "")

                if not date_str or not start_str or not end_str or not title:
                    reply(reply_token, "我目前無法完整解析你的行程內容，請再說得更明確一些。")
                    continue

                result = create_calendar_event(
                    user_id=user_id,
                    date_str=date_str,
                    start_str=start_str,
                    end_str=end_str,
                    title=title
                )

                reply(reply_token, result["message"])
                continue

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
            print("webhook error:", str(e))
            reply(reply_token, f"系統暫時發生錯誤：{str(e)}")

    return JSONResponse({"status": "ok"})
