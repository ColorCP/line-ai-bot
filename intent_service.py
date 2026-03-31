# ============================================================
# intent_service.py
# ============================================================
# 功能：
# 1. 用 OpenAI 判斷使用者意圖
# 2. 支援：
#    - weather_query
#    - calendar_query
#    - calendar_create
#    - google_bind
#    - memory_forget
#    - general_chat
# 3. 若 OpenAI 解析失敗，則用簡單規則當 fallback
# ============================================================

import os
import json
from openai import OpenAI

# ============================================================
# OpenAI 初始化
# ============================================================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)


# ============================================================
# fallback 規則判斷
# ============================================================
def detect_user_intent_by_rule(user_msg: str) -> str:
    """
    當 OpenAI 判斷失敗時，使用簡單規則做備援
    """
    text = user_msg.strip()

    # 清除記憶
    if any(keyword in text for keyword in ["清除記憶", "忘記我剛剛說的", "忘記剛剛", "刪除記憶"]):
        return "memory_forget"

    # 綁定 Google 行事曆
    if any(keyword in text for keyword in ["綁定行事曆", "綁定google行事曆", "連接google行事曆", "google綁定"]):
        return "google_bind"

    # 天氣
    weather_keywords = [
        "天氣", "氣溫", "溫度", "幾度", "下雨", "降雨", "weather", "forecast", "rain", "temperature"
    ]
    if any(keyword.lower() in text.lower() for keyword in weather_keywords):
        return "weather_query"

    # 查詢行事曆
    calendar_query_keywords = [
        "今天行程", "明天行程", "後天行程",
        "這週有哪些", "下週有哪些", "最近行程", "未來行程",
        "看行程", "查行程", "有哪些會議", "有哪些安排"
    ]
    if any(keyword in text for keyword in calendar_query_keywords):
        return "calendar_query"

    # 建立行事曆
    calendar_create_keywords = [
        "安排", "新增行程", "新增會議", "建立行程", "建立會議", "預約"
    ]
    if any(keyword in text for keyword in calendar_create_keywords):
        return "calendar_create"

    return "general_chat"


# ============================================================
# AI 意圖判斷
# ============================================================
def detect_user_intent(user_msg: str) -> str:
    """
    用 OpenAI 判斷使用者意圖
    回傳值只允許：
    - weather_query
    - calendar_query
    - calendar_create
    - google_bind
    - memory_forget
    - general_chat
    """

    prompt = f"""
請判斷以下這句話的使用者意圖，只能回傳 JSON，不能加任何其他文字。

可用的 intent 只有這些：
- weather_query
- calendar_query
- calendar_create
- google_bind
- memory_forget
- general_chat

判斷規則：
1. 如果是在問天氣、溫度、會不會下雨、幾度、weather，請回 weather_query
2. 如果是在查詢今天/明天/這週/下週/未來的行程、會議、安排，請回 calendar_query
3. 如果是在新增、安排、建立某個未來事件，請回 calendar_create
4. 如果是在要求綁定 Google 行事曆，請回 google_bind
5. 如果是在要求忘記、清除記憶，請回 memory_forget
6. 其他一般聊天，回 general_chat

使用者輸入：
{user_msg}

請只輸出這種格式：
{{"intent":"weather_query"}}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": "你是意圖分類器，只能輸出 JSON。"
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        content = response.choices[0].message.content.strip()
        print("detect_user_intent raw =", content)

        data = json.loads(content)
        intent = data.get("intent", "").strip()

        allowed = {
            "weather_query",
            "calendar_query",
            "calendar_create",
            "google_bind",
            "memory_forget",
            "general_chat"
        }

        if intent in allowed:
            return intent

        return detect_user_intent_by_rule(user_msg)

    except Exception as e:
        print("detect_user_intent error =", str(e))
        return detect_user_intent_by_rule(user_msg)
