# ============================================================
# main.py
# ============================================================

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
import requests
import os

from db import init_db, get_google_token_by_user_id

from memory_service import (
    save_message,
    build_memory_context,
    clear_all_user_memory,
    auto_extract_and_save_profile_memories,
    summarize_if_needed
)

from openai_service import (
    parse_assistant_action,
    call_ai_with_search
)

from google_oauth_service import (
    build_google_oauth_start_url,
    exchange_code_and_save_token
)

from calendar_service import (
    get_events_payload_by_query,
    get_events_payload_by_exact_date,
    create_calendar_event
)

from calendar_context_service import (
    save_calendar_context,
    build_calendar_context_text,
    should_use_calendar_context,
    clear_calendar_context
)

# ============================================================
# FastAPI app
# ============================================================
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

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=30
    )

    print("LINE reply status =", response.status_code)
    print("LINE reply body =", response.text)


def is_google_bind_request(user_msg: str) -> bool:
    text = (user_msg or "").strip().lower()

    bind_keywords = [
        "綁定行事曆",
        "綁定 google 行事曆",
        "綁定google行事曆",
        "連接 google 行事曆",
        "連接google行事曆",
        "google行事曆綁定",
        "綁定google calendar",
        "google calendar綁定"
    ]

    return any(keyword.lower() in text for keyword in bind_keywords)


def is_google_calendar_bound(user_id: str) -> bool:
    try:
        token_data = get_google_token_by_user_id(user_id)
        return token_data is not None
    except Exception as e:
        print("is_google_calendar_bound error =", str(e))
        return False


@app.get("/")
def root():
    return {"status": "ok"}


@app.get("/google/oauth/start")
def google_oauth_start(user_id: str):
    if not APP_BASE_URL:
        return JSONResponse(
            {"error": "APP_BASE_URL 尚未設定"},
            status_code=500
        )

    try:
        auth_url = build_google_oauth_start_url(
            user_id=user_id,
            base_url=APP_BASE_URL
        )
        return RedirectResponse(auth_url)

    except Exception as e:
        print("google_oauth_start error =", str(e))
        return JSONResponse(
            {"error": str(e)},
            status_code=500
        )


@app.get("/google/oauth/callback")
def google_oauth_callback(code: str, state: str):
    if not APP_BASE_URL:
        return HTMLResponse(
            "<h1>APP_BASE_URL 尚未設定</h1>",
            status_code=500
        )

    try:
        user_id = exchange_code_and_save_token(
            code=code,
            state=state,
            base_url=APP_BASE_URL
        )

        return HTMLResponse(f"""
        <html>
            <body style="font-family: Arial; padding: 40px;">
                <h2>✅ Google 行事曆綁定成功</h2>
                <p>LINE 使用者 ID：{user_id}</p>
            </body>
        </html>
        """)

    except Exception as e:
        print("google_oauth_callback error =", str(e))
        return HTMLResponse(f"""
        <html>
            <body style="font-family: Arial; padding: 40px;">
                <h2>❌ 綁定失敗</h2>
                <p>{str(e)}</p>
            </body>
        </html>
        """, status_code=500)


