# ============================================================
# calendar_service.py
# ============================================================
# 功能：
# 1. 讀取使用者 Google token
# 2. 查詢 Google Calendar 事件
# 3. 支援：
#    - today / tomorrow / this_week / next_week
#    - recent / future
#    - this_month / next_month
#    - exact_date
# 4. 建立 Google Calendar 事件
# 5. 支援：
#    - 單日時間事件
#    - 多天全天事件
# ============================================================

from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from db import get_google_token_by_user_id, save_google_token

TAIPEI_TZ = ZoneInfo("Asia/Taipei")


# ============================================================
# 取得使用者 Google Credentials
# ============================================================
def get_google_credentials_by_user(user_id: str):
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

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

        scopes_text = ",".join(creds.scopes) if creds.scopes else ""
        expiry_text = creds.expiry.isoformat() if creds.expiry else None

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


# ============================================================
# 建立 Google Calendar service
# ============================================================
def get_calendar_service(user_id: str):
    creds = get_google_credentials_by_user(user_id)

    if not creds:
        raise Exception("你尚未綁定 Google 行事曆")

    service = build("calendar", "v3", credentials=creds)
    return service


# ============================================================
# 工具：日期字串轉 datetime
# ============================================================
def parse_date(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=TAIPEI_TZ)


def parse_time_str(time_str: str) -> time:
    return datetime.strptime(time_str, "%H:%M").time()


def to_iso(dt: datetime) -> str:
    return dt.isoformat()


# ============================================================
# 工具：多天全天事件的 Google end.date 要用「最後一天 + 1」
# ============================================================
def add_days(date_str: str, days: int) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    dt = dt + timedelta(days=days)
    return dt.strftime("%Y-%m-%d")


# ============================================================
# 工具：格式化事件標題
# ============================================================
def get_event_title(event: dict) -> str:
    return event.get("summary", "(無標題)")


# ============================================================
# 工具：格式化單一事件時間顯示
# ============================================================
def format_event_time(event: dict) -> str:
    start = event.get("start", {})
    end = event.get("end", {})

    # 全天事件
    if "date" in start:
        start_date = start.get("date", "")
        end_date_exclusive = end.get("date", "")

        if start_date and end_date_exclusive:
            end_inclusive = add_days(end_date_exclusive, -1)

            if start_date == end_inclusive:
                return f"{start_date}（全天）"
            return f"{start_date} ~ {end_inclusive}（全天）"

        return "（全天）"

    # 一般時間事件
    start_dt = start.get("dateTime", "")
    end_dt = end.get("dateTime", "")

    try:
        start_local = datetime.fromisoformat(start_dt).astimezone(TAIPEI_TZ)
        end_local = datetime.fromisoformat(end_dt).astimezone(TAIPEI_TZ)
        return f"{start_local.strftime('%Y-%m-%d %H:%M')} ~ {end_local.strftime('%Y-%m-%d %H:%M')}"
    except Exception:
        return "（時間格式異常）"


# ============================================================
# 工具：格式化事件清單文字
# ============================================================
def build_events_text(title: str, events: list) -> str:
    if not events:
        return f"{title}\n目前沒有行程。"

    lines = [title]

    for event in events:
        lines.append(f"- {format_event_time(event)} | {get_event_title(event)}")

    return "\n".join(lines)


# ============================================================
# 查詢某個時間區間的事件
# ============================================================
def list_events(user_id: str, time_min: datetime, time_max: datetime):
    service = get_calendar_service(user_id)

    events_result = service.events().list(
        calendarId="primary",
        timeMin=to_iso(time_min),
        timeMax=to_iso(time_max),
        singleEvents=True,
        orderBy="startTime"
    ).execute()

    return events_result.get("items", [])


# ============================================================
# 查詢 today / tomorrow / this_week / next_week / this_month ...
# ============================================================
def get_events_payload_by_query(user_id: str, query_type: str):
    now = datetime.now(TAIPEI_TZ)

    if query_type == "today":
        start_dt = datetime.combine(now.date(), time.min, tzinfo=TAIPEI_TZ)
        end_dt = start_dt + timedelta(days=1)
        title = "你今天的行事曆："

    elif query_type == "tomorrow":
        start_dt = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=TAIPEI_TZ)
        end_dt = start_dt + timedelta(days=1)
        title = "你明天的行事曆："

    elif query_type == "this_week":
        start_dt = datetime.combine((now.date() - timedelta(days=now.weekday())), time.min, tzinfo=TAIPEI_TZ)
        end_dt = start_dt + timedelta(days=7)
        title = "你這週的行事曆："

    elif query_type == "next_week":
        this_week_start = now.date() - timedelta(days=now.weekday())
        next_week_start = this_week_start + timedelta(days=7)
        start_dt = datetime.combine(next_week_start, time.min, tzinfo=TAIPEI_TZ)
        end_dt = start_dt + timedelta(days=7)
        title = "你下週的行事曆："

    elif query_type == "this_month":
        start_dt = datetime(now.year, now.month, 1, tzinfo=TAIPEI_TZ)

        if now.month == 12:
            end_dt = datetime(now.year + 1, 1, 1, tzinfo=TAIPEI_TZ)
        else:
            end_dt = datetime(now.year, now.month + 1, 1, tzinfo=TAIPEI_TZ)

        title = "你這個月的行事曆："

    elif query_type == "next_month":
        if now.month == 12:
            start_dt = datetime(now.year + 1, 1, 1, tzinfo=TAIPEI_TZ)
            end_dt = datetime(now.year + 1, 2, 1, tzinfo=TAIPEI_TZ)
        elif now.month == 11:
            start_dt = datetime(now.year, 12, 1, tzinfo=TAIPEI_TZ)
            end_dt = datetime(now.year + 1, 1, 1, tzinfo=TAIPEI_TZ)
        else:
            start_dt = datetime(now.year, now.month + 1, 1, tzinfo=TAIPEI_TZ)
            end_dt = datetime(now.year, now.month + 2, 1, tzinfo=TAIPEI_TZ)

        title = "你下個月的行事曆："

    elif query_type == "recent":
        start_dt = datetime.combine(now.date(), time.min, tzinfo=TAIPEI_TZ)
        end_dt = start_dt + timedelta(days=30)
        title = "你最近一個月的行事曆："

    elif query_type == "future":
        start_dt = datetime.combine(now.date(), time.min, tzinfo=TAIPEI_TZ)
        end_dt = start_dt + timedelta(days=90)
        title = "你未來幾個月的行事曆："

    else:
        start_dt = datetime.combine(now.date(), time.min, tzinfo=TAIPEI_TZ)
        end_dt = start_dt + timedelta(days=1)
        title = "你今天的行事曆："
        query_type = "today"

    events = list_events(user_id, start_dt, end_dt)
    text = build_events_text(title, events)

    return {
        "query_type": query_type,
        "text": text,
        "events": events
    }


