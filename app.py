import streamlit as st
from groq import Groq
import json
import os
import hashlib
import uuid
from pypdf import PdfReader
import streamlit.components.v1 as components

# ==========================================
# 1. 頁面配置與全局 CSS
# ==========================================
st.set_page_config(page_title="My Own ChatGPT Pro", layout="centered", page_icon="🚀")

# --- ✨ 強化的 CSS：確保所有內容 100% 絕對置中 ---
st.markdown("""
<style>
    /* 統一按鈕外觀 */
    div[data-testid="stHorizontalBlock"] button {
        height: 38px !important;
        width: 100% !important;
        background-color: transparent !important;
        border: 1px solid #d1d5db !important;
        border-radius: 8px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        padding: 0 !important;
        transition: background 0.2s !important;
    }
    div[data-testid="stHorizontalBlock"] button:hover {
        background-color: #1a1a1a !important;
        border-color: #999 !important;
    }
    /* 穿透 Streamlit 的內部標籤，強制內容置中 */
    div[data-testid="stHorizontalBlock"] button div, 
    div[data-testid="stHorizontalBlock"] button p {
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        margin: 0 !important;
        padding: 0 !important;
        height: 100% !important;
        width: 100% !important;
    }
</style>
""", unsafe_allow_html=True)

USER_DATA_FILE = "users.json"
CHATS_DIR = "user_chats"
KB_DIR = "user_knowledge"
SHARED_DIR = "shared_content" 

for folder in [CHATS_DIR, KB_DIR, SHARED_DIR]:
    if not os.path.exists(folder): os.makedirs(folder)

# ==========================================
# 2. 核心邏輯 (多租戶隔離與 RAG)
# ==========================================
def hash_password(password): return hashlib.sha256(str.encode(password)).hexdigest()

def load_user_data(username):
    cp, kp = os.path.join(CHATS_DIR, f"chats_{username}.json"), os.path.join(KB_DIR, f"kb_{username}.txt")
    st.session_state.chats = json.load(open(cp, "r", encoding="utf-8")) if os.path.exists(cp) else {"新對話 1": []}
    st.session_state.pdf_context = open(kp, "r", encoding="utf-8").read() if os.path.exists(kp) else ""

