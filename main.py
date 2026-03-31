# ============================================================
# main.py
# ============================================================
# 這支檔案是整個系統入口。
# 目前先負責：
# 1. 建立 FastAPI app
# 2. 初始化資料庫
# 3. 提供健康檢查 API
# 4. 提供 LINE webhook 基本入口
#
# 後面我們會再把：
# - OpenAI 對話
# - 記憶處理
# - Google OAuth
# - Calendar 功能
# 逐步接進來
# ============================================================

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import requests
import os

from db import init_db


# 建立 FastAPI 應用
app = FastAPI()


# 讀取 LINE Bot token
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")


# 啟動時初始化資料庫
init_db()


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

    response = requests.post(url, headers=headers, json=payload)

    print("LINE reply status:", response.status_code, response.text)


@app.get("/")
def root():
    """
    健康檢查用
    """
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request):
    """
    LINE webhook 基本入口
    目前先只確認 webhook 能正常收到訊息
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

        # 目前先做最小測試回覆
        reply(reply_token, f"收到你的訊息：{user_msg}")

    return JSONResponse({"status": "ok"})
