import requests
import re

# ============================================================
# 判斷是否為天氣查詢
# ============================================================

def is_weather_query(text: str) -> bool:
    keywords = [
        "天氣", "氣溫", "溫度", "幾度", "下雨",
        "降雨", "weather", "forecast", "rain", "temperature"
    ]
    text_lower = text.lower()
    return any(k.lower() in text_lower for k in keywords)


# ============================================================
# 抓城市
# ============================================================

def extract_city_from_text(text: str) -> str:
    """
    強化版城市解析：

    規則：
    1. 如果句子只有「今天天氣 / 天氣如何」→ 預設 Taipei
    2. 有明確城市 → 抓城市
    3. 過濾時間詞（今天/明天/後天）
    """

    text = text.strip()

    # --------------------------------------------------
    # 1️⃣ 特殊情境：沒有城市 → 預設 Taipei
    # --------------------------------------------------
    pure_weather_patterns = [
        "今天天氣",
        "天氣如何",
        "現在天氣",
        "今天會下雨嗎",
        "會下雨嗎",
        "天氣",
    ]

    if text in pure_weather_patterns:
        return "Taipei"

    # --------------------------------------------------
    # 2️⃣ 移除時間詞
    # --------------------------------------------------
    time_words = ["今天", "明天", "後天", "現在", "目前"]
    for word in time_words:
        text = text.replace(word, "")

    # --------------------------------------------------
    # 3️⃣ 移除天氣相關詞
    # --------------------------------------------------
    weather_words = ["天氣", "氣溫", "溫度", "幾度", "下雨", "降雨"]
    for word in weather_words:
        text = text.replace(word, "")

    # --------------------------------------------------
    # 4️⃣ 移除語氣詞
    # --------------------------------------------------
    filler_words = ["請問", "一下", "會不會", "如何", "多少", "嗎"]
    for word in filler_words:
        text = text.replace(word, "")

    # --------------------------------------------------
    # 5️⃣ 清理
    # --------------------------------------------------
    text = text.strip()

    # --------------------------------------------------
    # 6️⃣ 如果最後是空 → 預設 Taipei
    # --------------------------------------------------
    if not text:
        return "Taipei"

    return text


# ============================================================
# Geocode
# ============================================================

def geocode_city(city_name: str):
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {
        "name": city_name,
        "count": 1,
        "language": "zh",
        "format": "json"
    }

    r = requests.get(url, params=params)
    data = r.json()

    if "results" not in data:
        return None

    item = data["results"][0]
    return {
        "name": item["name"],
        "lat": item["latitude"],
        "lon": item["longitude"],
        "timezone": item.get("timezone", "auto")
    }


# ============================================================
# 天氣查詢
# ============================================================

def get_weather(lat, lon, timezone="auto"):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min",
        "timezone": timezone,
        "forecast_days": 1
    }

    r = requests.get(url, params=params)
    return r.json()


# ============================================================
# 天氣 code 轉文字
# ============================================================

def weather_code_to_text(code):
    mapping = {
        0: "晴朗",
        1: "多雲",
        2: "陰天",
        61: "小雨",
        63: "中雨",
        65: "大雨"
    }
    return mapping.get(code, "未知天氣")


# ============================================================
# 對外主函式（最重要）
# ============================================================

def get_weather_reply(user_text: str) -> str:
    city = extract_city_from_text(user_text)

    loc = geocode_city(city)
    if not loc:
        return f"找不到 {city}"

    data = get_weather(loc["lat"], loc["lon"], loc["timezone"])

    current = data["current"]
    daily = data["daily"]

    weather = weather_code_to_text(current["weather_code"])

    return (
        f"{loc['name']} 天氣\n"
        f"🌤 {weather}\n"
        f"🌡 {current['temperature_2m']}°C\n"
        f"⬆ {daily['temperature_2m_max'][0]}°C\n"
        f"⬇ {daily['temperature_2m_min'][0]}°C"
    )
