# ============================================================
# main.py
# 功能：
# 1. 接收 LINE Webhook
# 2. 處理 Google 行事曆 OAuth 綁定
# 3. 處理 Google 行事曆查詢 / 建立事件
# 4. 處理記憶功能
# 5. 呼叫 AI 做一般問答 / 搜尋
# ============================================================

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
import requests
import os

# ============================================================
# 你自己的模組
# ============================================================
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
# 建立 FastAPI app
# Railway / Uvicorn 會找這個 app
# 啟動指令要對應 main:app
# ============================================================
app = FastAPI()

# ============================================================
# 環境變數
# ============================================================
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
APP_BASE_URL = os.getenv("APP_BASE_URL", "")

# ============================================================
# 啟動時初始化資料庫
# ============================================================
init_db()


# ============================================================
# 回覆 LINE 使用者訊息
# ============================================================
def reply(reply_token: str, text: str):
    """
    將文字回覆給 LINE 使用者
    LINE 單則文字有長度限制，因此這裡做 5000 字截斷
    """
    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("LINE_CHANNEL_ACCESS_TOKEN 尚未設定")
        return

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
                "text": (text or "")[:5000]
            }
        ]
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=30
        )
        print("LINE reply status =", response.status_code)
        print("LINE reply body =", response.text)
    except Exception as e:
        print("LINE reply error =", str(e))


# ============================================================
# 判斷是否是要求綁定 Google 行事曆
# ============================================================
def is_google_bind_request(user_msg: str) -> bool:
    """
    用簡單關鍵字先做第一層判斷
    """
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
# 判斷使用者是否已經綁定 Google 行事曆
# ============================================================
def is_google_calendar_bound(user_id: str) -> bool:
    """
    只要 DB 裡查得到 token，就視為已綁定
    """
    try:
        token_data = get_google_token_by_user_id(user_id)
        return token_data is not None
    except Exception as e:
        print("is_google_calendar_bound error =", str(e))
        return False


# ============================================================
# 首頁健康檢查
# Railway 可用來確認服務是否活著
# ============================================================
@app.get("/")
def root():
    return {"status": "ok"}


