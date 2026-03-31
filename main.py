# ============================================================
# main.py
# ============================================================
# 第 6 階段（AI 秘書 + AI 意圖判斷 + 天氣查詢版本）
#
# 功能：
# 1. LINE webhook 接收訊息
# 2. 多使用者記憶（DB）
# 3. OpenAI 自然語言回覆
# 4. AI 意圖判斷（天氣 / 記憶 / 行事曆 / 綁定）
# 5. Google OAuth（多使用者）
# 6. Google Calendar 查詢 / 新增
# 7. 支援世界天氣查詢（用 OpenAI 解析句子，再查真實天氣）
# 8. 查天氣不再用 replace 硬拆句子，提升自然度
# ============================================================

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
import requests
import os

# ============================================================
# 天氣服務模組
# ============================================================
from weather_service import get_weather_reply

# ============================================================
# 自己的模組：資料庫初始化
# ============================================================
from db import init_db

# ============================================================
# 記憶服務
# ============================================================
from memory_service import (
    save_message,
    build_memory_context,
    clear_all_user_memory,
    auto_extract_and_save_profile_memories,
    summarize_if_needed
)

# ============================================================
# OpenAI 服務
# ============================================================
from openai_service import (
    chat_with_memory,
    parse_calendar_query,
    parse_calendar_create
)

# ============================================================
# 意圖判斷服務
# ============================================================
from intent_service import detect_user_intent

# ============================================================
# Google OAuth 服務
# ============================================================
from google_oauth_service import (
    build_google_oauth_start_url,
    exchange_code_and_save_token
)

# ============================================================
# Google Calendar 服務
# ============================================================
from calendar_service import (
    get_events_payload_by_query,
    create_calendar_event
)

# ============================================================
# 行事曆短期上下文服務
# ============================================================
from calendar_context_service import (
    save_calendar_context,
    build_calendar_context_text,
    should_use_calendar_context,
    clear_calendar_context
)

# ============================================================
# FastAPI 初始化
# ============================================================
app = FastAPI()

# LINE Messaging API Token
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

# 對外公開網址
APP_BASE_URL = os.getenv("APP_BASE_URL")

# 啟動時初始化資料庫
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

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=30
    )

    print("LINE reply status =", response.status_code)
    print("LINE reply body =", response.text)


# ============================================================
# 健康檢查
# ============================================================
@app.get("/")
def root():
    """
    確認服務正常啟動
    """
    return {"status": "ok"}


# ============================================================
# Google OAuth Start
# ============================================================
@app.get("/google/oauth/start")
def google_oauth_start(user_id: str):
    """
    使用者點擊綁定連結後，轉跳 Google 登入頁
    """
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

        print("APP_BASE_URL =", APP_BASE_URL)
        print("GOOGLE AUTH URL =", auth_url)

        return RedirectResponse(auth_url)

    except Exception as e:
        print("google_oauth_start error =", str(e))
        return JSONResponse(
            {"error": str(e)},
            status_code=500
        )


# ============================================================
# Google OAuth Callback
# ============================================================
@app.get("/google/oauth/callback")
def google_oauth_callback(code: str, state: str):
    """
    Google 登入授權完成後打回這裡
    """
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
                <p>現在你可以回到 LINE 測試以下功能：</p>
                <ul>
                    <li>幫我看今天行程</li>
                    <li>我這週有哪些會議</li>
                    <li>後天新增一個會議，與 Google 開會 下午一點</li>
                    <li>明天東京會下雨嗎</li>
                </ul>
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


