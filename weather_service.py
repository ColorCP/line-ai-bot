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
    text_lower = text.lower()

    # 英文
    m = re.search(r"(?:weather|temperature)\s+in\s+([a-zA-Z\s\-]+)", text_lower)
    if m:
        return m.group(1).strip()

    # 中文
    words = ["天氣", "溫度", "幾度", "下雨", "降雨"]
    for w in words:
        text = text.replace(w, "")

    text = re.sub(r"\s+", " ", text).strip()

    return text if text else "Taipei"


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
