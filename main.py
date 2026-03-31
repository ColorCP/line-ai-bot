# ============================================================
# main.py
# ============================================================
# 第 4 階段（AI 秘書版本）
#
# 功能：
# 1. LINE webhook 接收訊息
# 2. 多使用者記憶（DB）
# 3. OpenAI 自然語言回覆
# 4. 意圖判斷（記憶 / 行事曆 / 綁定）
# 5. Google OAuth（多使用者）
# 6. Google Calendar 查詢 / 新增
# 7. 支援查詢今天 / 明天 / 本週 / 下週 / 近期 / 未來行程
# 8. 新增行程後，回覆完整時間與主題
#
# 使用說明：
# - 這支程式是整個 LINE AI 秘書的主入口
# - LINE 傳訊息進來後，會先進 webhook()
# - webhook() 會依照使用者意圖做不同處理
#
# 注意：
# - 這支 main.py 會搭配以下檔案一起使用：
#   1. db.py
#   2. memory_service.py
#   3. openai_service.py
#   4. intent_service.py
#   5. google_oauth_service.py
#   6. calendar_service.py
# ============================================================

# ============================================================
# 匯入 FastAPI 相關模組
# ============================================================
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse

# ============================================================
# 匯入一般 Python 模組
# ============================================================
import requests
import os

# ============================================================
# 匯入自己的模組：資料庫初始化
# ============================================================
from db import init_db

# ============================================================
# 匯入記憶服務
# ============================================================
from memory_service import (
    save_message,                        # 儲存對話訊息
    build_memory_context,                # 建立記憶上下文
    clear_all_user_memory,               # 清除某位使用者所有記憶
    auto_extract_and_save_profile_memories,  # 自動抽取長期記憶
    summarize_if_needed                  # 必要時做摘要記憶
)

# ============================================================
# 匯入 OpenAI 服務
# ============================================================
from openai_service import (
    chat_with_memory,        # 一般聊天回覆
    parse_calendar_query,    # 解析行事曆查詢範圍
    parse_calendar_create    # 解析建立行程需求
)

# ============================================================
# 匯入意圖判斷服務
# ============================================================
from intent_service import detect_user_intent

# ============================================================
# 匯入 Google OAuth 服務
# ============================================================
from google_oauth_service import (
    build_google_oauth_start_url,   # 建立 Google OAuth 連結
    exchange_code_and_save_token    # callback 後換 token 並存 DB
)

# ============================================================
# 匯入 Google Calendar 服務
# ============================================================
from calendar_service import (
    get_today_events_text,      # 保留舊函式，必要時可直接用
    get_events_text_by_query,   # 根據 today / this_week / upcoming_7_days 查詢
    create_calendar_event       # 建立 Google Calendar 行程
)

# ============================================================
# FastAPI 初始化
# ============================================================
app = FastAPI()

# ============================================================
# 讀取 Railway 環境變數
# ============================================================

# LINE Messaging API Token
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

# 目前網站公開網址，例如：
# https://pleasing-rejoicing-production-183e.up.railway.app
APP_BASE_URL = os.getenv("APP_BASE_URL")

# ============================================================
# 啟動時初始化資料庫
# ============================================================
# 注意：
# 這裡會建立 SQLite table（如果還不存在）
# 所以服務啟動時一定要先執行
init_db()


# ============================================================
# LINE 回覆函式
# ============================================================
def reply(reply_token: str, text: str):
    """
    回覆 LINE 使用者訊息

    參數：
    - reply_token：LINE 提供的回覆 token
    - text：要回給使用者的文字內容

    注意：
    - LINE 單則文字長度有限制，因此這裡先截到 5000 字
    """

    # LINE Reply API endpoint
    url = "https://api.line.me/v2/bot/message/reply"

    # HTTP Header
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }

    # 要送給 LINE 的 JSON payload
    payload = {
        "replyToken": reply_token,
        "messages": [
            {
                "type": "text",
                "text": text[:5000]
            }
        ]
    }

    # 呼叫 LINE Reply API
    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=30
    )

    # 印出結果供 debug 使用
    print("LINE reply status =", response.status_code)
    print("LINE reply body =", response.text)


# ============================================================
# 健康檢查 API
# ============================================================
@app.get("/")
def root():
    """
    Railway / 瀏覽器用來確認服務是否正常啟動
    """
    return {"status": "ok"}


