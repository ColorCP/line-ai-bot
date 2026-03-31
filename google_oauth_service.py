# ============================================================
# google_oauth_service.py
# ============================================================

import os
import json
import secrets

from google_auth_oauthlib.flow import Flow

from db import (
    save_oauth_state,
    get_user_id_by_oauth_state,
    delete_oauth_state,
    save_google_token
)


GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar"]


def get_google_client_config():
    """
    從環境變數讀取 Google OAuth client 設定
    Railway 上請放：
    GOOGLE_CREDENTIALS_JSON = credentials.json 的完整內容
    """
    raw = os.getenv("GOOGLE_CREDENTIALS_JSON")

    if not raw:
        raise ValueError("GOOGLE_CREDENTIALS_JSON 尚未設定")

    return json.loads(raw)


def build_google_oauth_start_url(user_id: str, base_url: str) -> str:
    """
    建立 Google OAuth 授權連結
    """
    client_config = get_google_client_config()

    state = secrets.token_urlsafe(32)
    save_oauth_state(state, user_id)

    redirect_uri = f"{base_url}/google/oauth/callback"

    flow = Flow.from_client_config(
        client_config=client_config,
        scopes=GOOGLE_SCOPES,
        state=state
    )
    flow.redirect_uri = redirect_uri

    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )

    return authorization_url


def exchange_code_and_save_token(code: str, state: str, base_url: str):
    """
    Google callback 回來後，用 code 換 token，並寫入 DB
    """
    user_id = get_user_id_by_oauth_state(state)

    if not user_id:
        raise ValueError("找不到對應的 OAuth state，可能已過期或無效")

    client_config = get_google_client_config()
    redirect_uri = f"{base_url}/google/oauth/callback"

    flow = Flow.from_client_config(
        client_config=client_config,
        scopes=GOOGLE_SCOPES,
        state=state
    )
    flow.redirect_uri = redirect_uri

    flow.fetch_token(code=code)

    creds = flow.credentials

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

    delete_oauth_state(state)

    return user_id
