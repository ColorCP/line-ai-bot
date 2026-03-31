# ============================================================
# google_oauth_service.py
# ============================================================
# 功能：
# 1. 從 Railway 環境變數讀取 Google OAuth 設定
# 2. 建立 Google OAuth 授權網址
# 3. 使用 PKCE 流程（會產生 code_verifier）
# 4. 將 state + user_id + code_verifier 存進資料庫
# 5. Google callback 回來後，用 code + code_verifier 換 token
# 6. 將 Google token 存進資料庫
# ============================================================

import os
import json
import secrets

from google_auth_oauthlib.flow import Flow

from db import (
    save_oauth_state,
    get_oauth_state_data,
    delete_oauth_state,
    save_google_token
)

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar"
]


def get_google_client_config():
    """
    從 Railway 環境變數讀取 Google OAuth 設定 JSON
    環境變數名稱：GOOGLE_CREDENTIALS_JSON
    """
    raw = os.getenv("GOOGLE_CREDENTIALS_JSON")

    if not raw:
        raise ValueError("GOOGLE_CREDENTIALS_JSON 尚未設定")

    try:
        config = json.loads(raw)
    except Exception as e:
        raise ValueError(f"GOOGLE_CREDENTIALS_JSON 格式錯誤：{str(e)}")

    if "web" not in config:
        raise ValueError("GOOGLE_CREDENTIALS_JSON 缺少 web 節點")

    return config


def build_google_oauth_start_url(user_id: str, base_url: str) -> str:
    """
    建立 Google OAuth 授權連結
    """

    client_config = get_google_client_config()

    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)

    save_oauth_state(
        state=state,
        user_id=user_id,
        code_verifier=code_verifier
    )

    redirect_uri = f"{base_url}/google/oauth/callback"

    # 重點：code_verifier 放在這裡
    flow = Flow.from_client_config(
        client_config=client_config,
        scopes=GOOGLE_SCOPES,
        state=state,
        code_verifier=code_verifier
    )

    flow.redirect_uri = redirect_uri

    # 重點：這裡不要再傳 code_verifier
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )

    print("========== Google OAuth Start ==========")
    print("user_id =", user_id)
    print("base_url =", base_url)
    print("redirect_uri =", redirect_uri)
    print("state =", state)
    print("authorization_url =", authorization_url)
    print("========================================")

    return authorization_url


def exchange_code_and_save_token(code: str, state: str, base_url: str):
    """
    Google callback 回來後：
    1. 根據 state 從 DB 找到 user_id 與 code_verifier
    2. 使用 code + code_verifier 向 Google 換 token
    3. 將 token 存進 DB
    4. 刪除已使用完的 state
    """

    oauth_data = get_oauth_state_data(state)

    if not oauth_data:
        raise ValueError("找不到對應的 OAuth state，可能已過期或無效")

    user_id = oauth_data["user_id"]
    code_verifier = oauth_data["code_verifier"]

    client_config = get_google_client_config()
    redirect_uri = f"{base_url}/google/oauth/callback"

    # 重點：同一個 code_verifier 也放在這裡
    flow = Flow.from_client_config(
        client_config=client_config,
        scopes=GOOGLE_SCOPES,
        state=state,
        code_verifier=code_verifier
    )

    flow.redirect_uri = redirect_uri

    # 重點：fetch_token 不要再手動傳 code_verifier
    flow.fetch_token(code=code)

    creds = flow.credentials

    scopes_text = ",".join(creds.scopes) if creds.scopes else ""
    expiry_text = creds.expiry.isoformat() if creds.expiry else ""
    refresh_token = creds.refresh_token if creds.refresh_token else ""

    save_google_token(
        user_id=user_id,
        access_token=creds.token,
        refresh_token=refresh_token,
        token_uri=creds.token_uri,
        client_id=creds.client_id,
        client_secret=creds.client_secret,
        scopes=scopes_text,
        expiry=expiry_text
    )

    delete_oauth_state(state)

    print("========== Google OAuth Callback Success ==========")
    print("user_id =", user_id)
    print("state =", state)
    print("redirect_uri =", redirect_uri)
    print("scopes =", scopes_text)
    print("expiry =", expiry_text)
    print("refresh_token_exists =", bool(refresh_token))
    print("===================================================")

    return user_id
