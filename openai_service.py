# ============================================================
# openai_service.py
# ============================================================
# 功能：
# 1. AI 單一入口判斷使用者要做什麼
# 2. 一般搜尋 / 問答 -> Responses API + web search
# 3. 行事曆查詢 / 建立 -> 解析成結構化資料
# 4. 記憶抽取 -> 提供給 memory_service.py 使用
# 5. 記憶摘要 -> 提供給 memory_service.py 使用
#
# 升級重點：
# 1. 支援特定日期查詢（例如：5/1 我有要去澎湖嗎）
# 2. 支援多天全天事件（例如：5/1 去澎湖三天）
# 3. 支援延續型追問（例如：下個月呢？）
# 4. 目前只支援 Google 行事曆
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
OPENAI_GENERAL_MODEL = os.getenv("OPENAI_GENERAL_MODEL", "gpt-4.1")

# 結構化解析模型
OPENAI_PARSE_MODEL = os.getenv("OPENAI_PARSE_MODEL", "gpt-4.1-mini")


# ============================================================
# 工具函式：安全解析 JSON
# ============================================================
def safe_json_loads(text: str, fallback):
    """
    安全解析 JSON
    若失敗就回傳 fallback
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
# 工具函式：清理日期字串，只保留 YYYY-MM-DD
# ============================================================
def normalize_date_string(value: str) -> str:
    """
    將模型可能回傳的日期格式統一成 YYYY-MM-DD
    例如：
    - 2026-05-01
    - 2026-05-01T00:00:00
    - 2026-05-01 00:00:00
    """
    value = (value or "").strip()

    if not value:
        return ""

    if "T" in value:
        value = value.split("T")[0].strip()

    if " " in value:
        value = value.split(" ")[0].strip()

    if len(value) >= 10:
        value = value[:10]

    return value


# ============================================================
# 工具函式：清理時間字串，只保留 HH:MM
# ============================================================
def normalize_time_string(value: str) -> str:
    """
    將模型可能回傳的時間格式統一成 HH:MM
    """
    value = (value or "").strip()

    if not value:
        return ""

    if "T" in value:
        value = value.split("T")[-1].strip()

    if " " in value:
        value = value.split(" ")[-1].strip()

    # 若有秒數，去掉秒
    parts = value.split(":")
    if len(parts) >= 2:
        hour = parts[0].strip()
        minute = parts[1].strip()

        try:
            hour_int = int(hour)
            minute_int = int(minute)

            if hour_int < 0:
                hour_int = 0
            if hour_int > 23:
                hour_int = 23

            if minute_int < 0:
                minute_int = 0
            if minute_int > 59:
                minute_int = 59

            return f"{hour_int:02d}:{minute_int:02d}"
        except Exception:
            return ""

    return ""


# ============================================================
# 工具函式：若只有開始時間，推算結束時間
# 特別處理 23:00 不能直接 +1 變成 24:00
# ============================================================
def infer_end_time(start_str: str) -> str:
    """
    根據開始時間推算結束時間
    規則：
    - 一般情況 +1 小時
    - 若開始為 23:00~23:59，則結束設成 23:59
    """
    start_str = normalize_time_string(start_str)

    if not start_str:
        return ""

    try:
        hour = int(start_str.split(":")[0])
        minute = int(start_str.split(":")[1])

        if hour == 23:
            return "23:59"

        end_dt = datetime(2000, 1, 1, hour, minute) + timedelta(hours=1)
        return end_dt.strftime("%H:%M")
    except Exception:
        return ""


# ============================================================
# AI 單一入口：判斷使用者要做什麼
# ============================================================
def parse_assistant_action(user_msg: str, calendar_context_text: str = "") -> dict:
    """
    AI 單一判斷入口

    回傳格式：
    {
      "action": "general_chat" | "google_bind" | "memory_forget" |
                "calendar_query" | "calendar_create",

      "calendar_query_type": "" | "today" | "tomorrow" | "this_week" |
                             "next_week" | "recent" | "future" |
                             "this_month" | "next_month" | "exact_date",

      "query_date": "YYYY-MM-DD",

      "date": "YYYY-MM-DD",
      "start": "HH:MM",
      "end": "HH:MM",
      "title": "",

      "all_day": false,
      "start_date": "",
      "end_date": "",

      "reply_hint": "",
      "needs_clarification": false,
      "clarification_question": ""
    }
    """
    now = get_now_taipei()
    today_str = now.strftime("%Y-%m-%d")
    tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    day_after_tomorrow_str = (now + timedelta(days=2)).strftime("%Y-%m-%d")
    current_year = now.year

    system_prompt = f"""
你是 AI 秘書的動作判斷器。
你只能輸出 JSON，不能輸出其他文字。

你要判斷使用者這句話想做什麼，並盡可能解析參數。

可用 action 只有：
- "general_chat"      -> 一般問答 / 搜尋 / 天氣 / 新聞 / 比較 / 查資料 / 閒聊
- "google_bind"       -> 綁定 Google 行事曆
- "memory_forget"     -> 清除記憶
- "calendar_query"    -> 查行事曆
- "calendar_create"   -> 新增行事曆
- "calendar_delete"   -> 刪除行事曆事件