# ============================================================
# 查詢某個明確日期
# ============================================================
def get_events_payload_by_exact_date(user_id: str, date_str: str):
    target_date = datetime.strptime(date_str, "%Y-%m-%d").date()

    start_dt = datetime.combine(target_date, time.min, tzinfo=TAIPEI_TZ)
    end_dt = start_dt + timedelta(days=1)

    events = list_events(user_id, start_dt, end_dt)
    text = build_events_text(f"你 {date_str} 的行事曆：", events)

    return {
        "query_type": "exact_date",
        "text": text,
        "events": events
    }


# ============================================================
# 建立 Google Calendar 事件
# 支援：
# 1. 單日時間事件
# 2. 多天全天事件
# ============================================================
def create_calendar_event(
    user_id: str,
    title: str,
    date_str: str = "",
    start_str: str = "",
    end_str: str = "",
    all_day: bool = False,
    start_date: str = "",
    end_date: str = ""
):
    service = get_calendar_service(user_id)

    # --------------------------------------------------------
    # 多天全天事件
    # --------------------------------------------------------
    if all_day:
        if not all([title, start_date, end_date]):
            raise Exception("建立全天事件缺少必要欄位")

        # Google Calendar 全天事件的 end.date 是「不包含當天」
        google_end_date = add_days(end_date, 1)

        body = {
            "summary": title,
            "start": {
                "date": start_date
            },
            "end": {
                "date": google_end_date
            }
        }

        created_event = service.events().insert(
            calendarId="primary",
            body=body
        ).execute()

        message = (
            f"已新增全天行程：\n"
            f"主題：{title}\n"
            f"開始：{start_date}\n"
            f"結束：{end_date}"
        )

        return {
            "message": message,
            "event": created_event
        }

    # --------------------------------------------------------
    # 一般單日時間事件
    # --------------------------------------------------------
    if not all([title, date_str, start_str, end_str]):
        raise Exception("建立時間事件缺少必要欄位")

    event_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    start_time = parse_time_str(start_str)
    end_time = parse_time_str(end_str)

    start_dt = datetime.combine(event_date, start_time, tzinfo=TAIPEI_TZ)
    end_dt = datetime.combine(event_date, end_time, tzinfo=TAIPEI_TZ)

    # 若 end <= start，代表可能跨日或有問題
    # 最簡單保護：至少讓它晚 1 分鐘
    if end_dt <= start_dt:
        end_dt = start_dt + timedelta(minutes=59)

    body = {
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
        body=body
    ).execute()

    message = (
        f"已新增行程：\n"
        f"主題：{title}\n"
        f"開始：{start_dt.strftime('%Y-%m-%d %H:%M')}\n"
        f"結束：{end_dt.strftime('%Y-%m-%d %H:%M')}"
    )

    return {
        "message": message,
        "event": created_event
    }

# ============================================================
# 刪除 Google 行事曆事件（用 event_id 刪除）
# ============================================================
def delete_calendar_event_by_id(user_id: str, event_id: str):
    """
    依照 event_id 刪除 Google 行事曆事件

    參數：
    - user_id: LINE 使用者 ID
    - event_id: Google Calendar 的事件 ID

    回傳格式：
    {
        "ok": True / False,
        "message": "給 LINE 顯示的訊息"
    }
    """

    try:
        # ----------------------------------------------------
        # 1️⃣ 取得 Google Calendar service（重點！）
        #    這裡直接用你原本的函式
        #    這樣就不會影響 OAuth，也會自動處理 token refresh
        # ----------------------------------------------------
        service = get_calendar_service(user_id)

        # ----------------------------------------------------
        # 2️⃣ 呼叫 Google API 刪除事件
        #    calendarId="primary" = 使用者主要行事曆
        # ----------------------------------------------------
        service.events().delete(
            calendarId="primary",
            eventId=event_id
        ).execute()

        # ----------------------------------------------------
        # 3️⃣ 回傳成功訊息
        # ----------------------------------------------------
        return {
            "ok": True,
            "message": "行程已成功刪除。"
        }

    except Exception as e:
        # ----------------------------------------------------
        # 4️⃣ 發生錯誤（例如：
        #    - event_id 不存在
        #    - token 過期
        #    - 沒有綁定
        # ----------------------------------------------------
        print("delete_calendar_event_by_id error =", str(e))

        return {
            "ok": False,
            "message": f"刪除行程失敗：{str(e)}"
        }
