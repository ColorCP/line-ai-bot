# ============================================================
# openai_service.py
# ============================================================
# 功能：
# 1. AI 單一入口判斷使用者要做什麼
# 2. 若是一般問答 / 搜尋 / 天氣 / 新聞 / 比較 / 查資料
#    -> 走 Responses API + web search
# 3. 若是行事曆功能
#    -> 解析成結構化資料，再交給 main.py 呼叫 calendar_service
#
# 設計理念：
# - AI 負責判斷與理解自然語言
# - 你的程式負責真的執行 Google Calendar API
# - 這樣最像真正的 AI 秘書
# ============================================================

import os
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from openai import OpenAI

# ============================================================
# OpenAI 初始化
# ============================================================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# 一般搜尋 / 問答模型
OPENAI_GENERAL_MODEL = os.getenv("OPENAI_GENERAL_MODEL", "gpt-5")

# 結構化解析模型
OPENAI_PARSE_MODEL = os.getenv("OPENAI_PARSE_MODEL", "gpt-4.1-mini")


# ============================================================
# 工具函式：安全解析 JSON
# ============================================================
def safe_json_loads(text: str, fallback: dict) -> dict:
    """
    安全解析 JSON
    若失敗，回傳 fallback
    """
    try:
        return json.loads(text)
    except Exception:
        return fallback


# ============================================================
# 工具函式：取得台灣時間現在
# ============================================================
def get_now_taipei() -> datetime:
    """
    回傳 Asia/Taipei 時區的現在時間
    """
    return datetime.now(ZoneInfo("Asia/Taipei"))


# ============================================================
# 工具函式：將 recent_messages 轉成 prompt 文字
# ============================================================
def format_recent_messages(recent_messages) -> str:
    """
    將 recent_messages 轉成可放進 prompt 的文字
    """
    if not recent_messages:
        return "（無）"

    lines = []

    for item in recent_messages[-12:]:
        role = item.get("role", "unknown")
        content = item.get("content", "")

        if role == "user":
            lines.append(f"使用者：{content}")
        else:
            lines.append(f"助理：{content}")

    return "\n".join(lines) if lines else "（無）"


# ============================================================
# AI 單一入口：判斷使用者要做什麼
# ============================================================
def parse_assistant_action(user_msg: str) -> dict:
    """
    AI 單一判斷入口

    回傳格式：
    {
      "action": "general_chat" | "google_bind" | "memory_forget" |
                "calendar_query" | "calendar_create",
      "calendar_query_type": "today" | "tomorrow" | "this_week" |
                             "next_week" | "recent" | "future",
      "date": "YYYY-MM-DD",
      "start": "HH:MM",
      "end": "HH:MM",
      "title": "",
      "reply_hint": "",
      "needs_clarification": false,
      "clarification_question": ""
    }

    設計重點：
    1. AI 先決定這句是一般聊天、綁定、清除記憶、查行事曆、還是新增行事曆
    2. 若是行事曆，就同時把所需欄位解析出來
    3. 若資訊不足，可要求補充
    """

    now = get_now_taipei()
    today_str = now.strftime("%Y-%m-%d")
    tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    day_after_tomorrow_str = (now + timedelta(days=2)).strftime("%Y-%m-%d")

    system_prompt = """
你是 AI 秘書的「動作判斷器」。
你只能輸出 JSON，不能輸出其他文字。

你要判斷使用者這句話想做什麼，並盡可能解析參數。

可用 action 只有：
- "general_chat"      -> 一般問答 / 搜尋 / 天氣 / 新聞 / 比較 / 查資料 / 閒聊
- "google_bind"       -> 綁定 Google 行事曆
- "memory_forget"     -> 清除記憶
- "calendar_query"    -> 查行事曆
- "calendar_create"   -> 新增行事曆

重要規則：
1. 問天氣、新聞、搜尋、產品比較、一般知識、旅遊、時事、聊天，一律是 general_chat
2. 「幫我看今天行程」「我這週有哪些會議」這類，是 calendar_query
3. 「明天下午三點安排與 Google 開會」這類，是 calendar_create
4. 如果是 calendar_create，請盡可能解析 date/start/end/title
5. 如果只知道開始時間但沒說結束時間，預設 end = start + 1 小時
6. 若 calendar_create 缺少必要資訊，請設 needs_clarification = true
7. calendar_query_type 只能是：
   - "today"
   - "tomorrow"
   - "this_week"
   - "next_week"
   - "recent"
   - "future"
8. 若不是 calendar_query，calendar_query_type 請給空字串
9. 若不是 calendar_create，date/start/end/title 請給空字串
10. 若不需要追問，clarification_question 給空字串

今天日期（Asia/Taipei）：
- 今天：""" + today_str + """
- 明天：""" + tomorrow_str + """
- 後天：""" + day_after_tomorrow_str + """
""".strip()

    user_prompt = f"""
請解析以下使用者輸入，並只輸出 JSON：

使用者輸入：
{user_msg}

輸出格式：
{{
  "action": "general_chat",
  "calendar_query_type": "",
  "date": "",
  "start": "",
  "end": "",
  "title": "",
  "reply_hint": "",
  "needs_clarification": false,
  "clarification_question": ""
}}
""".strip()

    fallback = {
        "action": "general_chat",
        "calendar_query_type": "",
        "date": "",
        "start": "",
        "end": "",
        "title": "",
        "reply_hint": "",
        "needs_clarification": False,
        "clarification_question": ""
    }

    try:
        response = client.responses.create(
            model=OPENAI_PARSE_MODEL,
            instructions=system_prompt,
            input=user_prompt
        )

        raw_text = (response.output_text or "").strip()
        print("parse_assistant_action raw =", raw_text)

        data = safe_json_loads(raw_text, fallback)

        action = str(data.get("action", "general_chat")).strip()
        calendar_query_type = str(data.get("calendar_query_type", "")).strip()
        date = str(data.get("date", "")).strip()
        start = str(data.get("start", "")).strip()
        end = str(data.get("end", "")).strip()
        title = str(data.get("title", "")).strip()
        reply_hint = str(data.get("reply_hint", "")).strip()
        needs_clarification = bool(data.get("needs_clarification", False))
        clarification_question = str(data.get("clarification_question", "")).strip()

        allowed_actions = {
            "general_chat",
            "google_bind",
            "memory_forget",
            "calendar_query",
            "calendar_create"
        }

        allowed_query_types = {
            "",
            "today",
            "tomorrow",
            "this_week",
            "next_week",
            "recent",
            "future"
        }

        if action not in allowed_actions:
            action = "general_chat"

        if calendar_query_type not in allowed_query_types:
            calendar_query_type = ""

        return {
            "action": action,
            "calendar_query_type": calendar_query_type,
            "date": date,
            "start": start,
            "end": end,
            "title": title,
            "reply_hint": reply_hint,
            "needs_clarification": needs_clarification,
            "clarification_question": clarification_question
        }

    except Exception as e:
        print("parse_assistant_action error =", str(e))
        return fallback


