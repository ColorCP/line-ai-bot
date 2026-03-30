from fastapi import FastAPI, Request
import requests
import os

app = FastAPI()

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

@app.get("/")
def root():
    return {"status": "ok"}

@app.post("/webhook")
async def webhook(request: Request):
    body = await request.json()

    try:
        events = body.get("events", [])

        for event in events:
            if event.get("type") != "message":
                continue

            message = event.get("message", {})
            if message.get("type") != "text":
                continue

            user_msg = message.get("text", "")
            reply_token = event.get("replyToken")

            if not reply_token:
                continue

            reply_msg = f"收到：{user_msg}"

            requests.post(
                "https://api.line.me/v2/bot/message/reply",
                headers={
                    "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
                    "Content-Type": "application/json"
                },
                json={
                    "replyToken": reply_token,
                    "messages": [
                        {"type": "text", "text": reply_msg}
                    ]
                }
            )

    except Exception as e:
        print("error:", str(e))

    return {"status": "ok"}
