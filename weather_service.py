# ============================================================
# weather_service.py
# ============================================================
# 功能：
# 1. 使用 OpenAI 解析自然語言天氣查詢
# 2. 從句子中解析：
#    - city
#    - date_target
#    - question_type
# 3. 使用 Open-Meteo 查詢真實世界天氣
# 4. 不直接讓 OpenAI 回答天氣內容，避免亂回答
# ============================================================

import os
import json
import requests
from openai import OpenAI

# ============================================================
# OpenAI 初始化
# ============================================================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)


# ============================================================
# 天氣意圖判斷（保留簡單版本，main 目前可不一定使用）
# ============================================================
def is_weather_query(text: str) -> bool:
    """
    簡單關鍵字判斷，作為保底
    """
    keywords = [
        "天氣", "氣溫", "溫度", "幾度", "下雨", "降雨",
        "weather", "forecast", "rain", "temperature"
    ]
    text_lower = text.lower()
    return any(k.lower() in text_lower for k in keywords)


# ============================================================
# AI 解析天氣查詢
# ============================================================
def parse_weather_query(user_text: str) -> dict:
    """
    把自然語言天氣問題解析成結構化資料

    回傳格式：
    {
        "city": "東京",
        "date_target": "tomorrow",
        "question_type": "rain"
    }

    date_target 允許：
    - today
    - tomorrow
    - day_after_tomorrow

    question_type 允許：
    - general
    - rain
    - temperature
    """

    prompt = f"""
請把以下使用者的天氣問題解析成 JSON。
只能輸出 JSON，不能加其他文字。

規則：
1. city：請抓出城市名稱
2. 如果句子沒有明確城市，預設 city = "Taipei"
3. date_target 只能是：
   - "today"
   - "tomorrow"
   - "day_after_tomorrow"
4. 如果句子沒明講日期，預設 "today"
5. question_type 只能是：
   - "general"      （一般問天氣）
   - "rain"         （問會不會下雨 / 降雨）
   - "temperature"  （問幾度 / 溫度 / 熱不熱 / 冷不冷）

例子：
- 今天天氣 → {{"city":"Taipei","date_target":"today","question_type":"general"}}
- 明天東京會下雨嗎 → {{"city":"東京","date_target":"tomorrow","question_type":"rain"}}
- 巴黎現在幾度 → {{"city":"巴黎","date_target":"today","question_type":"temperature"}}
- 倫敦後天天氣如何 → {{"city":"倫敦","date_target":"day_after_tomorrow","question_type":"general"}}

使用者輸入：
{user_text}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": "你是天氣查詢解析器，只能輸出 JSON。"
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        content = response.choices[0].message.content.strip()
        print("parse_weather_query raw =", content)

        data = json.loads(content)

        city = str(data.get("city", "Taipei")).strip()
        date_target = str(data.get("date_target", "today")).strip()
        question_type = str(data.get("question_type", "general")).strip()

        if not city:
            city = "Taipei"

        if date_target not in ["today", "tomorrow", "day_after_tomorrow"]:
            date_target = "today"

        if question_type not in ["general", "rain", "temperature"]:
            question_type = "general"

        return {
            "city": city,
            "date_target": date_target,
            "question_type": question_type
        }

    except Exception as e:
        print("parse_weather_query error =", str(e))
        return {
            "city": "Taipei",
            "date_target": "today",
            "question_type": "general"
        }


# ============================================================
# 地理編碼：城市名稱轉經緯度
# ============================================================
def geocode_city(city_name: str):
    """
    用 Open-Meteo Geocoding API 查詢城市經緯度
    """
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {
        "name": city_name,
        "count": 1,
        "language": "zh",
        "format": "json"
    }

    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()

    results = data.get("results", [])
    if not results:
        return None

    item = results[0]

    return {
        "name": item.get("name", ""),
        "country": item.get("country", ""),
        "admin1": item.get("admin1", ""),
        "latitude": item.get("latitude"),
        "longitude": item.get("longitude"),
        "timezone": item.get("timezone", "auto")
    }


# ============================================================
# Open-Meteo weather_code 轉中文
# ============================================================
def weather_code_to_text(code: int) -> str:
    mapping = {
        0: "晴朗",
        1: "大致晴",
        2: "局部多雲",
        3: "陰天",
        45: "霧",
        48: "霧凇",
        51: "毛毛雨",
        53: "中度毛毛雨",
        55: "濃毛毛雨",
        56: "凍毛毛雨",
        57: "強凍毛毛雨",
        61: "小雨",
        63: "中雨",
        65: "大雨",
        66: "凍雨",
        67: "強凍雨",
        71: "小雪",
        73: "中雪",
        75: "大雪",
        77: "雪粒",
        80: "陣雨",
        81: "較強陣雨",
        82: "強烈陣雨",
        85: "陣雪",
        86: "強陣雪",
        95: "雷雨",
        96: "雷雨夾小冰雹",
        99: "雷雨夾大冰雹"
    }
    return mapping.get(code, f"天氣代碼 {code}")


# ============================================================
# 取得 forecast_days
# ============================================================
def get_forecast_days(date_target: str) -> int:
    """
    Open-Meteo 的 forecast_days 至少要包含目標天數
    """
    if date_target == "today":
        return 1
    if date_target == "tomorrow":
        return 2
    if date_target == "day_after_tomorrow":
        return 3
    return 1


# ============================================================
# 取得目標日索引
# ============================================================
def get_target_day_index(date_target: str) -> int:
    """
    today = 第 0 天
    tomorrow = 第 1 天
    day_after_tomorrow = 第 2 天
    """
    if date_target == "today":
        return 0
    if date_target == "tomorrow":
        return 1
    if date_target == "day_after_tomorrow":
        return 2
    return 0


# ============================================================
# 天氣查詢
# ============================================================
def get_weather_by_location(lat: float, lon: float, timezone: str, forecast_days: int):
    """
    查詢目前天氣 + 每日預報
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": timezone,
        "forecast_days": forecast_days
    }

    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()
    return response.json()


