# 🚀 My Own ChatGPT Pro

這是一個基於 Streamlit 與 Groq API 開發的全功能 AI 聊天助手。
本專案不僅實作了基本的 LLM 對話功能，還達到了**產品級 (Production-level)** 的系統設計，包含多租戶資料隔離、PDF 知識庫 (RAG) 整合、以及精美且像素級對齊的 UI 互動工具列。

## ✨ 核心功能 (Key Features)

* **🔐 多租戶系統與資料隔離 (Multi-tenant Isolation)**
  * 完整的註冊與登入系統 (密碼經過 SHA-256 雜湊加密)。
  * 每個使用者的「對話紀錄」與「知識庫檔案」皆在伺服器端實體隔離，互不干涉。
* **📚 個人知識庫 RAG (Retrieval-Augmented Generation)**
  * 支援上傳 PDF 講義或文件，AI 能夠根據使用者專屬的文件內容進行精準回答。
* **⚙️ AI 專業設定面板 (Full Control)**
  * **模型切換**：支援切換 Llama 3.3, 3.1 或 Mixtral 等多種高效能模型。
  * **自訂 System Prompt**：可即時修改 AI 的角色設定與回覆指令。
  * **API 參數調整**：支援透過 Slider 調整 Temperature (創造力) 以符合不同使用情境。
* **💬 專業對話管理**
  * **自動命名**：根據對話第一句話自動生成標題。
  * **手動管理**：支援新增對話、刪除對話與手動更改對話名稱。
* **🛠️ 像素級對齊的互動工具列 (Enhanced UX)**
  * **📋 完美複製**：一鍵複製 AI 回覆，點擊後圖示會變換為 ✅ 提供視覺回饋。
  * **👍/👎 回饋系統**：點擊後提供 Toast 氣泡提示，強化互動感。
  * **📤 公開網址分享**：自動偵測環境網址，生成獨立 UUID 連結，免登入即可分享對話。
  * **🔄 重新生成**：退回上一層邏輯，要求 AI 重新回答。
* **📐 專業格式渲染**
  * 完美渲染 Markdown 程式碼區塊、表格，以及 LaTeX 數學公式。

## 📂 專案架構說明

* `users.json`: 儲存使用者帳號與雜湊密碼。
* `user_chats/`: 存放每位使用者的對話歷史 (`.json`)。
* `user_knowledge/`: 存放每位使用者的 PDF 知識庫解析文字 (`.txt`)。
* `shared_content/`: 存放使用者產生的公開分享內容 (`.json`)。

## 🚀 快速安裝與啟動

### Step 1: 複製專案與安裝依賴套件
```bash
git clone [https://github.com/你的帳號/你的專案名稱.git](https://github.com/你的帳號/你的專案名稱.git)
cd 你的專案名稱
pip install -r requirements.txt
```

### Step 2: 設定環境變數 (API Key)
請在專案根目錄下建立 .streamlit/secrets.toml 檔案，並填入你的 Groq API 金鑰：
```Ini, TOML
GROQ_API_KEY = "你的_GROQ_API_KEY"
```

### Step 3: 啟動應用程式
```bash
streamlit run app.py
```

## ⚠️ 佈署注意事項 (Deployment)

本程式已內建 「自動環境偵測」 邏輯，當你將專案佈署到 Streamlit Community Cloud 時，系統會自動將分享連結由 localhost 轉向你的 `http://xxx.streamlit.app`。