# ============================================================
# 一般聊天 / 搜尋 / 問答
# ============================================================
def call_ai_with_search(
    user_msg: str,
    profile_text: str = "",
    summary_text: str = "",
    recent_messages=None,
    calendar_context_text: str = ""
) -> str:
    """
    一般聊天主函式

    說明：
    - 使用 Responses API
    - 開啟 web search
    - 所有一般問答、天氣、新聞、查資料、旅遊、比較等都從這裡走
    """

    recent_text = format_recent_messages(recent_messages)

    system_prompt = """
你是一位貼心、自然、實用的 AI 秘書。
請用繁體中文回答。

你的工作原則：
1. 若問題需要最新資訊、即時資訊、天氣、新聞、價格、旅遊、地點、推薦、規格比較、法規更新等，請優先使用 web search。
2. 若不需要上網即可回答，則直接回答即可。
3. 回答要自然，不要像搜尋引擎拼貼。
4. 若你有使用網路資料，請在回答中自然整合資訊。
5. 不要假裝你能直接新增、刪除或修改使用者的行事曆；這些由外部程式執行。
6. 若使用者是在延續前面一份行事曆結果做討論，你可以根據 calendar_context_text 協助分析。
7. 回答以清楚、自然、實用為主。
""".strip()

    user_prompt = f"""
以下是目前可用的上下文，請根據它回答最後的使用者問題。

【使用者長期資料】
{profile_text or "（無）"}

【使用者摘要記憶】
{summary_text or "（無）"}

【最近對話】
{recent_text}

【最近一次行事曆查詢上下文】
{calendar_context_text or "（無）"}

【使用者最新問題】
{user_msg}
""".strip()

    try:
        response = client.responses.create(
            model=OPENAI_GENERAL_MODEL,
            instructions=system_prompt,
            input=user_prompt,
            tools=[
                {"type": "web_search"}
            ],
            tool_choice="auto"
        )

        answer = (response.output_text or "").strip()

        if answer:
            return answer

        return "我目前沒有整理出可回覆的內容，請你再問我一次。"

    except Exception as e:
        print("call_ai_with_search error =", str(e))
        return f"AI 呼叫失敗：{str(e)}"
