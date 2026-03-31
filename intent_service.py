# ============================================================
# intent_service.py
# ============================================================
# 這支檔案負責：
# 1. 判斷使用者訊息意圖
# 2. 將意圖分類結果提供給 main.py 使用
# ============================================================

from openai_service import classify_intent


def detect_user_intent(user_msg: str) -> str:
    """
    回傳使用者意圖字串
    """
    return classify_intent(user_msg)
