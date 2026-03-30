from fastapi import FastAPI, Request
import requests
import os

app = FastAPI()

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

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

        # 👉 呼叫 AI
        ai_reply = call_ai(user_msg)

        # 👉 回傳給 LINE
        reply(reply_token, ai_reply)

    return {"status": "ok"}


def call_ai(user_msg):
    url = "https://api.openai.com/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "你是一個貼心的AI助理"},
            {"role": "user", "content": user_msg}
        ]
    }

    res = requests.post(url, headers=headers, json=data)
    result = res.json()

    return result["choices"][0]["message"]["content"]


def reply(reply_token, text):
    url = "https://api.line.me/v2/bot/message/reply"

    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    data = {
        "replyToken": reply_token,
        "messages": [
            {"type": "text", "text": text}
        ]
    }

    requests.post(url, headers=headers, json=data)
