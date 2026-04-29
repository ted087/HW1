# Personal AI Assistant v2｜個人 AI 助手 v2

本專案是 Homework 01 的升級版本 v2。  
原本系統為基本 AI Chatbot，本次新增 Long-term Memory、Multimodal、Auto Routing between Models、Tool Use / MCP-style Tools，以及其他實用功能，例如 Google OAuth 登入、使用者 API Key 加密儲存、個人知識庫與聊天紀錄管理。

---

## 1. 專案簡介

Personal AI Assistant v2 是一個使用 Streamlit 建立的個人化 AI 助手系統。

使用者可以透過 Google 帳號登入，輸入自己的 Groq API Key，並使用 AI 助手進行聊天、檔案分析、多模態理解、長期記憶、自動模型路由，以及 MCP-style 工具呼叫。

本專案目標是將 Homework 01 的簡單聊天機器人，升級成更完整的個人 AI 助手系統。

---

## 2. 主要功能

### 2.1 Google OAuth 登入

本系統使用 Google OAuth 進行登入。

功能包含：

- 使用 Google 帳號登入
- 顯示使用者名稱、Email 與頭像
- 首次登入時自動建立使用者資料
- 使用 Google Email 區分不同使用者資料
- 不需要自行儲存使用者密碼

---

### 2.2 使用者 API Key 加密儲存

每位使用者可以在介面中輸入自己的 Groq API Key。

功能包含：

- 使用者可自行輸入 Groq API Key
- API Key 依照使用者分開儲存
- 使用 Fernet 加密技術儲存 API Key
- API Key 不會以明文方式保存
- 使用者儲存後，下次登入不需要重新輸入

---

### 2.3 Long-term Memory 長期記憶

本系統支援長期記憶功能。

功能包含：

- 自動從對話中萃取長期有用的使用者偏好
- 儲存使用者偏好、重要事項與自動記憶
- 未來回答時會參考長期記憶
- 使用者也可以手動編輯或清除長期記憶

範例：

```text
以後回答程式題時，請使用繁體中文，並且每行程式碼都加上註解。
```

系統會記住使用者偏好的回答方式，之後回答程式題時會套用這個偏好。

---

### 2.4 Multimodal 多模態輸入

本系統支援多種檔案輸入與分析。

支援格式包含：

- 圖片：png、jpg、jpeg、webp
- 音訊：mp3、wav、m4a、ogg、flac
- 影片：mp4、mov、avi、mkv、webm
- 文件：pdf、txt、md、csv、json
- 程式檔：py、cpp、java、html、css、js

處理方式：

- 圖片會送到具備視覺能力的模型分析
- 音訊會先透過 Whisper 轉成文字
- 影片會固定抽取 8 張代表影格，再交給視覺模型分析
- PDF、文字檔與程式檔會轉成文字內容加入 prompt context

注意：影片分析是基於代表影格，不是逐秒完整影片串流分析。

---

### 2.5 Auto Routing between Models 自動模型路由

本系統支援自動模型選擇。

當使用者選擇：

```text
Auto｜自動選擇模型
```

系統會根據任務類型自動選擇適合的模型。

| 任務類型 | 使用模型 |
|---|---|
| 圖片 / 多模態任務 | Llama 4 Scout Vision Model |
| 程式 / Debug 問題 | Qwen Model |
| 推理 / 分析問題 | GPT-OSS 120B |
| 翻譯 / 中文寫作 | Llama 3.3 70B |
| 簡短問題 | Llama 3.1 8B |

---

### 2.6 Tool Use / MCP-style Tools 工具使用與 MCP

本系統實作 MCP-style 工具層，模擬 MCP 的 tools/list 與 tools/call 概念。

支援功能：

- `tools/list`
- `tools/call`
- 自動工具選擇
- 手動 slash command 工具呼叫

目前可用工具：

| 工具名稱 | 功能 |
|---|---|
| calculator | 計算數學算式 |
| current_time | 取得目前系統時間 |
| word_count | 統計中文字數、英文單字數與數字數量 |

範例：

```text
請幫我計算 125*37+89
```

系統會自動判斷需要使用 calculator，並透過 MCP-style tools/call 呼叫工具回傳結果。

---

### 2.7 其他實用功能

