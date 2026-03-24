import streamlit as st
from groq import Groq

# 頁面基本設定
st.set_page_config(page_title="My Own ChatGPT", layout="centered", page_icon="🚀")

# 1. 初始化 Groq 客戶端
client = Groq(api_key=st.secrets["GROQ_API_KEY"])

# --- 初始化 Session State (多對話與自動命名核心) ---
if "chats" not in st.session_state:
    st.session_state.chats = {"對話 1": []}

if "current_chat_id" not in st.session_state:
    st.session_state.current_chat_id = "對話 1"

# 2. 側邊欄：對話管理與參數設定
with st.sidebar:
    st.title("💬 對話管理")
    
    # 新增對話按鈕
    if st.button("＋ 新增對話", use_container_width=True):
        new_id = f"對話 {len(st.session_state.chats) + 1}"
        st.session_state.chats[new_id] = []
        st.session_state.current_chat_id = new_id
        st.rerun()

    st.divider()

    # 顯示歷史對話清單
    chat_list = list(st.session_state.chats.keys())
    # 確保選取項對應到正確的 index
    try:
        current_index = chat_list.index(st.session_state.current_chat_id)
    except ValueError:
        current_index = 0

    selected_chat = st.radio("歷史對話", chat_list, index=current_index)
    
    # 切換對話時刷新頁面
    if selected_chat != st.session_state.current_chat_id:
        st.session_state.current_chat_id = selected_chat
        st.rerun()

    st.divider()
    st.title("⚙️ 設定面板")
    selected_model = st.selectbox(
        "選擇模型",
        ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
        index=0
    )
    system_prompt = st.text_area("System Prompt", value="你是一位友善的 AI 助手。")
    temperature = st.slider("Temperature (隨機性)", 0.0, 2.0, 0.7, step=0.1)
    
    if st.button("清除「目前」對話內容"):
        st.session_state.chats[st.session_state.current_chat_id] = []
        st.rerun()

# 顯示目前對話標題
st.title(f"🚀 {st.session_state.current_chat_id}")

# 3. 取得並顯示目前對話內容
current_messages = st.session_state.chats[st.session_state.current_chat_id]

for message in current_messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 4. 對話邏輯與「自動命名」
if prompt := st.chat_input("想聊什麼？"):
    
    # --- ✨ 關鍵：自動命名邏輯 ---
    # 如果這是該對話的第一條訊息
    if len(current_messages) == 0:
        # 取前 10 個字，去除換行符號
        new_name = prompt.replace("\n", " ")[:10]
        if len(prompt) > 10:
            new_name += "..."
            
        # 避免 Key 衝突 (如果已經有同名的對話)
        if new_name in st.session_state.chats:
            new_name = f"{new_name} ({len(st.session_state.chats)})"
            
        # 執行字典 Key 置換：存入新 Key，彈出舊 Key 並刪除
        old_id = st.session_state.current_chat_id
        st.session_state.chats[new_name] = st.session_state.chats.pop(old_id)
        
        # 更新目前指向的對話 ID
        st.session_state.current_chat_id = new_name
        # 重新指向目前的訊息清單，否則會報錯
        current_messages = st.session_state.chats[new_name]

    # --- 正常的對話處理流程 ---
    current_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        final_system_instruction = system_prompt + "\n【重要：請全程使用『繁體中文』回覆。】"
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
            
            # 存入記憶
            current_messages.append({"role": "assistant", "content": full_response})
            
            # 存完之後執行一次 rerun，讓側邊欄的標題立刻更新
            st.rerun()
            
        except Exception as e:
            st.error(f"發生錯誤: {e}")