非常重要的限制：
1. 目前系統只支援 Google 行事曆
2. 不支援 Apple 行事曆、Outlook 行事曆、iCloud 行事曆、手機內建行事曆
3. 如果使用者說「綁定行事曆」，就是綁定 Google 行事曆，不能延伸回答到其他平台

行事曆判斷規則：
4. 「幫我看今天行程」「我這週有哪些會議」「我明天下午有空嗎」「5/1 我有要去澎湖嗎」這類，是 calendar_query
5. 「明天下午三點安排與 Google 開會」「我5/1加入去澎湖三天」這類，是 calendar_create
6. 若句子很短，例如「下個月呢？」「那明天呢？」，但有提供 calendar_context_text，請優先視為延續上一輪行事曆查詢

calendar_query_type 只能是：
- ""
- "today"
- "tomorrow"
- "this_week"
- "next_week"
- "recent"
- "future"
- "this_month"
- "next_month"
- "exact_date"

行事曆查詢補充規則：
7. 若是查某一個明確日期，例如「5/1 我有要去澎湖嗎」「2026/5/1 有行程嗎」，請：
   - action = "calendar_query"
   - calendar_query_type = "exact_date"
   - query_date = 對應日期
8. 若月份日期未寫年份，例如 5/1，預設使用 {current_year} 年
9. 若不是 exact_date，query_date 請給空字串

行事曆建立補充規則：
10. 若是一般單日事件，請填：
   - date
   - start
   - end
   - title
11. 若是多天旅行 / 多天活動，例如「5/1 去澎湖三天」，請填：
   - all_day = true
   - start_date = 2026-05-01
   - end_date = 2026-05-03
   - title = 去澎湖
12. 多天事件的 end_date 代表最後一天（含當天）
13. 若只知道開始時間但沒說結束時間，請預設 end = start + 1 小時
14. 若開始時間是 23:00 左右，不可輸出 24:00，請改成 23:59
15. 若不是 calendar_create，date/start/end/title/all_day/start_date/end_date 請給空值或 false
16. 若需要追問，needs_clarification = true，並寫 clarification_question
17. 若不需要追問，clarification_question 給空字串

今天日期（Asia/Taipei）：
- 今天：{today_str}
- 明天：{tomorrow_str}
- 後天：{day_after_tomorrow_str}
""".strip()

    user_prompt = f"""
請解析以下使用者輸入，並只輸出 JSON。

【最近一次行事曆上下文】
{calendar_context_text or "（無）"}

【使用者輸入】
{user_msg}

輸出格式：
{{
  "action": "general_chat",
  "calendar_query_type": "",
  "query_date": "",
  "date": "",
  "start": "",
  "end": "",
  "title": "",
  "all_day": false,
  "start_date": "",
  "end_date": "",
  "reply_hint": "",
  "needs_clarification": false,
  "clarification_question": ""
}}
""".strip()

    fallback = {
        "action": "general_chat",
        "calendar_query_type": "",
        "query_date": "",
        "date": "",
        "start": "",
        "end": "",
        "title": "",
        "all_day": False,
        "start_date": "",
        "end_date": "",
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
        query_date = normalize_date_string(str(data.get("query_date", "")).strip())

        date = normalize_date_string(str(data.get("date", "")).strip())
        start = normalize_time_string(str(data.get("start", "")).strip())
        end = normalize_time_string(str(data.get("end", "")).strip())
        title = str(data.get("title", "")).strip()

        all_day = bool(data.get("all_day", False))
        start_date = normalize_date_string(str(data.get("start_date", "")).strip())
        end_date = normalize_date_string(str(data.get("end_date", "")).strip())

        reply_hint = str(data.get("reply_hint", "")).strip()
        needs_clarification = bool(data.get("needs_clarification", False))
        clarification_question = str(data.get("clarification_question", "")).strip()

        allowed_actions = {
            "general_chat",
            "google_bind",
            "memory_forget",
            "calendar_query",
            "calendar_create",
            "calendar_delete"
        }

        allowed_query_types = {
            "",
            "today",
            "tomorrow",
            "this_week",
            "next_week",
            "recent",
            "future",
            "this_month",
            "next_month",
            "exact_date"
        }

        if action not in allowed_actions:
            action = "general_chat"

        if calendar_query_type not in allowed_query_types:
            calendar_query_type = ""

        # 若是單日建立事件但沒有 end，幫它補
        if action == "calendar_create" and (not all_day):
            if start and not end:
                end = infer_end_time(start)

        return {
            "action": action,
            "calendar_query_type": calendar_query_type,
            "query_date": query_date,
            "date": date,
            "start": start,
            "end": end,
            "title": title,
            "all_day": all_day,
            "start_date": start_date,
            "end_date": end_date,
            "reply_hint": reply_hint,
            "needs_clarification": needs_clarification,
            "clarification_question": clarification_question
        }

    except Exception as e:
        print("parse_assistant_action error =", str(e))
        return fallback


# ============================================================
# 一般聊天 / 搜尋 / 問答（含 AI 上網搜尋）
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
    """
    recent_text = format_recent_messages(recent_messages)

    system_prompt = """
你是一位貼心、自然、實用的 AI 秘書。
請用繁體中文回答。

你的工作原則：
1. 若問題需要最新資訊、即時資訊、天氣、新聞、價格、旅遊、地點、推薦、規格比較、法規更新等，請優先使用 web search。
2. 若不需要上網即可回答，則直接回答即可。
3. 回答要自然，不要像搜尋引擎拼貼。
4. 若你有使用網路資料，請自然整合資訊。
5. 不要假裝你能直接新增、刪除或修改使用者的行事曆；這些由外部程式執行。
6. 若使用者是在延續前面一份行事曆結果做討論，你可以根據 calendar_context_text 協助分析。
7. 目前系統只支援 Google 行事曆；不要提到 Apple、Outlook、iCloud 行事曆整合。
8. 回答以清楚、自然、實用為主。
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
                {"type": "web_search_preview"}
            ]
        )

        answer = (response.output_text or "").strip()

        if answer:
            return answer

        return "我目前沒有整理出可回覆的內容，請你再問我一次。"

    except Exception as e:
        print("call_ai_with_search error =", str(e))
        return f"AI 呼叫失敗：{str(e)}"


# ============================================================
# 記憶抽取：提供給 memory_service.py 使用
# ============================================================
def extract_profile_memories_from_text(user_text: str):
    """
    從使用者輸入中抽取適合長期保存的個人資訊
    """
    system_prompt = """
