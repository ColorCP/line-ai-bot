# LINE AI Bot

這是使用 FastAPI + LINE Messaging API + OpenAI + Google Calendar 建立的 AI 助理專案。

## 目前階段
- 第 1 階段：專案骨架、資料庫、記憶結構

## 已建立資料表
- messages
- user_profiles
- conversation_summaries
- google_tokens

## 本機必要檔案
以下檔案不要上傳 GitHub：
- credentials.json
- token.json

## 啟動方式
```bash
uvicorn main:app --reload