# ============================================================
# Google OAuth Start
# ============================================================
@app.get("/google/oauth/start")
def google_oauth_start(user_id: str):
    """
    使用者點擊 LINE 綁定連結後，會進到這裡

    流程：
    1. 從 query string 拿到 user_id
    2. 呼叫 build_google_oauth_start_url() 建立 Google 授權連結
    3. 直接 redirect 到 Google 登入頁
    """

    # 若 APP_BASE_URL 沒設定，直接回錯誤
    if not APP_BASE_URL:
        return JSONResponse(
            {"error": "APP_BASE_URL 尚未設定"},
            status_code=500
        )

    try:
        # 建立 Google 授權連結
        auth_url = build_google_oauth_start_url(
            user_id=user_id,
            base_url=APP_BASE_URL
        )

        # 印出 debug 訊息
        print("APP_BASE_URL =", APP_BASE_URL)
        print("GOOGLE AUTH URL =", auth_url)

        # 直接轉跳到 Google OAuth 畫面
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
    Google 登入授權完成後，會打回這裡

    Google 會帶回：
    - code
    - state

    我們在這裡做的事：
    1. 用 code + state 去換 token
    2. 把 token 存進 DB
    3. 顯示成功 / 失敗頁面
    """

    # 若 APP_BASE_URL 沒設定，直接顯示錯誤頁
    if not APP_BASE_URL:
        return HTMLResponse(
            "<h1>APP_BASE_URL 尚未設定</h1>",
            status_code=500
        )

    try:
        # 依照 code / state 換取 token，並存進資料庫
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
                <p>現在你可以回到 LINE 測試以下功能：</p>
                <ul>
                    <li>幫我看今天行程</li>
                    <li>我這週有哪些會議</li>
                    <li>後天新增一個會議，與 Google 開會 下午一點</li>
                </ul>
            </body>
        </html>
        """)

    except Exception as e:
        print("google_oauth_callback error =", str(e))

        # 失敗頁面
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

    流程說明：
    1. LINE 把事件 POST 到這裡
    2. 只處理文字訊息
    3. 先判斷意圖
    4. 根據意圖決定做：
       - 清除記憶
       - Google 綁定
       - 查詢行事曆
       - 新增行事曆
       - 一般聊天
    """

    # 解析 LINE 傳來的 JSON
    body = await request.json()
    print("Webhook body =", body)

    # 取出所有 event
    events = body.get("events", [])

    # 一筆一筆處理 event
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
            reply(reply_token, 
        """目前你可以這樣使用我：
        
        【🧠 一般聊天】
        - 問問題、聊天、整理資訊
        
        【📅 行事曆功能】
        👉 請先輸入：綁定行事曆
        
        綁定後可以：
        - 幫我看今天行程
        - 我這週有哪些會議
        - 我未來幾天有哪些安排
        - 明天下午三點安排與微軟開會
        
        （💡 若描述不清，我會請你補充）
        
        【🧹 記憶功能】
        - 清除記憶
        - 忘記我剛剛說的
        """)
            continue

        # 如果取不到 user_id，就無法做多使用者邏輯
        if not user_id:
            reply(reply_token, "無法取得使用者資訊")
            continue

        try:
            # =================================================
            # 1. 判斷使用者意圖
            # =================================================
            intent = detect_user_intent(user_msg)
            print("detected intent =", intent)

            # =================================================
            # 2. 清除記憶
            # =================================================
            if intent == "memory_forget":
                clear_all_user_memory(user_id)
                reply(reply_token, "我已經幫你清除記憶")
                continue

            # =================================================
            # 3. Google 行事曆綁定
            # =================================================
            if intent == "google_bind":

                # 檢查系統網址是否存在
                if not APP_BASE_URL:
                    reply(reply_token, "系統尚未設定網址")
                    continue

                # 組出綁定網址
                bind_url = f"{APP_BASE_URL}/google/oauth/start?user_id={user_id}"

                # 回給使用者點擊
                reply(
                    reply_token,
                    f"點擊綁定 Google 行事曆：\n{bind_url}"
                )
                continue

            # =================================================
            # 4. 查詢行事曆
            # =================================================
            if intent == "calendar_query":

                # 先解析查詢範圍，例如：
                # today / tomorrow / this_week / next_week /
                # upcoming_7_days / upcoming_30_days
                parsed_query = parse_calendar_query(user_msg)
                print("parsed_query =", parsed_query)

                # 查詢對應範圍的行程
                result_text = get_events_text_by_query(
                    user_id=user_id,
                    query_type=parsed_query.get("type", "unknown")
                )

                # 回覆使用者
                reply(reply_token, result_text)
                continue

            # =================================================
            # 5. 新增行事曆
            # =================================================
            if intent == "calendar_create":

                # 解析使用者文字，抽出：
                # date / start / end / title
                parsed = parse_calendar_create(user_msg)
                print("parsed_calendar_create =", parsed)

                # 若資料不完整，就提示使用者補充
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

                # 建立 Google Calendar 行程
                result = create_calendar_event(
                    user_id=user_id,
                    date_str=parsed["date"],
                    start_str=parsed["start"],
                    end_str=parsed["end"],
                    title=parsed["title"]
                )

                # 注意：
                # 這裡會回傳完整訊息，例如：
                # 已新增行程：
                # 主題：與 Google 開會
                # 開始：2026-04-02 13:00
                # 結束：2026-04-02 14:00
                reply(reply_token, result["message"])
                continue

            # =================================================
            # 6. 一般聊天（含記憶）
            # =================================================

            # 先嘗試抽取長期記憶，例如：
            # 姓名、職業、偏好、家人名稱等
            auto_extract_and_save_profile_memories(user_id, user_msg)

            # 若對話累積太多，做摘要記憶
            summarize_if_needed(user_id)

            # 建立記憶上下文
            memory_context = build_memory_context(user_id)

            # 呼叫 OpenAI，結合記憶進行回覆
            ai_reply = chat_with_memory(
                user_msg=user_msg,
                profile_text=memory_context["profile_text"],
                summary_text=memory_context["summary_text"],
                recent_messages=memory_context["recent_messages"]
            )

            # 把本輪對話存入資料庫
            save_message(user_id, "user", user_msg)
            save_message(user_id, "assistant", ai_reply)

            # 回覆給 LINE 使用者
            reply(reply_token, ai_reply)

        except Exception as e:
            # 若任何一段出錯，統一回覆錯誤訊息
            print("webhook error =", str(e))
            reply(reply_token, f"系統錯誤：{str(e)}")

    # 告知 LINE 我們有成功收到請求
    return JSONResponse({"status": "ok"})
