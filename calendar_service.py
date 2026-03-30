# Google Calendar 模組
# 專門負責 Google Calendar OAuth、查詢行程、建立事件等功能

import os
from datetime import datetime, timedelta

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


# Google Calendar 權限範圍
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar"]


def get_calendar_service():
    """
    建立並回傳 Google Calendar API service
    會優先讀取 token.json
    若 token 無效，會重新整理或重新登入
    """
    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", GOOGLE_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "credentials.json",
                GOOGLE_SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open("token.json", "w") as token:
            token.write(creds.to_json())

    service = build("calendar", "v3", credentials=creds)
    return service


def get_today_events_text():
    """
    查詢今天的 Google Calendar 行程，並回傳可直接顯示給 LINE 的文字
    """
    service = get_calendar_service()

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


def create_calendar_event(date_str: str, start_str: str, end_str: str, title: str):
    """
    建立一筆 Google Calendar 事件
    date_str 格式：2026-03-31
    start_str 格式：14:00
    end_str 格式：15:00
    """
    service = get_calendar_service()

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

    return created_event