@app.post("/webhook")
async def webhook(request: Request):
    body = await request.json()
    print("Webhook body =", body)

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

        print("user_id =", user_id)
        print("user_msg =", user_msg)

        if user_msg in ["功能", "說明", "help", "HELP"]:
            reply(
                reply_token,
                """目前你可以這樣使用我：

【🧠 AI 搜尋 / 問答】
- 東京明天天氣如何
- 今天有什麼科技新聞

【📅 Google 行事曆功能】
- 綁定行事曆
- 幫我看今天行程
- 我5/1有要去澎湖嗎
- 我5/1加入去澎湖三天

【🧹 記憶功能】
- 清除記憶
"""
            )
            continue

        if not user_id:
            reply(reply_token, "無法取得使用者資訊")
            continue

        try:
            if is_google_bind_request(user_msg):
                if not APP_BASE_URL:
                    reply(reply_token, "系統尚未設定網址")
                    continue

                if is_google_calendar_bound(user_id):
                    reply(
                        reply_token,
                        "你已經綁定 Google 行事曆了。"
                    )
                    continue

                bind_url = f"{APP_BASE_URL}/google/oauth/start?user_id={user_id}"
                reply(reply_token, f"請點擊以下連結綁定 Google 行事曆：\n{bind_url}")
                continue

            calendar_context_text = ""
            if should_use_calendar_context(user_msg):
                calendar_context_text = build_calendar_context_text(user_id=user_id)

            parsed_action = parse_assistant_action(
                user_msg=user_msg,
                calendar_context_text=calendar_context_text
            )
            print("parsed_action =", parsed_action)

            action = parsed_action.get("action", "general_chat")

            if action == "memory_forget":
                clear_all_user_memory(user_id)
                clear_calendar_context(user_id)
                reply(reply_token, "我已經幫你清除記憶")
                continue

            if action == "google_bind":
                if not APP_BASE_URL:
                    reply(reply_token, "系統尚未設定網址")
                    continue

                if is_google_calendar_bound(user_id):
                    reply(reply_token, "你已經綁定 Google 行事曆了。")
                    continue

                bind_url = f"{APP_BASE_URL}/google/oauth/start?user_id={user_id}"
                reply(reply_token, f"請點擊以下連結綁定 Google 行事曆：\n{bind_url}")
                continue

            if action == "calendar_query":
                query_type = parsed_action.get("calendar_query_type", "") or "today"
                query_date = parsed_action.get("query_date", "").strip()

                if query_type == "exact_date" and query_date:
                    query_payload = get_events_payload_by_exact_date(
                        user_id=user_id,
                        date_str=query_date
                    )
                else:
                    query_payload = get_events_payload_by_query(
                        user_id=user_id,
                        query_type=query_type
                    )

                save_calendar_context(
                    user_id=user_id,
                    query_type=query_payload["query_type"],
                    result_text=query_payload["text"],
                    events=query_payload["events"]
                )

                reply(reply_token, query_payload["text"])
                continue

            if action == "calendar_create":
                needs_clarification = parsed_action.get("needs_clarification", False)

                if needs_clarification:
                    clarification_question = parsed_action.get("clarification_question", "").strip()
                    if clarification_question:
                        reply(reply_token, clarification_question)
                    else:
                        reply(reply_token, "我可以幫你新增行程，但我還缺少一些資訊。")
                    continue

                all_day = bool(parsed_action.get("all_day", False))
                title = parsed_action.get("title", "").strip()

                if all_day:
                    start_date = parsed_action.get("start_date", "").strip()
                    end_date = parsed_action.get("end_date", "").strip()

                    if not all([start_date, end_date, title]):
                        reply(reply_token, "我可以幫你新增多天行程，但我還無法完整解析內容。")
                        continue

                    result = create_calendar_event(
                        user_id=user_id,
                        title=title,
                        all_day=True,
                        start_date=start_date,
                        end_date=end_date
                    )

                    reply(reply_token, result["message"])
                    continue

                date_str = parsed_action.get("date", "").strip()
                start_str = parsed_action.get("start", "").strip()
                end_str = parsed_action.get("end", "").strip()

                if not all([date_str, start_str, end_str, title]):
                    reply(reply_token, "我可以幫你新增行程，但我還無法完整解析內容。")
                    continue

                result = create_calendar_event(
                    user_id=user_id,
                    title=title,
                    date_str=date_str,
                    start_str=start_str,
                    end_str=end_str,
                    all_day=False
                )

                reply(reply_token, result["message"])
                continue

            auto_extract_and_save_profile_memories(user_id, user_msg)
            summarize_if_needed(user_id)

            memory_context = build_memory_context(user_id)

            ai_reply = call_ai_with_search(
                user_msg=user_msg,
                profile_text=memory_context["profile_text"],
                summary_text=memory_context["summary_text"],
                recent_messages=memory_context["recent_messages"],
                calendar_context_text=calendar_context_text
            )

            save_message(user_id, "user", user_msg)
            save_message(user_id, "assistant", ai_reply)

            reply(reply_token, ai_reply)

        except Exception as e:
            print("webhook error =", str(e))
            reply(reply_token, f"系統錯誤：{str(e)}")

    return JSONResponse({"status": "ok"})