# ============================================================
# 日期文字轉中文
# ============================================================
def date_target_to_text(date_target: str) -> str:
    if date_target == "today":
        return "今天"
    if date_target == "tomorrow":
        return "明天"
    if date_target == "day_after_tomorrow":
        return "後天"
    return "今天"


# ============================================================
# 組出地點顯示名稱
# ============================================================
def build_display_name(location: dict) -> str:
    parts = []

    if location.get("name"):
        parts.append(location["name"])
    if location.get("admin1"):
        parts.append(location["admin1"])
    if location.get("country"):
        parts.append(location["country"])

    return " / ".join(parts)


# ============================================================
# 對外主函式：由 main.py 呼叫
# ============================================================
def get_weather_reply(user_text: str) -> str:
    """
    完整流程：
    1. AI 解析天氣問題
    2. 取得城市經緯度
    3. 查詢真實天氣
    4. 根據 question_type 回覆比較自然的文字
    """
    parsed = parse_weather_query(user_text)
    print("parsed weather =", parsed)

    city = parsed["city"]
    date_target = parsed["date_target"]
    question_type = parsed["question_type"]

    location = geocode_city(city)
    if not location:
        return f"我找不到「{city}」這個城市，請換個地名試試看。"

    forecast_days = get_forecast_days(date_target)
    target_index = get_target_day_index(date_target)

    weather_data = get_weather_by_location(
        lat=location["latitude"],
        lon=location["longitude"],
        timezone=location["timezone"],
        forecast_days=forecast_days
    )

    display_name = build_display_name(location)
    date_text = date_target_to_text(date_target)

    daily = weather_data.get("daily", {})

    weather_code_list = daily.get("weather_code", [])
    temp_max_list = daily.get("temperature_2m_max", [])
    temp_min_list = daily.get("temperature_2m_min", [])
    rain_prob_list = daily.get("precipitation_probability_max", [])

    if target_index >= len(weather_code_list):
        return "目前查不到這一天的天氣資料，請稍後再試。"

    day_weather_code = weather_code_list[target_index]
    day_temp_max = temp_max_list[target_index]
    day_temp_min = temp_min_list[target_index]
    day_rain_prob = rain_prob_list[target_index]

    weather_text = weather_code_to_text(day_weather_code)

    # --------------------------------------------------------
    # 依照問題類型，回覆不同風格
    # --------------------------------------------------------
    if question_type == "rain":
        if day_rain_prob is None:
            return (
                f"📍 {display_name}\n"
                f"{date_text}天氣：{weather_text}\n"
                f"目前查不到降雨機率。"
            )

        if day_rain_prob >= 60:
            rain_summary = "有不低的機會下雨，建議帶傘。"
        elif day_rain_prob >= 30:
            rain_summary = "有一些下雨機會，出門前可以再留意。"
        else:
            rain_summary = "看起來下雨機率不高。"

        return (
            f"📍 {display_name}\n"
            f"{date_text}降雨機率：約 {day_rain_prob}%\n"
            f"{date_text}天氣：{weather_text}\n"
            f"🌡 最高 {day_temp_max}°C / 最低 {day_temp_min}°C\n"
            f"{rain_summary}"
        )

    if question_type == "temperature":
        return (
            f"📍 {display_name}\n"
            f"{date_text}天氣：{weather_text}\n"
            f"🌡 {date_text}最高溫：約 {day_temp_max}°C\n"
            f"🌡 {date_text}最低溫：約 {day_temp_min}°C"
        )

    # general
    current = weather_data.get("current", {})
    current_temp = current.get("temperature_2m")
    apparent_temp = current.get("apparent_temperature")
    wind_speed = current.get("wind_speed_10m")

    if date_target == "today":
        return (
            f"📍 {display_name}\n"
            f"今天的天氣是：{weather_text}\n"
            f"🌡 目前溫度：{current_temp}°C\n"
            f"🤗 體感溫度：{apparent_temp}°C\n"
            f"🔺 最高溫：{day_temp_max}°C\n"
            f"🔻 最低溫：{day_temp_min}°C\n"
            f"🌧 降雨機率：{day_rain_prob}%\n"
            f"💨 風速：{wind_speed} km/h"
        )

    return (
        f"📍 {display_name}\n"
        f"{date_text}天氣：{weather_text}\n"
        f"🔺 最高溫：{day_temp_max}°C\n"
        f"🔻 最低溫：{day_temp_min}°C\n"
        f"🌧 降雨機率：{day_rain_prob}%"
    )