# ============================================================
# LINE Webhook
# ============================================================
@app.post("/webhook")
async def webhook(request: Request):
    """
    LINE Webhook 主入口
    """
    body = await request.json()
    print("Webhook body =", body)

    events = body.get("events", [])

    for event in events:

        # ----------------------------------------------------
        # 只處理 message 類型事件
        # ----------------------------------------------------
        if event.get("type") != "message":
            continue

        # ----------------------------------------------------
        # 只處理文字訊息
        # ----------------------------------------------------
        message = event.get("message", {})
        if message.get("type") != "text":
            continue

        # ----------------------------------------------------
        # 取出使用者資料
        # ----------------------------------------------------
        user_id = event["source"].get("userId")
        user_msg = message.get("text", "").strip()
        reply_token = event.get("replyToken")

        print("user_id =", user_id)
        print("user_msg =", user_msg)

        # ====================================================
        # 功能說明（help）
        # ====================================================
        if user_msg in ["功能", "說明", "help", "HELP"]:
            reply(
                reply_token,
                """目前你可以這樣使用我：

【🧠 一般聊天】
- 問問題、聊天、整理資訊

【🌤 天氣功能】
- 今天天氣
- 明天東京會下雨嗎
- 東京明天天氣
- 巴黎現在幾度
- London weather

【📅 行事曆功能】
👉 請先輸入：綁定行事曆

綁定後可以：
- 幫我看今天行程
- 幫我看明天行程
- 我這週有哪些會議
- 我下週有哪些會議
- 我未來幾天有哪些安排
- 明天下午三點安排與微軟開會

【🧹 記憶功能】
- 清除記憶
- 忘記我剛剛說的
"""
            )
            continue

        # ----------------------------------------------------
        # 如果取不到 user_id，就無法做多使用者邏輯
        # ----------------------------------------------------
        if not user_id:
            reply(reply_token, "無法取得使用者資訊")
            continue

        try:
            # =================================================
            # 1. 先用 AI 判斷意圖
            # =================================================
            intent = detect_user_intent(user_msg)
            print("detected intent =", intent)

            # =================================================
            # 2. 天氣查詢
            # =================================================
            if intent == "weather_query":
                weather_reply = get_weather_reply(user_msg)
                reply(reply_token, weather_reply)
                continue

            # =================================================
            # 3. 清除記憶
            # =================================================
            if intent == "memory_forget":
                clear_all_user_memory(user_id)
                clear_calendar_context(user_id)
                reply(reply_token, "我已經幫你清除記憶")
                continue

            # =================================================
            # 4. Google 行事曆綁定
            # =================================================
            if intent == "google_bind":
                if not APP_BASE_URL:
                    reply(reply_token, "系統尚未設定網址")
                    continue

                bind_url = f"{APP_BASE_URL}/google/oauth/start?user_id={user_id}"

                reply(
                    reply_token,
                    f"點擊綁定 Google 行事曆：\n{bind_url}"
                )
                continue

            # =================================================
            # 5. 查詢行事曆
            # =================================================
            if intent == "calendar_query":

                parsed_query = parse_calendar_query(user_msg)
                print("parsed_query =", parsed_query)

                query_payload = get_events_payload_by_query(
                    user_id=user_id,
                    query_type=parsed_query.get("type", "unknown")
                )

                # 儲存最近一次行事曆查詢結果，供下一輪分析使用
                save_calendar_context(
                    user_id=user_id,
                    query_type=query_payload["query_type"],
                    result_text=query_payload["text"],
                    events=query_payload["events"]
                )

                reply(reply_token, query_payload["text"])
                continue

            # =================================================
            # 6. 新增行事曆
            # =================================================
            if intent == "calendar_create":

                parsed = parse_calendar_create(user_msg)
                print("parsed_calendar_create =", parsed)

                if not all([
                    parsed["date"],
                    parsed["start"],
                    parsed["end"],
                    parsed["title"]
                ]):
                    reply(
                        reply_token,
                        "我還無法完整解析你的行程，請再說清楚一點，例如：\n"
                        "後天下午三點安排與 Google 開會"
                    )
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

            # =================================================
            # 7. 一般聊天（含記憶 + 行事曆短期上下文）
            # =================================================

            # 先抽取長期記憶
            auto_extract_and_save_profile_memories(user_id, user_msg)

            # 必要時做摘要記憶
            summarize_if_needed(user_id)

            # 建立記憶上下文
            memory_context = build_memory_context(user_id)

            # 若這句話像在延續討論剛剛那份行程，就把最近行事曆結果丟給 AI
            calendar_context_text = ""
            if should_use_calendar_context(user_msg):
                calendar_context_text = build_calendar_context_text(user_id=user_id)
                print("calendar_context_text =", calendar_context_text)

            ai_reply = chat_with_memory(
                user_msg=user_msg,
                profile_text=memory_context["profile_text"],
                summary_text=memory_context["summary_text"],
                recent_messages=memory_context["recent_messages"],
                calendar_context_text=calendar_context_text
            )

            # 存入對話記錄
            save_message(user_id, "user", user_msg)
            save_message(user_id, "assistant", ai_reply)

            # 回覆使用者
            reply(reply_token, ai_reply)

        except Exception as e:
            print("webhook error =", str(e))
            reply(reply_token, f"系統錯誤：{str(e)}")

    return JSONResponse({"status": "ok"})
