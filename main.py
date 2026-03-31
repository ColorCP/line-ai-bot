# ============================================================
# main.py
# ============================================================
# 第 9 階段（AI 秘書 + 專屬功能硬保護版本）
#
# 功能：
# 1. LINE webhook 接收訊息
# 2. 多使用者記憶（DB）
# 3. 一般搜尋 / 問答 -> OpenAI Responses API + web search
# 4. AI 判斷是不是：
#    - 綁定 Google 行事曆
#    - 清除記憶
#    - 查詢行事曆
#    - 新增行事曆
#    - 一般聊天 / 搜尋 / 問答
# 5. 綁定行事曆先做硬判斷，避免 AI 亂回答 Apple / Outlook
# 6. 若已綁定 Google 行事曆，直接回覆已綁定
# ============================================================

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
import requests
import os

# ============================================================
# 自己的模組：資料庫初始化 + Google token 查詢
# ============================================================
from db import init_db, get_google_token_by_user_id

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
    parse_assistant_action,
    call_ai_with_search
)

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
# 工具函式：回覆 LINE
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
# 工具函式：判斷是否為綁定 Google 行事曆意圖（硬判斷）
# 說明：
# 這些句子不應該丟給一般 AI 回答，否則容易亂講 Apple/Outlook
# ============================================================
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


# ============================================================
# 工具函式：判斷是否已綁定 Google 行事曆
# ============================================================
def is_google_calendar_bound(user_id: str) -> bool:
    """
    只檢查 DB 裡是否已有此 user_id 的 Google token
    """
    try:
        token_data = get_google_token_by_user_id(user_id)
        return token_data is not None
    except Exception as e:
        print("is_google_calendar_bound error =", str(e))
        return False


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
                    <li>明天下午三點安排與 Google 開會</li>
                    <li>東京明天天氣如何</li>
                    <li>今天有什麼科技新聞</li>
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

【🧠 AI 搜尋 / 問答】
- 東京明天天氣如何
- 今天有什麼科技新聞
- 幫我比較 WRX 跟 Lexus IS
- 日本滑雪推薦哪裡
- 幫我整理某個主題

【📅 Google 行事曆功能】
👉 目前只支援 Google 行事曆
👉 請先輸入：綁定行事曆

綁定後可以自然地說：
- 幫我看今天行程
- 我明天下午有空嗎
- 我這週有哪些會議
- 明天下午三點安排與微軟開會
- 後天下午兩點新增家庭聚餐

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
            # 0. 綁定 Google 行事曆：先做硬保護
            # 說明：
            # 避免一般 AI 回答亂扯 Apple / Outlook / 裝置同步
            # =================================================
            if is_google_bind_request(user_msg):
                if not APP_BASE_URL:
                    reply(reply_token, "系統尚未設定網址")
                    continue

                # 已綁定
                if is_google_calendar_bound(user_id):
                    reply(
                        reply_token,
                        "你已經綁定 Google 行事曆了。\n"
                        "你現在可以直接問我：\n"
                        "- 幫我看今天行程\n"
                        "- 我這週有哪些會議\n"
                        "- 明天下午三點安排與 Google 開會"
                    )
                    continue

                # 尚未綁定
                bind_url = f"{APP_BASE_URL}/google/oauth/start?user_id={user_id}"

                reply(
                    reply_token,
                    f"請點擊以下連結綁定 Google 行事曆：\n{bind_url}"
                )
                continue

            # =================================================
            # 1. AI 先判斷這句話要做什麼
            # =================================================
            parsed_action = parse_assistant_action(user_msg)
            print("parsed_action =", parsed_action)

            action = parsed_action.get("action", "general_chat")

            # =================================================
            # 2. 清除記憶
            # =================================================
            if action == "memory_forget":
                clear_all_user_memory(user_id)
                clear_calendar_context(user_id)
                reply(reply_token, "我已經幫你清除記憶")
                continue

            # =================================================
            # 3. Google 行事曆綁定（AI 解析到的情況）
            # =================================================
            if action == "google_bind":
                if not APP_BASE_URL:
                    reply(reply_token, "系統尚未設定網址")
                    continue

                if is_google_calendar_bound(user_id):
                    reply(
                        reply_token,
                        "你已經綁定 Google 行事曆了。\n"
                        "你可以直接叫我幫你查或新增行程。"
                    )
                    continue

                bind_url = f"{APP_BASE_URL}/google/oauth/start?user_id={user_id}"

                reply(
                    reply_token,
                    f"請點擊以下連結綁定 Google 行事曆：\n{bind_url}"
                )
                continue

            # =================================================
            # 4. 查詢行事曆
            # =================================================
            if action == "calendar_query":
                query_type = parsed_action.get("calendar_query_type", "") or "today"

                query_payload = get_events_payload_by_query(
                    user_id=user_id,
                    query_type=query_type
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
            # 5. 新增行事曆
            # =================================================
            if action == "calendar_create":
                needs_clarification = parsed_action.get("needs_clarification", False)

                if needs_clarification:
                    clarification_question = parsed_action.get("clarification_question", "").strip()
                    if clarification_question:
                        reply(reply_token, clarification_question)
                    else:
                        reply(reply_token, "我可以幫你新增行程，但我還缺少一些資訊，請再描述清楚一點。")
                    continue

                date_str = parsed_action.get("date", "").strip()
                start_str = parsed_action.get("start", "").strip()
                end_str = parsed_action.get("end", "").strip()
                title = parsed_action.get("title", "").strip()

                if not all([date_str, start_str, end_str, title]):
                    reply(
                        reply_token,
                        "我可以幫你新增行程，但我還無法完整解析內容，請再說清楚一點，例如：\n"
                        "後天下午三點安排與 Google 開會"
                    )
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

            # =================================================
            # 6. 其他全部走 AI 搜尋 / 問答
            # =================================================
            auto_extract_and_save_profile_memories(user_id, user_msg)
            summarize_if_needed(user_id)

            memory_context = build_memory_context(user_id)

            calendar_context_text = ""
            if should_use_calendar_context(user_msg):
                calendar_context_text = build_calendar_context_text(user_id=user_id)
                print("calendar_context_text =", calendar_context_text)

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
