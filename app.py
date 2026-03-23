import streamlit as st
from groq import Groq

st.set_page_config(page_title="My Own ChatGPT", layout="centered")

# 1. 初始化 Groq 客戶端
client = Groq(api_key=st.secrets["GROQ_API_KEY"])

# 2. 側邊欄：實作作業要求的參數設定
with st.sidebar:
    st.title("⚙️ 設定面板")
    selected_model = st.selectbox(
        "選擇模型",
        ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
        index=0
    )
    system_prompt = st.text_area("System Prompt", value="你是一位友善的 AI 助手。")
    temperature = st.slider("Temperature (隨機性)", 0.0, 2.0, 0.7, step=0.1)
    
    if st.button("清除對話歷史"):
        st.session_state.messages = []
        st.rerun()

st.title("🚀 Your Own ChatGPT (Groq)")

# 3. 實作對話記憶 (Session State)
if "messages" not in st.session_state:
    st.session_state.messages = []

# 顯示過去的對話內容
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 4. 對話邏輯
if prompt := st.chat_input("想聊什麼？"):
    # 顯示使用者訊息
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 呼叫 API 並實作 Streaming (串流)
    with st.chat_message("assistant"):

        # --- 關鍵修正：在發送前組合繁體中文指令 ---
        final_system_instruction = system_prompt + "\n【重要：請全程使用『繁體中文』回覆，禁止使用簡體字，語氣要符合台灣習慣。】"
        # 組合完整的對話歷史給模型（包含 System Prompt）
        full_messages = [{"role": "system", "content": final_system_instruction}] + [
            {"role": m["role"], "content": m["content"]} for m in st.session_state.messages
        ]
        
        try:
            response = client.chat.completions.create(
                model=selected_model,
                messages=full_messages,
                temperature=temperature,
                stream=True,
            )
            
            # 串流輸出到畫面
            placeholder = st.empty()
            full_response = ""
            for chunk in response:
                if chunk.choices[0].delta.content:
                    full_response += chunk.choices[0].delta.content
                    placeholder.markdown(full_response + "▌")
            placeholder.markdown(full_response)
            
            # 存入記憶
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            
        except Exception as e:
            st.error(f"發生錯誤: {e}")