本系統也包含以下功能：

- 聊天紀錄管理
- 新增對話
- 刪除目前對話
- 重新命名對話
- 匯出目前對話
- 個人 PDF 知識庫
- 分享 AI 回覆連結
- 重新生成回答
- 回覆好評 / 負評按鈕

---

## 3. 作業需求對照表

| 作業需求 | 本系統實作方式 |
|---|---|
| Based on Homework 01 | 由原本 AI 助手升級為 v2 |
| Long-term memory | 自動萃取使用者偏好並儲存為長期記憶 |
| Multimodal | 支援圖片、音訊、影片、PDF、文字檔與程式檔 |
| Auto routing between models | 依照任務類型自動選擇模型 |
| Tool use, MCP | 實作 MCP-style tools/list 與 tools/call |
| Any other useful functions | Google OAuth、API Key 加密、聊天紀錄、知識庫、分享功能 |
| Upgrade GitHub project to v2 | GitHub 專案更新為 v2 版本 |

---

## 4. 系統架構

```text
User 使用者
 │
 ▼
Streamlit Web UI
 │
 ├── Google OAuth Login
 ├── Chat Interface
 ├── File Upload
 └── User Settings
        │
        ├── Encrypted API Key
        ├── Long-term Memory
        └── MCP Tools
 │
 ▼
AI Orchestration Layer
 │
 ├── System Prompt
 ├── Long-term Memory Injection
 ├── Auto Model Routing
 ├── Multimodal Processing
 └── MCP-style Tool Calling
 │
 ├───────────────┬────────────────┬────────────────
 ▼               ▼                ▼
Groq Models     Local Tools       Local Storage
Llama/Qwen      Calculator        user_chats/
GPT-OSS         Current Time      user_memory/
Vision Model    Word Count        user_knowledge/
Whisper                           user_secrets/
```

---

## 5. 本機執行方式

### Step 1：下載專案

```bash
git clone your-github-repo-url
cd your-project-folder
```

### Step 2：安裝套件

```bash
pip install -r requirements.txt
```

### Step 3：建立 Streamlit Secrets

建立資料夾：

```text
.streamlit
```

在資料夾中建立：

```text
.streamlit/secrets.toml
```

並加入以下內容：

```toml
GOOGLE_CLIENT_ID = "your_google_client_id"
GOOGLE_CLIENT_SECRET = "your_google_client_secret"
APP_BASE_URL = "http://localhost:8501"
APP_ENCRYPTION_KEY = "your_fernet_encryption_key"
```

### Step 4：產生加密金鑰

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

將產生的金鑰填入：

```toml
APP_ENCRYPTION_KEY = "your_generated_key"
```

### Step 5：執行系統

```bash
streamlit run app.py
```

---

## 6. Google OAuth 設定

請到 Google Cloud Console 建立 OAuth 2.0 Client ID。

Application type 選擇：

```text
Web application
```

本機測試時，Authorized redirect URI 加入：

```text
http://localhost:8501
```

如果部署到 Streamlit Cloud，請加入：

```text
https://your-app-name.streamlit.app
```

若使用 `streamlit-oauth`，可能也需要加入：

```text
https://your-app-name.streamlit.app/component/streamlit_oauth.authorize_button
```

---

## 7. Streamlit Cloud 部署

在 Streamlit Cloud 的 Secrets 中加入：

```toml
GOOGLE_CLIENT_ID = "your_google_client_id"
GOOGLE_CLIENT_SECRET = "your_google_client_secret"
APP_BASE_URL = "https://your-app-name.streamlit.app"
APP_ENCRYPTION_KEY = "your_fernet_encryption_key"
```

設定完成後請重新啟動 App。

---

## 8. requirements.txt

範例：

```text
streamlit>=1.49
groq
pypdf
pillow
opencv-python
streamlit-oauth
requests
cryptography
```



---

## 9. 專案版本

```text
Version: v2
Based on: Homework 01
Framework: Streamlit
AI Provider: Groq
Authentication: Google OAuth
Tool Protocol: MCP-style tools/list and tools/call
```

---

## 10. 建議專案資料夾結構

```text
project/
├── app.py
├── README.md
├── requirements.txt
├── .gitignore
└── assets/
    └── system_architecture_diagram.png
```

