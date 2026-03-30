from fastapi import FastAPI, Request
import requests
import os

app = FastAPI()

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


@app.get("/")
def root():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request):
    body = await request.json()
    print("Webhook body:", body)

    events = body.get("events", [])

    for event in events:
        if event.get("type") != "message":
            continue

        message = event.get("message", {})
        if message.get("type") != "text":
            continue

        user_msg = message.get("text", "")
        reply_token = event.get("replyToken")

        try:
            ai_reply = call_ai(user_msg)
        except Exception as e:
            print("call_ai error:", str(e))
            ai_reply = f"AI 呼叫失敗：{str(e)}"

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

    res = requests.post(url, headers=headers, json=data, timeout=30)
    print("OpenAI status:", res.status_code)
    print("OpenAI response:", res.text)

    if res.status_code != 200:
        raise Exception(f"OpenAI API 錯誤 {res.status_code}: {res.text}")

    result = res.json()

    if "choices" not in result:
        raise Exception(f"OpenAI 回傳格式異常: {result}")

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
            {"type": "text", "text": text[:5000]}
        ]
    }

    res = requests.post(url, headers=headers, json=data, timeout=10)
    print("LINE reply status:", res.status_code)
    print("LINE reply response:", res.text)
