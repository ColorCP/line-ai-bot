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

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
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
from openai_service import chat_with_memory
from intent_service import detect_user_intent
from google_oauth_service import build_google_bind_message
from calendar_service import (
    handle_calendar_query_placeholder,
    handle_calendar_create_placeholder
)


app = FastAPI()

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")


init_db()


def reply(reply_token: str, text: str):
    """
    回覆 LINE 訊息
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
    print("LINE reply status:", response.status_code, response.text)


@app.get("/")
def root():
    """
    健康檢查 API
    """
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request):
    """
    LINE webhook 入口
    """
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
            # ====================================================
            # 1. 意圖判斷
            # ====================================================
            intent = detect_user_intent(user_msg)

            # ====================================================
            # 2. 特殊意圖先處理
            # ====================================================
            if intent == "memory_forget":
                clear_all_user_memory(user_id)
                reply(reply_token, "我已經幫你清除目前的記憶。")
                continue

            if intent == "google_bind":
                bind_message = build_google_bind_message()
                reply(reply_token, bind_message)
                continue

            if intent == "calendar_query":
                result_text = handle_calendar_query_placeholder()
                reply(reply_token, result_text)
                continue

            if intent == "calendar_create":
                result_text = handle_calendar_create_placeholder()
                reply(reply_token, result_text)
                continue

            # ====================================================
            # 3. 一般聊天：先抽長期記憶
            # ====================================================
            auto_extract_and_save_profile_memories(user_id, user_msg)

            # ====================================================
            # 4. 對話太多就做摘要
            # ====================================================
            summarize_if_needed(user_id)

            # ====================================================
            # 5. 組合記憶內容
            # ====================================================
            memory_context = build_memory_context(user_id)

            profile_text = memory_context["profile_text"]
            summary_text = memory_context["summary_text"]
            recent_messages = memory_context["recent_messages"]

            # ====================================================
            # 6. 產生 AI 回答
            # ====================================================
            ai_reply = chat_with_memory(
                user_msg=user_msg,
                profile_text=profile_text,
                summary_text=summary_text,
                recent_messages=recent_messages
            )

            # ====================================================
            # 7. 存回對話記錄
            # ====================================================
            save_message(user_id, "user", user_msg)
            save_message(user_id, "assistant", ai_reply)

            # ====================================================
            # 8. 回覆 LINE
            # ====================================================
            reply(reply_token, ai_reply)

        except Exception as e:
            print("webhook error:", str(e))
            reply(reply_token, f"系統暫時發生錯誤：{str(e)}")

    return JSONResponse({"status": "ok"})