def save_user_chats(username, chats):
    json.dump(chats, open(os.path.join(CHATS_DIR, f"chats_{username}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=4)

def save_user_kb(username, text):
    with open(os.path.join(KB_DIR, f"kb_{username}.txt"), "w", encoding="utf-8") as f: f.write(text)

def get_pdf_text(pdf_docs):
    text = ""
    for pdf in pdf_docs:
        for page in PdfReader(pdf).pages:
            content = page.extract_text()
            if content: text += content
    return text

# ==========================================
# 3. 分享功能路由
# ==========================================
query_params = st.query_params
if "share" in query_params:
    share_id = query_params["share"]
    share_path = os.path.join(SHARED_DIR, f"{share_id}.json")
    if os.path.exists(share_path):
        with open(share_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        st.title("📢 分享的 AI 回應")
        st.info(f"來自用戶 **{data['author']}** 的對話分享")
        with st.chat_message("user"): st.markdown(data["user_query"])
        with st.chat_message("assistant"): st.markdown(data["ai_response"])
        st.divider()
        if st.button("返回系統"):
            st.query_params.clear()
            st.rerun()
        st.stop()

# ==========================================
# 4. 身份驗證
# ==========================================
if "authenticated" not in st.session_state: st.session_state.authenticated = False
if "regen_flag" not in st.session_state: st.session_state.regen_flag = False

if not st.session_state.authenticated:
    st.title("🛡️ 個人 AI 助手")
    t1, t2 = st.tabs(["登入", "註冊"])
    with t1:
        u, p = st.text_input("帳號", key="l_u"), st.text_input("密碼", type="password", key="l_p")
        if st.button("進入系統"):
            users = json.load(open(USER_DATA_FILE)) if os.path.exists(USER_DATA_FILE) else {}
            if u in users and users[u] == hash_password(p):
                st.session_state.authenticated, st.session_state.username = True, u
                load_user_data(u); st.session_state.current_chat_id = list(st.session_state.chats.keys())[0]
                st.rerun()
            else: st.error("帳號或密碼錯誤")
    with t2:
        nu, np = st.text_input("新帳號", key="n_u"), st.text_input("新密碼", type="password", key="n_p")
        if st.button("建立空間"):
            users = json.load(open(USER_DATA_FILE)) if os.path.exists(USER_DATA_FILE) else {}
            if nu in users: st.error("帳號已存在")
            else:
                users[nu] = hash_password(np); json.dump(users, open(USER_DATA_FILE, "w"))
                st.success("註冊成功")
else:
    # --- 🤖 主程式 ---
    client = Groq(api_key=st.secrets["GROQ_API_KEY"])

    with st.sidebar:
        st.write(f"👤 用戶: **{st.session_state.username}**")
        if st.button("登出"): st.session_state.authenticated = False; st.rerun()
        
        st.divider()
        st.title("📚 個人知識庫")
        files = st.file_uploader("上傳 PDF (個人隔離)", type="pdf", accept_multiple_files=True)
        if st.button("學習文件"):
            if files:
                with st.spinner("分析中..."):
                    text = get_pdf_text(files)
                    st.session_state.pdf_context = text
                    save_user_kb(st.session_state.username, text)
                    st.success("知識庫已載入並存檔！")
        
        if st.session_state.pdf_context:
            st.caption("✅ 已啟用個人知識庫")

        st.divider()
        st.title("💬 對話管理")
        if st.button("＋ 新增對話", use_container_width=True):
            nid = f"對話 {len(st.session_state.chats) + 1}"
            st.session_state.chats[nid] = []; st.session_state.current_chat_id = nid; st.rerun()
        
        with st.expander("📝 更改對話名稱"):
            new_name = st.text_input("新名稱", value=st.session_state.current_chat_id)
            if st.button("確認修改"):
                if new_name and new_name != st.session_state.current_chat_id:
                    old_id = st.session_state.current_chat_id
                    st.session_state.chats[new_name] = st.session_state.chats.pop(old_id)
                    st.session_state.current_chat_id = new_name
                    save_user_chats(st.session_state.username, st.session_state.chats)
                    st.success("修改成功！")
                    st.rerun()

        chat_list = list(st.session_state.chats.keys())
        selected = st.radio("歷史紀錄", chat_list, index=chat_list.index(st.session_state.current_chat_id))
        if selected != st.session_state.current_chat_id:
            st.session_state.current_chat_id = selected; st.rerun()

    st.title(f"🚀 {st.session_state.current_chat_id}")

    # 顯示對話與工具列
    chats = st.session_state.chats[st.session_state.current_chat_id]
    for idx, m in enumerate(chats):
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            
            if m["role"] == "assistant":
                escaped_text = m["content"].replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace('"', '\\"')
                col1, col2, col3, col4, col5, _ = st.columns([0.15, 0.12, 0.12, 0.12, 0.12, 0.4])
                
                with col1:
                    components.html(f"""
                        <style>
                            body {{ margin: 0; padding: 0; display: flex; align-items: center; justify-content: center; height: 38px; overflow: hidden; }}
                            .copy-btn {{
                                background-color: transparent; border: 1px solid #d1d5db;
                                border-radius: 8px; padding: 4px; cursor: pointer;
                                font-size: 16px; width: 100%; height: 38px;
                                display: flex; align-items: center; justify-content: center;
                                transition: background 0.2s;
                            }}
                            .copy-btn:hover {{ background-color: #1a1a1a; border-color: #999; }}
                        </style>
                        <button class="copy-btn" id="cp_btn">📋</button>
                        <script>
                            document.getElementById('cp_btn').onclick = function() {{
                                const text = "{escaped_text}";
                                const p = window.parent.document;
                                const ta = p.createElement("textarea");
                                ta.value = text; p.body.appendChild(ta); ta.select();
                                try {{ p.execCommand('copy'); }} catch (err) {{}}
                                p.body.removeChild(ta);
                            }}
                        </script>
                    """, height=38)

                with col2: st.button("👍", key=f"g_{idx}", use_container_width=True)
                with col3: st.button("👎", key=f"b_{idx}", use_container_width=True)
                
                with col4:
                    if st.button("📤", key=f"share_btn_{idx}", use_container_width=True):
                        share_uuid = uuid.uuid4().hex[:12]
                        shared_data = {
                            "author": st.session_state.username,
                            "user_query": chats[idx-1]["content"] if idx > 0 else "無標題",
                            "ai_response": m["content"]
                        }
                        with open(os.path.join(SHARED_DIR, f"{share_uuid}.json"), "w", encoding="utf-8") as f:
                            json.dump(shared_data, f, ensure_ascii=False)
                        st.session_state.last_share_url = f"http://localhost:8501/?share={share_uuid}"
                        st.toast("✅ 已生成分享連結！")

                with col5:
                    if idx == len(chats) - 1:
                        if st.button("🔄", key=f"r_{idx}", use_container_width=True):
                            st.session_state.regen_flag = True; st.rerun()

    # 顯示分享網址
    if "last_share_url" in st.session_state:
        st.success("🔗 你的分享連結：")
        st.code(st.session_state.last_share_url)
        if st.button("關閉連結"):
            del st.session_state.last_share_url; st.rerun()

    # --- ✨ AI 邏輯修正 (修復 AI 不回話的 Bug) ---
    if st.session_state.regen_flag:
        st.session_state.regen_flag = False
        prompt_to_use = chats[-2]["content"]; chats.pop()
    else:
        prompt_to_use = st.chat_input("詢問...")

    if prompt_to_use:
        # 1. 自動改名邏輯
        if len(chats) == 0:
            new_n = prompt_to_use[:10] + ("..." if len(prompt_to_use) > 10 else "")
            st.session_state.chats[new_n] = st.session_state.chats.pop(st.session_state.current_chat_id)
            st.session_state.current_chat_id = new_n; chats = st.session_state.chats[new_n]
        
        # 2. 儲存並印出使用者的話 (移除了錯誤的 st.rerun)
        if not chats or chats[-1]["content"] != prompt_to_use:
            chats.append({"role": "user", "content": prompt_to_use})
            with st.chat_message("user"):
                st.markdown(prompt_to_use)

        # 3. 呼叫 AI 並顯示回覆
        with st.chat_message("assistant"):
            sys_msg = "你是一位專業助手。請使用繁體中文。若有公式請用 LaTeX。"
            if st.session_state.pdf_context: 
                sys_msg += f"\n\n參考資料 (僅限此用戶): \n{st.session_state.pdf_context[:4000]}"
                
            res = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role":"system","content":sys_msg}]+chats, stream=True)
            full_res, ph = "", st.empty()
            for chunk in res:
                if chunk.choices[0].delta.content:
                    full_res += chunk.choices[0].delta.content; ph.markdown(full_res + "▌")
            ph.markdown(full_res)
            
            # 4. 存檔對話，最後才重新整理確保畫面穩定
            chats.append({"role": "assistant", "content": full_res})
            save_user_chats(st.session_state.username, st.session_state.chats)
            st.rerun()