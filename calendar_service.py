# ============================================================
# calendar_service.py
# ============================================================
# 功能：
# 1. 從資料庫讀取 Google token
# 2. 查詢 Google Calendar 行程
# 3. 建立 Google Calendar 行程
# 4. 回傳可直接給 LINE 使用的文字
# ============================================================

from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from db import get_google_token

TZ = ZoneInfo("Asia/Taipei")


def _get_google_creds(user_id: str) -> Credentials:
    """
    從 DB 取出指定使用者的 Google token，建立 Credentials
    """
    token_data = get_google_token(user_id)

    if not token_data:
        raise ValueError("你還沒有綁定 Google 行事曆，請先輸入：綁定行事曆")

    scopes = []
    if token_data.get("scopes"):
        scopes = token_data["scopes"].split(",")

    return Credentials(
        token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token", ""),
        token_uri=token_data["token_uri"],
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
        scopes=scopes
    )


def _get_service(user_id: str):
    """
    建立 Google Calendar API service
    """
    creds = _get_google_creds(user_id)
    return build("calendar", "v3", credentials=creds)


def _format_event_time(dt_str: str) -> str:
    """
    把 Google 回傳的 ISO datetime 轉成台北時間字串
    """
    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00")).astimezone(TZ)
    return dt.strftime("%Y-%m-%d %H:%M")


def _format_event_item(event: dict) -> str:
    """
    把單一 event 整理成可顯示的文字
    """
    summary = event.get("summary", "(無標題)")
    start_raw = event["start"].get("dateTime") or event["start"].get("date")
    end_raw = event["end"].get("dateTime") or event["end"].get("date")

    if "dateTime" in event["start"]:
        start_text = _format_event_time(start_raw)
        end_text = _format_event_time(end_raw)
        return f"- {start_text} ~ {end_text}｜{summary}"
    else:
        return f"- 全天｜{summary}"


def get_events_by_range(user_id: str, start_dt: datetime, end_dt: datetime) -> list:
    """
    查詢指定時間範圍內的 Google Calendar events
    """
    service = _get_service(user_id)

    events_result = service.events().list(
        calendarId="primary",
        timeMin=start_dt.astimezone(TZ).isoformat(),
        timeMax=end_dt.astimezone(TZ).isoformat(),
        singleEvents=True,
        orderBy="startTime"
    ).execute()

    return events_result.get("items", [])


def get_events_text_by_query(user_id: str, query_type: str) -> str:
    """
    依 query type 回傳純文字結果
    """
    payload = get_events_payload_by_query(user_id, query_type)
    return payload["text"]


def get_events_payload_by_query(user_id: str, query_type: str) -> dict:
    """
    根據 query_type 查詢行事曆
    回傳：
    {
        "text": "...",
        "events": [...],
        "query_type": "this_week"
    }
    """
    now = datetime.now(TZ)

    if query_type == "today":
        start_dt = datetime.combine(now.date(), time.min, tzinfo=TZ)
        end_dt = datetime.combine(now.date(), time.max, tzinfo=TZ)
        title = "你今天的行程："

    elif query_type == "tomorrow":
        target_date = now.date() + timedelta(days=1)
        start_dt = datetime.combine(target_date, time.min, tzinfo=TZ)
        end_dt = datetime.combine(target_date, time.max, tzinfo=TZ)
        title = "你明天的行程："

    elif query_type == "this_week":
        monday = now.date() - timedelta(days=now.weekday())
        sunday = monday + timedelta(days=6)
        start_dt = datetime.combine(monday, time.min, tzinfo=TZ)
        end_dt = datetime.combine(sunday, time.max, tzinfo=TZ)
        title = "你這週的行程："

    elif query_type == "next_week":
        this_monday = now.date() - timedelta(days=now.weekday())
        next_monday = this_monday + timedelta(days=7)
        next_sunday = next_monday + timedelta(days=6)
        start_dt = datetime.combine(next_monday, time.min, tzinfo=TZ)
        end_dt = datetime.combine(next_sunday, time.max, tzinfo=TZ)
        title = "你下週的行程："

    elif query_type == "upcoming_7_days":
        start_dt = now
        end_dt = now + timedelta(days=7)
        title = "你近期 7 天的行程："

    elif query_type == "upcoming_30_days":
        start_dt = now
        end_dt = now + timedelta(days=30)
        title = "你未來 30 天的行程："

    else:
        start_dt = datetime.combine(now.date(), time.min, tzinfo=TZ)
        end_dt = datetime.combine(now.date(), time.max, tzinfo=TZ)
        title = "你今天的行程："
        query_type = "today"

    events = get_events_by_range(user_id, start_dt, end_dt)

    if not events:
        text = f"{title}\n目前沒有行程。"
        return {
            "text": text,
            "events": [],
            "query_type": query_type
        }

    lines = [title]
    for event in events:
        lines.append(_format_event_item(event))

    text = "\n".join(lines)

    return {
        "text": text,
        "events": events,
        "query_type": query_type
    }


def get_today_events_text(user_id: str) -> str:
    """
    保留舊介面，方便相容
    """
    return get_events_text_by_query(user_id, "today")


def create_calendar_event(user_id: str, date_str: str, start_str: str, end_str: str, title: str) -> dict:
    """
    建立 Google Calendar 行程
    並回傳完整結果，讓 LINE 可以顯示主題 / 開始 / 結束時間
    """
    service = _get_service(user_id)

    start_dt = datetime.fromisoformat(f"{date_str}T{start_str}:00").replace(tzinfo=TZ)
    end_dt = datetime.fromisoformat(f"{date_str}T{end_str}:00").replace(tzinfo=TZ)

    event_body = {
        "summary": title,
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": "Asia/Taipei"
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": "Asia/Taipei"
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {
                    "method": "popup",
                    "minutes": 10
                }
            ]
        }
    }

    created_event = service.events().insert(
        calendarId="primary",
        body=event_body
    ).execute()

    created_summary = created_event.get("summary", title)
    created_start = created_event["start"].get("dateTime", "")
    created_end = created_event["end"].get("dateTime", "")

    start_text = _format_event_time(created_start)
    end_text = _format_event_time(created_end)

    message = (
        "已新增行程：\n"
        f"主題：{created_summary}\n"
        f"開始：{start_text}\n"
        f"結束：{end_text}"
    )

    return {
        "success": True,
        "message": message,
        "event": created_event
    }
