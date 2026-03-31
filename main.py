# ============================================================
# main.py（穩定版，不會 ASGI 爆炸）
# ============================================================

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
import requests
import os

# ============================================================
# ⚠️ 關鍵：安全 import（避免整個 app 爆掉）
# ============================================================

def safe_import(module_name, names):
    """
    安全載入模組
    如果失敗，不讓整個 FastAPI 掛掉
    """
    try:
        module = __import__(module_name, fromlist=names)
        return [getattr(module, name) for name in names]
    except Exception as e:
        print(f"[IMPORT ERROR] {module_name} -> {str(e)}")
        return [None] * len(names)


# ============================================================
# 安全載入你的模組
# ============================================================

init_db, get_google_token_by_user_id = safe_import(
    "db", ["init_db", "get_google_token_by_user_id"]
)

(
    save_message,
    build_memory_context,
    clear_all_user_memory,
    auto_extract_and_save_profile_memories,
    summarize_if_needed
) = safe_import(
    "memory_service",
    [
        "save_message",
        "build_memory_context",
        "clear_all_user_memory",
        "auto_extract_and_save_profile_memories",
        "summarize_if_needed"
    ]
)

parse_assistant_action, call_ai_with_search = safe_import(
    "openai_service",
    ["parse_assistant_action", "call_ai_with_search"]
)

build_google_oauth_start_url, exchange_code_and_save_token = safe_import(
    "google_oauth_service",
    ["build_google_oauth_start_url", "exchange_code_and_save_token"]
)

(
    get_events_payload_by_query,
    get_events_payload_by_exact_date,
    create_calendar_event
) = safe_import(
    "calendar_service",
    [
        "get_events_payload_by_query",
        "get_events_payload_by_exact_date",
        "create_calendar_event"
    ]
)

(
    save_calendar_context,
    build_calendar_context_text,
    should_use_calendar_context,
    clear_calendar_context
) = safe_import(
    "calendar_context_service",
    [
        "save_calendar_context",
        "build_calendar_context_text",
        "should_use_calendar_context",
        "clear_calendar_context"
    ]
)

# ============================================================
# FastAPI app（⚠️ 一定要存在）
# ============================================================
app = FastAPI()

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
APP_BASE_URL = os.getenv("APP_BASE_URL", "")

# ============================================================
# 初始化 DB（若存在）
# ============================================================
if init_db:
    try:
        init_db()
    except Exception as e:
        print("init_db error =", str(e))


# ============================================================
# LINE 回覆
# ============================================================
def reply(reply_token: str, text: str):
    if not LINE_CHANNEL_ACCESS_TOKEN:
        print("LINE token not set")
        return

    url = "https://api.line.me/v2/bot/message/reply"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }

    payload = {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": text[:5000]}]
    }

    try:
        requests.post(url, headers=headers, json=payload)
    except Exception as e:
        print("LINE reply error =", str(e))


# ============================================================
# 健康檢查
# ============================================================
@app.get("/")
def root():
    return {"status": "ok"}


# ============================================================
# Google OAuth Start
# ============================================================
@app.get("/google/oauth/start")
def google_start(user_id: str):
    if not build_google_oauth_start_url:
        return JSONResponse({"error": "OAuth module not loaded"}, 500)

    url = build_google_oauth_start_url(user_id=user_id, base_url=APP_BASE_URL)
    return RedirectResponse(url)


# ============================================================
# ⭐ Google OAuth Callback（你要的畫面）
# ============================================================
@app.get("/google/oauth/callback")
def google_callback(code: str, state: str):

    try:
        user_id = exchange_code_and_save_token(
            code=code,
            state=state,
            base_url=APP_BASE_URL
        ) if exchange_code_and_save_token else "unknown"

        return HTMLResponse(f"""
        <!DOCTYPE html>
        <html lang="zh-Hant">
        <head>
            <meta charset="UTF-8">
            <title>Google 行事曆綁定成功</title>
            <style>
                body {{
                    font-family: Arial, "Microsoft JhengHei";
                    background: #f3f4f6;
                    padding: 30px;
                }}
                .card {{
                    max-width: 700px;
                    margin: auto;
                    background: white;
                    padding: 30px;
                    border-radius: 12px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.1);
                }}
                .title {{
                    font-size: 22px;
                    font-weight: bold;
                    margin-bottom: 20px;
                }}
            </style>
        </head>
        <body>
            <div class="card">
                <div class="title">✅ Google 行事曆綁定成功</div>

                <p>LINE 使用者 ID: {user_id}</p>

                <p>現在你可以回到 LINE 測試以下功能：</p>

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
        """)

    except Exception as e:
        return HTMLResponse(f"<h1>錯誤：{str(e)}</h1>", status_code=500)


# ============================================================
# LINE Webhook（簡化版，先確保穩定）
# ============================================================
@app.post("/webhook")
async def webhook(request: Request):

    body = await request.json()
    events = body.get("events", [])

    for event in events:

        if event.get("type") != "message":
            continue

        message = event.get("message", {})
        if message.get("type") != "text":
            continue

        user_msg = message.get("text", "")
        reply_token = event.get("replyToken")

        # 👉 測試 AI 是否正常
        if call_ai_with_search:
            try:
                ai_reply = call_ai_with_search(user_msg)
            except Exception as e:
                ai_reply = f"AI錯誤: {str(e)}"
        else:
            ai_reply = "AI 尚未初始化（可能 openai_service 有錯）"

        reply(reply_token, ai_reply)

    return {"status": "ok"}
