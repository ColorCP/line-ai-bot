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

# Google Calendar 權限範圍
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar"
]


def get_google_client_config():
    """
    從 Railway 環境變數讀取 Google OAuth 設定 JSON

    Railway 變數名稱：
    GOOGLE_CREDENTIALS_JSON

    內容必須是完整 JSON，例如：
    {
      "web": {
        "client_id": "...",
        "project_id": "...",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": "...",
        "redirect_uris": [
          "https://你的網域/google/oauth/callback"
        ],
        "javascript_origins": [
          "https://你的網域"
        ]
      }
    }
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

    這裡會做幾件事：
    1. 產生 state（防止 CSRF）
    2. 產生 code_verifier（PKCE 流程必須）
    3. 將 state + user_id + code_verifier 存到資料庫
    4. 建立 Google OAuth URL 並回傳
    """

    # 讀取 Google OAuth client 設定
    client_config = get_google_client_config()

    # 產生隨機 state，給 OAuth 流程辨識使用者
    state = secrets.token_urlsafe(32)

    # 產生 PKCE 用的 code_verifier
    # callback 換 token 時還要再用一次
    code_verifier = secrets.token_urlsafe(64)

    # 將 state、user_id、code_verifier 存進 DB
    save_oauth_state(
        state=state,
        user_id=user_id,
        code_verifier=code_verifier
    )

    # Google callback URL
    # 必須和 Google Cloud Console 設定完全一致
    redirect_uri = f"{base_url}/google/oauth/callback"

    # 建立 OAuth Flow
    # 重點：PKCE 的 code_verifier 要放在這裡，不要放在 authorization_url()
    flow = Flow.from_client_config(
        client_config=client_config,
        scopes=GOOGLE_SCOPES,
        state=state,
        code_verifier=code_verifier
    )

    # 指定 callback URI
    flow.redirect_uri = redirect_uri

    # 產生 Google 授權網址
    # 注意：不要在這裡傳 code_verifier
    authorization_url, _ = flow.authorization_url(
        access_type="offline",          # 需要 refresh token
        include_granted_scopes="true",  # 保留已授權 scope
        prompt="consent"                # 強制顯示授權畫面，較容易取得 refresh token
    )

    # Debug 訊息
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

    # 根據 state 查回先前存的資料
    oauth_data = get_oauth_state_data(state)

    if not oauth_data:
        raise ValueError("找不到對應的 OAuth state，可能已過期或無效")

    user_id = oauth_data["user_id"]
    code_verifier = oauth_data["code_verifier"]

    # 讀取 Google OAuth client 設定
    client_config = get_google_client_config()

    # callback URL 必須和一開始產生授權網址時完全相同
    redirect_uri = f"{base_url}/google/oauth/callback"

    # 重新建立 Flow
    # 重點：這裡也要帶入同一個 code_verifier
    flow = Flow.from_client_config(
        client_config=client_config,
        scopes=GOOGLE_SCOPES,
        state=state,
        code_verifier=code_verifier
    )

    # 指定 callback URI
    flow.redirect_uri = redirect_uri

    # 用 code 換 token
    # 這裡不需要另外手動再傳 code_verifier，Flow 會使用已設定的 verifier
    flow.fetch_token(code=code)

    # 取得 Google credentials
    creds = flow.credentials

    # 整理 scopes 與到期時間
    scopes_text = ",".join(creds.scopes) if creds.scopes else ""
    expiry_text = creds.expiry.isoformat() if creds.expiry else ""

    # refresh_token 有些情況下 Google 不一定每次都回傳
    refresh_token = creds.refresh_token if creds.refresh_token else ""

    # 存進 DB
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

    # 使用完就刪除 state，避免重複使用
    delete_oauth_state(state)

    # Debug 訊息
    print("========== Google OAuth Callback Success ==========")
    print("user_id =", user_id)
    print("state =", state)
    print("redirect_uri =", redirect_uri)
    print("scopes =", scopes_text)
    print("expiry =", expiry_text)
    print("refresh_token_exists =", bool(refresh_token))
    print("===================================================")

    return user_id