你是記憶抽取器。
請從使用者輸入中，抽取適合長期保存的個人資訊。

只保留：
1. 長期穩定偏好
2. 身分背景
3. 長期計畫
4. 家庭成員 / 寵物名稱
5. 之後回答很可能有幫助的資訊

不要保留：
1. 短期情緒
2. 一次性的隨口聊天
3. 當下天氣、短期新聞、即時事件
4. 太瑣碎、沒有長期價值的內容

請只輸出 JSON 陣列，例如：
["使用者喜歡 Lexus IS", "使用者有一隻貓叫咪咪"]

如果沒有值得記住的內容，輸出：
[]
""".strip()

    fallback = []

    try:
        response = client.responses.create(
            model=OPENAI_PARSE_MODEL,
            instructions=system_prompt,
            input=user_text
        )

        raw_text = (response.output_text or "").strip()
        print("extract_profile_memories_from_text raw =", raw_text)

        data = safe_json_loads(raw_text, fallback)

        if isinstance(data, list):
            clean_items = []
            for item in data:
                text = str(item).strip()
                if text:
                    clean_items.append(text)
            return clean_items

        return fallback

    except Exception as e:
        print("extract_profile_memories_from_text error =", str(e))
        return fallback


# ============================================================
# 記憶摘要：提供給 memory_service.py 使用
# ============================================================
def summarize_messages_for_memory(messages) -> str:
    """
    將一批對話訊息摘要成較短的記憶摘要
    """
    if not messages:
        return ""

    lines = []

    for item in messages:
        role = item.get("role", "")
        content = item.get("content", "")

        if role == "user":
            lines.append(f"使用者：{content}")
        else:
            lines.append(f"助理：{content}")

    conversation_text = "\n".join(lines)

    system_prompt = """
你是對話摘要器。
請把以下對話整理成短摘要，供 AI 助理未來參考。

要求：
1. 使用繁體中文
2. 保留重要背景、需求、長期計畫、持續中的問題
3. 刪除瑣碎寒暄
4. 控制在精簡但有用的長度
""".strip()

    try:
        response = client.responses.create(
            model=OPENAI_PARSE_MODEL,
            instructions=system_prompt,
            input=conversation_text
        )

        summary = (response.output_text or "").strip()
        print("summarize_messages_for_memory raw =", summary)
        return summary

    except Exception as e:
        print("summarize_messages_for_memory error =", str(e))
        return ""


# ============================================================
# 相容舊名稱
# ============================================================
def chat_with_memory(
    user_msg: str,
    profile_text: str = "",
    summary_text: str = "",
    recent_messages=None,
    calendar_context_text: str = ""
) -> str:
    return call_ai_with_search(
        user_msg=user_msg,
        profile_text=profile_text,
        summary_text=summary_text,
        recent_messages=recent_messages,
        calendar_context_text=calendar_context_text
    )


def parse_calendar_query(user_msg: str) -> dict:
    parsed = parse_assistant_action(user_msg)
    query_type = parsed.get("calendar_query_type", "") or "today"
    return {"type": query_type}


def parse_calendar_create(user_msg: str) -> dict:
    parsed = parse_assistant_action(user_msg)
    return {
        "date": parsed.get("date", ""),
        "start": parsed.get("start", ""),
        "end": parsed.get("end", ""),
        "title": parsed.get("title", "")
    }
