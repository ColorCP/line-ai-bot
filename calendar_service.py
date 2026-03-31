# ============================================================
# calendar_service.py
# ============================================================

from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from db import get_google_token


TZ = ZoneInfo("Asia/Taipei")


def _get_google_creds(user_id: str) -> Credentials:
    token_data = get_google_token(user_id)

    if not token_data:
        raise ValueError("你還沒有綁定 Google 行事曆，請先綁定。")

    return Credentials(
        token=token_data["access_token"],
        refresh_token=token_data.get("refresh_token", ""),
        token_uri=token_data["token_uri"],
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
        scopes=token_data["scopes"].split(",") if token_data.get("scopes") else []
    )


def _get_service(user_id: str):
    creds = _get_google_creds(user_id)
    return build("calendar", "v3", credentials=creds)


def _format_event_time(dt_str: str) -> str:
    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00")).astimezone(TZ)
    return dt.strftime("%Y-%m-%d %H:%M")


def _format_event_item(event: dict) -> str:
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

    events = get_events_by_range(user_id, start_dt, end_dt)

    if not events:
        return f"{title}\n目前沒有行程。"

    lines = [title]
    for event in events:
        lines.append(_format_event_item(event))

    return "\n".join(lines)


def get_today_events_text(user_id: str) -> str:
    return get_events_text_by_query(user_id, "today")


def create_calendar_event(user_id: str, date_str: str, start_str: str, end_str: str, title: str) -> dict:
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
