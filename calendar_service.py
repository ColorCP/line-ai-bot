# ============================================================
# calendar_service.py
# ============================================================

from datetime import datetime, timedelta

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from db import get_google_token_by_user_id, save_google_token


def get_google_credentials_by_user(user_id: str):
    """
    依 user_id 從 DB 取得 Google Credentials
    """
    token_data = get_google_token_by_user_id(user_id)

    if not token_data:
        return None

    scopes = token_data["scopes"].split(",") if token_data["scopes"] else []

    creds = Credentials(
        token=token_data["access_token"],
        refresh_token=token_data["refresh_token"],
        token_uri=token_data["token_uri"],
        client_id=token_data["client_id"],
        client_secret=token_data["client_secret"],
        scopes=scopes
    )

    # 如過期則自動 refresh，並回寫 DB
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

        scopes_text = ",".join(creds.scopes) if creds.scopes else ""
        expiry_text = creds.expiry.isoformat() if creds.expiry else ""

        save_google_token(
            user_id=user_id,
            access_token=creds.token,
            refresh_token=creds.refresh_token,
            token_uri=creds.token_uri,
            client_id=creds.client_id,
            client_secret=creds.client_secret,
            scopes=scopes_text,
            expiry=expiry_text
        )

    return creds


def get_calendar_service_by_user(user_id: str):
    creds = get_google_credentials_by_user(user_id)

    if not creds:
        return None

    service = build("calendar", "v3", credentials=creds)
    return service


def get_today_events_text(user_id: str):
    service = get_calendar_service_by_user(user_id)

    if not service:
        return "你還沒有綁定 Google 行事曆，請先輸入：我要綁定 Google 行事曆"

    now = datetime.now().astimezone()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    events_result = service.events().list(
        calendarId="primary",
        timeMin=start_of_day.isoformat(),
        timeMax=end_of_day.isoformat(),
        singleEvents=True,
        orderBy="startTime"
    ).execute()

    events = events_result.get("items", [])

    if not events:
        return "你今天沒有行程。"

    lines = ["你今天的行程："]

    for event in events:
        start = event["start"].get("dateTime", event["start"].get("date"))
        title = event.get("summary", "無標題")
        lines.append(f"- {start} | {title}")

    return "\n".join(lines)


def create_calendar_event(user_id: str, date_str: str, start_str: str, end_str: str, title: str):
    service = get_calendar_service_by_user(user_id)

    if not service:
        return {
            "success": False,
            "message": "你還沒有綁定 Google 行事曆，請先輸入：我要綁定 Google 行事曆"
        }

    timezone = "Asia/Taipei"

    start_dt = datetime.fromisoformat(f"{date_str}T{start_str}:00+08:00")
    end_dt = datetime.fromisoformat(f"{date_str}T{end_str}:00+08:00")

    event = {
        "summary": title,
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": timezone
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": timezone
        }
    }

    created_event = service.events().insert(
        calendarId="primary",
        body=event
    ).execute()

    return {
        "success": True,
        "message": f"已新增行程：{title}",
        "event_link": created_event.get("htmlLink", "")
    }
