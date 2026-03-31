# ============================================================
# openai_service.py
# ============================================================
# 這支檔案專門負責：
# 1. 呼叫 OpenAI API
# 2. 提供一般聊天回覆
# 3. 提供記憶抽取
# 4. 提供意圖判斷
#
# 後面如果你要換模型、改參數，
# 集中改這裡就好，不用去 main.py 到處改。
# ============================================================

import os
import requests


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def call_openai(messages: list, temperature: float = 0.3) -> str:
    """
    通用 OpenAI 呼叫函式
    messages 要符合 Chat Completions 格式
    """
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY 尚未設定")

    url = "https://api.openai.com/v1/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}"
    }

    payload = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "temperature": temperature
    }

    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()

    result = response.json()
    return result["choices"][0]["message"]["content"]


def extract_profile_memories_from_text(user_msg: str) -> list:
    """
    從使用者輸入中抽取可長期記憶的資訊
    回傳格式：
    [
        {"type": "name", "value": "卡樂"},
        {"type": "job", "value": "軟體工程師"}
    ]
    如果沒有可記憶內容，回傳空陣列
    """
    messages = [
        {
            "role": "system",
            "content": (
                "你是一個記憶抽取器。"
                "請從使用者輸入中判斷是否有值得長期記住的個人資訊。"
                "例如：姓名、職業、家人名稱、語言偏好、長期喜好、目標。"
                "如果沒有，回覆 NONE。"
                "如果有，請只輸出 JSON 陣列，格式如下："
                '[{"type":"name","value":"卡樂"}]'
                "type 只能是 name、job、family、preference、language、goal。"
                "不要輸出其他說明。"
            )
        },
        {
            "role": "user",
            "content": user_msg
        }
    ]

    result = call_openai(messages, temperature=0.0).strip()

    if result.upper() == "NONE":
        return []

    try:
        import json
        data = json.loads(result)

        if isinstance(data, list):
            cleaned = []

            for item in data:
                if not isinstance(item, dict):
                    continue

                memory_type = str(item.get("type", "")).strip()
                memory_value = str(item.get("value", "")).strip()

                if memory_type and memory_value:
                    cleaned.append({
                        "type": memory_type,
                        "value": memory_value
                    })

            return cleaned

    except Exception:
        return []

    return []


def summarize_messages_for_memory(old_messages: list) -> str:
    """
    將較舊對話整理成摘要
    old_messages 格式：
    [{"role":"user","content":"..."}, {"role":"assistant","content":"..."}]
    """
    text_lines = []

    for item in old_messages:
        role = item.get("role", "")
        content = item.get("content", "")
        text_lines.append(f"{role}: {content}")

    old_text = "\n".join(text_lines)

    messages = [
        {
            "role": "system",
            "content": (
                "請把以下對話整理成精簡摘要，"
                "保留重要背景、需求、偏好、已確認資訊。"
                "請使用繁體中文，內容精簡但完整。"
            )
        },
        {
            "role": "user",
            "content": old_text
        }
    ]

    return call_openai(messages, temperature=0.2).strip()


def chat_with_memory(user_msg: str, profile_text: str, summary_text: str, recent_messages: list) -> str:
    """
    使用記憶上下文進行聊天回覆
    """
    system_prompt = {
        "role": "system",
        "content": (
            "你是一位貼心、清楚、使用繁體中文回答的 AI 助理。\n"
            "你要優先根據提供的長期記憶、摘要記憶、近期對話來回覆。\n"
            "如果記憶中沒有，就不要亂編。\n\n"
            f"【長期記憶】\n{profile_text}\n\n"
            f"【摘要記憶】\n{summary_text}\n"
        )
    }

    messages = [system_prompt] + recent_messages + [
        {"role": "user", "content": user_msg}
    ]

    return call_openai(messages, temperature=0.7).strip()


def classify_intent(user_msg: str) -> str:
    """
    粗略意圖分類，先分出後面會用到的類型
    回傳其中一種：
    - google_bind
    - calendar_query
    - calendar_create
    - memory_forget
    - chat
    """
    messages = [
        {
            "role": "system",
            "content": (
                "請判斷使用者訊息意圖，只能回覆以下其中一個字串：\n"
                "google_bind\n"
                "calendar_query\n"
                "calendar_create\n"
                "memory_forget\n"
                "chat\n\n"
                "判斷規則：\n"
                "- 如果是在要求綁定 Google 行事曆，回 google_bind\n"
                "- 如果是在問今天/明天/某時間有沒有行程，回 calendar_query\n"
                "- 如果是在要求新增/安排/建立行事曆事件，回 calendar_create\n"
                "- 如果是在要求忘記、刪除記憶，回 memory_forget\n"
                "- 其餘一般聊天，回 chat\n"
                "不要輸出其他文字。"
            )
        },
        {
            "role": "user",
            "content": user_msg
        }
    ]

    result = call_openai(messages, temperature=0.0).strip()

    allowed = {
        "google_bind",
        "calendar_query",
        "calendar_create",
        "memory_forget",
        "chat"
    }

    if result in allowed:
        return result

    return "chat"

def parse_calendar_query(user_msg: str) -> dict:
    """
    解析查詢行事曆需求
    第 1 版先只支援今天
    """
    messages = [
        {
            "role": "system",
            "content": (
                "請解析使用者是否在查詢今天行程。"
                "如果是，回覆 JSON：{\"type\":\"today\"}"
                "如果不是，回覆 JSON：{\"type\":\"unknown\"}"
                "不要輸出其他文字。"
            )
        },
        {
            "role": "user",
            "content": user_msg
        }
    ]

    result = call_openai(messages, temperature=0.0).strip()

    try:
        import json
        return json.loads(result)
    except Exception:
        return {"type": "unknown"}


def parse_calendar_create(user_msg: str) -> dict:
    """
    解析新增行事曆需求
    第 1 版要求 AI 輸出固定 JSON
    """
    messages = [
        {
            "role": "system",
            "content": (
                "請從使用者輸入中解析行事曆建立需求。"
                "請只輸出 JSON，不要輸出其他文字。"
                "格式如下："
                '{"date":"2026-03-31","start":"15:00","end":"16:00","title":"與客戶開會"}'
                "如果無法解析，請輸出："
                '{"date":"","start":"","end":"","title":""}'
                "預設時區為 Asia/Taipei。"
            )
        },
        {
            "role": "user",
            "content": user_msg
        }
    ]

    result = call_openai(messages, temperature=0.0).strip()

    try:
        import json
        data = json.loads(result)

        return {
            "date": str(data.get("date", "")).strip(),
            "start": str(data.get("start", "")).strip(),
            "end": str(data.get("end", "")).strip(),
            "title": str(data.get("title", "")).strip()
        }
    except Exception:
        return {
            "date": "",
            "start": "",
            "end": "",
            "title": ""
        }
