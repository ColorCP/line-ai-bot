# ============================================================
# openai_service.py
# ============================================================
# 這支檔案專門負責：
# 1. 呼叫 OpenAI API
# 2. 提供一般聊天回覆
# 3. 提供記憶抽取
# 4. 提供意圖判斷
# 5. 提供行事曆查詢 / 新增解析
#
# 後面如果你要換模型、改參數，
# 集中改這裡就好，不用去 main.py 到處改。
# ============================================================

import os
import json
import requests
from datetime import datetime, timedelta


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
        return json.loads(result)
    except Exception:
        return {"type": "unknown"}


def parse_calendar_create(user_msg: str) -> dict:
    """
    解析新增行事曆需求

    回傳格式：
    {
        "date": "YYYY-MM-DD",
        "start": "HH:MM",
        "end": "HH:MM",
        "title": "事件名稱"
    }

    重點：
    1. 以「現在時間」當基準，不要亂用固定年份
    2. 預設時區為 Asia/Taipei
    3. 如果使用者只說明天 / 後天，要根據今天推算正確日期
    4. 如果沒有提供結束時間，預設加 1 小時
    """

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    day_after_tomorrow_str = (now + timedelta(days=2)).strftime("%Y-%m-%d")
    current_year = now.strftime("%Y")
    current_month = now.strftime("%m")
    current_day = now.strftime("%d")

    messages = [
        {
            "role": "system",
            "content": (
                "你是一個行事曆建立需求解析器。"
                "請根據使用者輸入，解析出要建立的行程資料。"
                "你只能輸出 JSON，不能輸出其他文字。\n\n"

                "【目前基準時間】\n"
                f"今天日期是：{today_str}\n"
                f"明天日期是：{tomorrow_str}\n"
                f"後天日期是：{day_after_tomorrow_str}\n"
                f"今年是：{current_year} 年\n"
                f"今天月日是：{current_month} 月 {current_day} 日\n\n"

                "【輸出格式】\n"
                '{"date":"YYYY-MM-DD","start":"HH:MM","end":"HH:MM","title":"事件名稱"}\n\n'

                "【解析規則】\n"
                "1. '今天' 就用今天日期。\n"
                "2. '明天' 就用明天日期。\n"
                "3. '後天' 就用後天日期。\n"
                "4. 若使用者有講明確日期，例如 4月2日、2026/4/2，請轉成 YYYY-MM-DD。\n"
                "5. 若只有開始時間、沒有結束時間，end 預設為 start 後 1 小時。\n"
                "6. '下午三點' = 15:00，'上午十點' = 10:00。\n"
                "7. 若無法解析，請輸出："
                '{"date":"","start":"","end":"","title":""}\n'
                "8. 預設時區為 Asia/Taipei。\n"
                "9. 不可以自己亂用 2023、2024 等固定年份，若使用者沒特別說年份，就以目前基準時間推算。\n"
                "10. title 要精簡，抓出真正事件名稱，例如："
                "「幫我加上明天下午三點的會議，與微軟開會」"
                "可輸出 title 為「與微軟開會」。\n"
            )
        },
        {
            "role": "user",
            "content": user_msg
        }
    ]

    result = call_openai(messages, temperature=0.0).strip()
    print("parse_calendar_create raw =", result)

    try:
        data = json.loads(result)

        parsed = {
            "date": str(data.get("date", "")).strip(),
            "start": str(data.get("start", "")).strip(),
            "end": str(data.get("end", "")).strip(),
            "title": str(data.get("title", "")).strip()
        }

        print("parse_calendar_create parsed =", parsed)
        return parsed

    except Exception as e:
        print("parse_calendar_create json error =", str(e))
        return {
            "date": "",
            "start": "",
            "end": "",
            "title": ""
        }
