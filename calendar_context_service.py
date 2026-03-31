# ============================================================
# calendar_context_service.py
# ============================================================
# 功能：
# 1. 暫存最近一次行事曆查詢結果
# 2. 提供下一輪 AI 分析使用
# 3. 只保留短期上下文（預設 30 分鐘）
#
# 注意：
# - 這一版使用記憶體暫存，不寫進 DB
# - 服務重啟後資料會消失
# - 但整體最簡單、最好上線
# ============================================================

from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

# ============================================================
# 全域記憶體快取
# key   = user_id
# value = {
#   "query_type": "...",
#   "result_text": "...",
#   "events": [...],
#   "created_at": datetime object
# }
# ============================================================
_calendar_context_store: Dict[str, Dict[str, Any]] = {}


# ============================================================
# 儲存最近一次行事曆查詢結果
# ============================================================
def save_calendar_context(
    user_id: str,
    query_type: str,
    result_text: str,
    events: List[dict]
):
    """
    儲存最近一次行事曆查詢結果

    參數：
    - user_id：LINE 使用者 ID
    - query_type：查詢類型，例如 today / this_week / upcoming_7_days
    - result_text：回給使用者的文字結果
    - events：Google Calendar events 原始資料陣列
    """
    _calendar_context_store[user_id] = {
        "query_type": query_type,
        "result_text": result_text,
        "events": events,
        "created_at": datetime.now()
    }


# ============================================================
# 取得最近一次行事曆查詢結果
# ============================================================
def get_latest_calendar_context(
    user_id: str,
    expire_minutes: int = 30
) -> Optional[Dict[str, Any]]:
    """
    取得最近一次行事曆查詢結果

    若超過 expire_minutes，視為過期，回傳 None
    """
    data = _calendar_context_store.get(user_id)

    if not data:
        return None

    created_at = data.get("created_at")
    if not created_at:
        return None

    if datetime.now() - created_at > timedelta(minutes=expire_minutes):
        _calendar_context_store.pop(user_id, None)
        return None

    return data


# ============================================================
# 清除某位使用者的行事曆上下文
# ============================================================
def clear_calendar_context(user_id: str):
    """
    清除使用者的短期行事曆上下文
    """
    _calendar_context_store.pop(user_id, None)


# ============================================================
# 判斷這一句話是否像在延續討論剛剛的行程
# ============================================================
def should_use_calendar_context(user_msg: str) -> bool:
    """
    若使用者這句話是在分析剛剛那份行程，
    就回 True，讓 AI 把最近一次行程一起納入考量
    """
    msg = user_msg.strip()

    keywords = [
        "這行程",
        "這安排",
        "這樣安排",
        "會不會太緊",
        "會不會太滿",
        "太緊",
        "太滿",
        "緊湊",
        "合理嗎",
        "有空檔嗎",
        "哪天比較空",
        "哪一天比較空",
        "哪個時間比較空",
        "排得下嗎",
        "排得開嗎",
        "要不要調整",
        "要不要改",
        "空檔",
        "行程",
        "安排"
    ]

    return any(keyword in msg for keyword in keywords)


# ============================================================
# 把 event 轉成 AI 看得懂的文字
# ============================================================
def _event_to_text(event: dict) -> str:
    """
    將 Google Calendar event 轉成簡潔文字
    """
    summary = event.get("summary", "(無標題)")

    start_raw = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date", "")
    end_raw = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date", "")

    if start_raw and end_raw:
        return f"- {start_raw} ~ {end_raw}｜{summary}"

    return f"- {summary}"


# ============================================================
# 建立要丟給 AI 的上下文文字
# ============================================================
def build_calendar_context_text(
    user_id: str,
    expire_minutes: int = 30
) -> str:
    """
    取得最近一次行事曆查詢結果，轉成一段文字，
    給 AI 在下一輪分析時使用
    """
    data = get_latest_calendar_context(user_id, expire_minutes=expire_minutes)

    if not data:
        return ""

    query_type = data.get("query_type", "")
    result_text = data.get("result_text", "")
    events = data.get("events", [])

    lines = []
    lines.append("【最近一次行事曆查詢結果】")
    lines.append(f"查詢類型：{query_type}")

    if result_text:
        lines.append("【回覆給使用者的摘要】")
        lines.append(result_text)

    if events:
        lines.append("【事件清單】")
        for event in events:
            lines.append(_event_to_text(event))

    return "\n".join(lines)
