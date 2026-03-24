import streamlit as st
from groq import Groq

# 頁面基本設定
st.set_page_config(page_title="My Own ChatGPT", layout="centered")

# 1. 初始化 Groq 客戶端
client = Groq(api_key=st.secrets["GROQ_API_KEY"])

# --- Step 1: 在 session_state 建立字典儲存多個對話 ---
if "chats" not in st.session_state:
    # 初始狀態：一個名為 "對話 1" 的空白清單
    st.session_state.chats = {"對話 1": []}

if "current_chat_id" not in st.session_state:
    st.session_state.current_chat_id = "對話 1"

# 2. 側邊欄設定
with st.sidebar:
    st.title("💬 對話管理")
    
    # --- Step 2: 增加「新增對話」按鈕 ---
    if st.button("＋ 新增對話", use_container_width=True):
        new_id = f"對話 {len(st.session_state.chats) + 1}"
        st.session_state.chats[new_id] = []
        st.session_state.current_chat_id = new_id
        st.rerun()

    st.divider()

    # --- Step 3: 點擊不同對話標題來切換 ---
    chat_list = list(st.session_state.chats.keys())
    # 這裡使用 radio 或是 selectbox 作為切換器，其效果最接近 ChatGPT 側邊欄
    selected_chat = st.radio(
        "歷史對話", 
        chat_list, 
        index=chat_list.index(st.session_state.current_chat_id)
    )
    
    # 如果使用者切換了選項，更新 current_chat_id
    if selected_chat != st.session_state.current_chat_id:
        st.session_state.current_chat_id = selected_chat
        st.rerun()

    st.divider()
    st.title("⚙️ 設定面板")
    selected_model = st.selectbox(
        "選擇模型",
        ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]
    )
    system_prompt = st.text_area("System Prompt", value="你是一位友善的 AI 助手。")
    temperature = st.slider("Temperature (隨機性)", 0.0, 2.0, 0.7, step=0.1)
    
    if st.button("清除「目前」對話內容"):
        st.session_state.chats[st.session_state.current_chat_id] = []
        st.rerun()

st.title(f"🚀 {st.session_state.current_chat_id}")

# 3. 取得目前對話的訊息清單 (參考字典中對應的 ID)
current_messages = st.session_state.chats[st.session_state.current_chat_id]

# 顯示目前的對話內容
for message in current_messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 4. 對話邏輯
if prompt := st.chat_input("想聊什麼？"):
    # 將訊息加入目前的對話清單中
    current_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 呼叫 API 並實作 Streaming
    with st.chat_message("assistant"):
        final_system_instruction = system_prompt + "\n【重要：請全程使用『繁體中文』回覆，禁止使用簡體字。】"
        
        # 組合歷史紀錄
        full_messages = [{"role": "system", "content": final_system_instruction}] + [
            {"role": m["role"], "content": m["content"]} for m in current_messages
        ]
        
        try:
            response = client.chat.completions.create(
                model=selected_model,
                messages=full_messages,
                temperature=temperature,
                stream=True,
            )
            
            placeholder = st.empty()
            full_response = ""
            for chunk in response:
                if chunk.choices[0].delta.content:
                    full_response += chunk.choices[0].delta.content
                    placeholder.markdown(full_response + "▌")
            placeholder.markdown(full_response)
            
            # 將 AI 回覆存入目前的對話清單
            current_messages.append({"role": "assistant", "content": full_response})
            
        except Exception as e:
            st.error(f"發生錯誤: {e}")