# ============================================================
# Google OAuth 起始點
# 使用者點擊這個網址後，會跳去 Google 授權頁面
# ============================================================
@app.get("/google/oauth/start")
def google_oauth_start(user_id: str):
    """
    產生 Google OAuth 授權網址，然後導向過去
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
        return RedirectResponse(auth_url)

    except Exception as e:
        print("google_oauth_start error =", str(e))
        return JSONResponse(
            {"error": str(e)},
            status_code=500
        )


# ============================================================
# Google OAuth Callback
# Google 授權成功後會導回這裡
# ============================================================
@app.get("/google/oauth/callback")
def google_oauth_callback(code: str, state: str):
    """
    1. 用 Google 回傳的 code 換 token
    2. 將 token 存到 DB
    3. 顯示綁定成功頁面
    """
    if not APP_BASE_URL:
        return HTMLResponse(
            content="""
            <html>
                <head>
                    <meta charset="utf-8">
                    <title>系統錯誤</title>
                </head>
                <body style="font-family: Arial, 'Microsoft JhengHei', sans-serif; padding: 40px;">
                    <h2>❌ APP_BASE_URL 尚未設定</h2>
                </body>
            </html>
            """,
            status_code=500
        )

    try:
        # ====================================================
        # 用 code 換 token，並儲存到 DB
        # 同時回傳綁定的 LINE user_id
        # ====================================================
        user_id = exchange_code_and_save_token(
            code=code,
            state=state,
            base_url=APP_BASE_URL
        )

        # ====================================================
        # 綁定成功頁面（你要的樣式）
        # ====================================================
        html = f"""
        <!DOCTYPE html>
        <html lang="zh-Hant">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Google 行事曆綁定成功</title>
            <style>
                body {{
                    font-family: Arial, "Microsoft JhengHei", sans-serif;
                    background-color: #f3f4f6;
                    margin: 0;
                    padding: 30px;
                }}

                .card {{
                    max-width: 760px;
                    margin: 40px auto;
                    background: #ffffff;
                    padding: 32px 40px;
                    border-radius: 12px;
                    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
                    color: #111827;
                    line-height: 1.8;
                }}

                .title-row {{
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    margin-bottom: 20px;
                }}

                .icon {{
                    width: 28px;
                    height: 28px;
                    background-color: #22c55e;
                    color: white;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    border-radius: 4px;
                    font-size: 20px;
                    font-weight: bold;
                    flex-shrink: 0;
                }}

                .title {{
                    font-size: 22px;
                    font-weight: bold;
                    margin: 0;
                }}

                .label {{
                    font-weight: normal;
                }}

                .user-id {{
                    word-break: break-all;
                }}

                .desc {{
                    margin-top: 18px;
                    margin-bottom: 8px;
                }}

                ul {{
                    margin-top: 8px;
                    padding-left: 28px;
                }}

                li {{
                    margin-bottom: 4px;
                    font-size: 16px;
                }}
            </style>
        </head>
        <body>
            <div class="card">
                <div class="title-row">
                    <div class="icon">✓</div>
                    <h1 class="title">Google 行事曆綁定成功</h1>
                </div>

                <p>
                    <span class="label">LINE 使用者 ID:</span>
                    <span class="user-id">{user_id}</span>
                </p>

                <p class="desc">現在你可以回到 LINE 測試以下功能：</p>

                <ul>
                    <li>幫我看今天行程</li>
                    <li>我這週有哪些會議</li>
                    <li>明天下午三點安排與 Google 開會</li>
                    <li>東京明天天氣如何</li>
                    <li>今天有什麼科技新聞</li>
                </ul>
            </div>
        </body>
        </html>
        """

        return HTMLResponse(content=html)

    except Exception as e:
        print("google_oauth_callback error =", str(e))

        error_html = f"""
        <!DOCTYPE html>
        <html lang="zh-Hant">
        <head>
            <meta charset="UTF-8">
            <title>Google 行事曆綁定失敗</title>
            <style>
                body {{
                    font-family: Arial, "Microsoft JhengHei", sans-serif;
                    background-color: #f3f4f6;
                    margin: 0;
                    padding: 30px;
                }}

                .card {{
                    max-width: 760px;
                    margin: 40px auto;
                    background: #ffffff;
                    padding: 32px 40px;
                    border-radius: 12px;
                    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
                    color: #111827;
                    line-height: 1.8;
                }}

                .title {{
                    color: #dc2626;
                    font-size: 22px;
                    font-weight: bold;
                    margin-top: 0;
                }}

                .error-text {{
                    color: #374151;
                    white-space: pre-wrap;
                    word-break: break-word;
                }}
            </style>
        </head>
        <body>
            <div class="card">
                <h1 class="title">❌ Google 行事曆綁定失敗</h1>
                <p class="error-text">{str(e)}</p>
            </div>
        </body>
        </html>
        """

        return HTMLResponse(content=error_html, status_code=500)


# ============================================================
# LINE Webhook
# LINE 傳來的訊息都會從這裡進來
# ============================================================
@app.post("/webhook")
async def webhook(request: Request):
    """
    LINE Bot 的主入口：
    1. 解析使用者訊息
    2. 判斷是否要綁定 Google
    3. 判斷是否是行事曆查詢 / 建立
    4. 判斷是否清除記憶
    5. 其餘交給 AI 搜尋 / 問答
    """
    try:
        body = await request.json()
        print("Webhook body =", body)
    except Exception as e:
        print("read webhook json error =", str(e))
        return JSONResponse({"status": "invalid json"}, status_code=400)

    events = body.get("events", [])

    for event in events:
        try:
            # ------------------------------------------------
            # 只處理文字訊息
            # ------------------------------------------------
            if event.get("type") != "message":
                continue

            message = event.get("message", {})
            if message.get("type") != "text":
                continue

            source = event.get("source", {})
            user_id = source.get("userId")
            user_msg = (message.get("text", "") or "").strip()
            reply_token = event.get("replyToken")

            print("user_id =", user_id)
            print("user_msg =", user_msg)

            # ------------------------------------------------
            # 沒有 user_id 就無法做綁定 / 記憶 / 行事曆
            # ------------------------------------------------
            if not user_id:
                reply(reply_token, "無法取得使用者資訊")
                continue

            # ------------------------------------------------
            # 功能說明
            # ------------------------------------------------
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

            # ------------------------------------------------
            # 先處理明確的 Google 綁定需求
            # ------------------------------------------------
            if is_google_bind_request(user_msg):
                if not APP_BASE_URL:
                    reply(reply_token, "系統尚未設定網址")
                    continue

                if is_google_calendar_bound(user_id):
                    reply(reply_token, "你已經綁定 Google 行事曆了。")
                    continue

                bind_url = f"{APP_BASE_URL}/google/oauth/start?user_id={user_id}"
                reply(reply_token, f"請點擊以下連結綁定 Google 行事曆：\n{bind_url}")
                continue

            # ------------------------------------------------
            # 是否需要把先前查過的行事曆內容當上下文帶入
            # ------------------------------------------------
            calendar_context_text = ""
            if should_use_calendar_context(user_msg):
                calendar_context_text = build_calendar_context_text(user_id=user_id)

            # ------------------------------------------------
            # 讓 AI 先判斷這句話屬於什麼動作
            # 例如：
            # - google_bind
            # - calendar_query
            # - calendar_create
            # - memory_forget
            # - general_chat
            # ------------------------------------------------
            parsed_action = parse_assistant_action(
                user_msg=user_msg,
                calendar_context_text=calendar_context_text
            )
            print("parsed_action =", parsed_action)

            action = parsed_action.get("action", "general_chat")

            # ------------------------------------------------
            # 清除記憶
            # ------------------------------------------------
            if action == "memory_forget":
                clear_all_user_memory(user_id)
                clear_calendar_context(user_id)
                reply(reply_token, "我已經幫你清除記憶")
                continue

            # ------------------------------------------------
            # AI 判斷要進行 Google 綁定
            # ------------------------------------------------
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

            # ------------------------------------------------
            # 行事曆查詢
            # ------------------------------------------------
            if action == "calendar_query":
                query_type = parsed_action.get("calendar_query_type", "") or "today"
                query_date = (parsed_action.get("query_date", "") or "").strip()

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

                # 把這次查到的行程存成上下文，方便下一句接著問
                save_calendar_context(
                    user_id=user_id,
                    query_type=query_payload["query_type"],
                    result_text=query_payload["text"],
                    events=query_payload["events"]
                )

                reply(reply_token, query_payload["text"])
                continue

            # ------------------------------------------------
            # 行事曆建立事件
            # ------------------------------------------------
            if action == "calendar_create":
                needs_clarification = parsed_action.get("needs_clarification", False)

                # 如果資訊不夠完整，先回問使用者
                if needs_clarification:
                    clarification_question = (parsed_action.get("clarification_question", "") or "").strip()
                    if clarification_question:
                        reply(reply_token, clarification_question)
                    else:
                        reply(reply_token, "我可以幫你新增行程，但我還缺少一些資訊。")
                    continue

                all_day = bool(parsed_action.get("all_day", False))
                title = (parsed_action.get("title", "") or "").strip()

                # 多天 / 全天事件
                if all_day:
                    start_date = (parsed_action.get("start_date", "") or "").strip()
                    end_date = (parsed_action.get("end_date", "") or "").strip()

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

                # 一般有時間的事件
                date_str = (parsed_action.get("date", "") or "").strip()
                start_str = (parsed_action.get("start", "") or "").strip()
                end_str = (parsed_action.get("end", "") or "").strip()

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

            # ------------------------------------------------
            # 一般聊天 / AI 搜尋 / 新聞 / 天氣等
            # ------------------------------------------------
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

            # 儲存對話紀錄
            save_message(user_id, "user", user_msg)
            save_message(user_id, "assistant", ai_reply)

            reply(reply_token, ai_reply)

        except Exception as e:
            print("event handling error =", str(e))
            try:
                reply_token = event.get("replyToken")
                if reply_token:
                    reply(reply_token, f"系統錯誤：{str(e)}")
            except Exception as inner_e:
                print("reply error after event error =", str(inner_e))

    return JSONResponse({"status": "ok"})
