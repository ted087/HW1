import streamlit as st
from groq import Groq
import json
import os
import hashlib
import uuid
from pypdf import PdfReader
import streamlit.components.v1 as components
import base64
from PIL import Image
import datetime
import re

# ==========================================
# 1. 頁面配置與全局 CSS
# ==========================================
st.set_page_config(page_title="My Own ChatGPT Pro", layout="centered", page_icon="🚀")

# --- ✨ 強化 CSS：確保所有內容 100% 絕對置中與外觀統一 ---
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
    /* 穿透 Streamlit 標籤強制內容置中 */
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
MEMORY_DIR = "user_memory"

for folder in [CHATS_DIR, KB_DIR, SHARED_DIR, MEMORY_DIR]:
    if not os.path.exists(folder):
        os.makedirs(folder)

# ==========================================
# 2. 核心邏輯
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

def load_user_memory(username):
    memory_path = os.path.join(MEMORY_DIR, f"memory_{username}.json")
    if os.path.exists(memory_path):
        with open(memory_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "profile": "",
        "preferences": [],
        "important_notes": []
    }

def save_user_memory(username, memory):
    memory_path = os.path.join(MEMORY_DIR, f"memory_{username}.json")
    with open(memory_path, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=4)


def get_pdf_text(pdf_docs):
    text = ""
    for pdf in pdf_docs:
        for page in PdfReader(pdf).pages:
            content = page.extract_text()
            if content: text += content
    return text

def route_model(prompt, has_image=False):
    text = prompt.lower()

    if has_image:
        return "meta-llama/llama-4-scout-17b-16e-instruct"

    code_keywords = [
        "code", "python", "c++", "java", "bug", "錯誤", "程式", "演算法",
        "debug", "streamlit", "github", "api"
    ]

    reasoning_keywords = [
        "推理", "分析", "比較", "證明", "為什麼", "詳細解釋",
        "step by step", "邏輯", "規劃"
    ]

    chinese_keywords = [
        "翻譯", "中文", "英文", "作文", "報告", "簡報", "講稿"
    ]

    if any(k in text for k in code_keywords):
        return "qwen/qwen3-32b"

    if any(k in text for k in reasoning_keywords):
        return "openai/gpt-oss-120b"

    if any(k in text for k in chinese_keywords):
        return "llama-3.3-70b-versatile"

    if len(prompt) < 80:
        return "llama-3.1-8b-instant"

    return "llama-3.3-70b-versatile"

def image_to_data_url(uploaded_file):
    image_bytes = uploaded_file.getvalue()
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    mime_type = uploaded_file.type
    return f"data:{mime_type};base64,{encoded}"

def calculator_tool(expression):
    try:
        # 只允許安全字元，避免執行危險程式碼
        if not re.match(r"^[0-9+\-*/(). %]+$", expression):
            return "計算式包含不允許的字元。"
        return str(eval(expression))
    except Exception as e:
        return f"計算失敗：{e}"

def time_tool():
    now = datetime.datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")

def word_count_tool(text):
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    english_words = len(re.findall(r"[A-Za-z]+", text))
    numbers = len(re.findall(r"\d+", text))
    return f"中文字數：{chinese_chars}，英文單字數：{english_words}，數字數量：{numbers}"

def run_local_tool(prompt):
    text = prompt.strip()

    if text.startswith("/calc"):
        expression = text.replace("/calc", "", 1).strip()
        return calculator_tool(expression)

    if text.startswith("/time"):
        return time_tool()

    if text.startswith("/count"):
        content = text.replace("/count", "", 1).strip()
        return word_count_tool(content)

    return None


# ==========================================
# 3. 分享功能路由
# ==========================================
query_params = st.query_params
if "share" in query_params:
    share_id = query_params["share"]
    share_path = os.path.join(SHARED_DIR, f"{share_id}.json")
    if os.path.exists(share_path):
        with open(share_path, "r", encoding="utf-8") as f: data = json.load(f)
        st.title("📢 分享的 AI 回應")
        st.info(f"來自用戶 **{data['author']}** 的對話分享")
        with st.chat_message("user"): st.markdown(data["user_query"])
        with st.chat_message("assistant"): st.markdown(data["ai_response"])
        st.divider()
        if st.button("返回系統"): st.query_params.clear(); st.rerun()
        st.stop()

# ==========================================
# 4. 身份驗證與對話管理
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
                load_user_data(u)
                st.session_state.memory = load_user_memory(u)
                st.session_state.current_chat_id = list(st.session_state.chats.keys())[0]   
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
    # --- 🤖 初始化 AI ---
    client = Groq(api_key=st.secrets["GROQ_API_KEY"])

    with st.sidebar:
        st.write(f"👤 用戶: **{st.session_state.username}**")
        if st.button("登出"): st.session_state.authenticated = False; st.rerun()
        
        st.divider(); st.title("📚 個人知識庫")
        files = st.file_uploader("上傳 PDF (隔離保護)", type="pdf", accept_multiple_files=True)
        if st.button("學習文件"):
            if files:
                with st.spinner("分析中..."):
                    text = get_pdf_text(files)
                    st.session_state.pdf_context = text; save_user_kb(st.session_state.username, text)
                    st.success("知識庫已載入！")
        
        current_chat_text = "\n\n".join(
            [f"{m['role'].upper()}:\n{m['content']}" for m in st.session_state.chats[st.session_state.current_chat_id]]
        )

        st.download_button(
            label="⬇️ 匯出目前對話",
            data=current_chat_text,
            file_name=f"{st.session_state.current_chat_id}.txt",
            mime="text/plain",
            use_container_width=True
        )


        if st.session_state.pdf_context: st.caption("✅ 已啟用個人知識庫")

        st.divider()
        st.title("🧠 長期記憶")

        if "memory" not in st.session_state:
            st.session_state.memory = load_user_memory(st.session_state.username)

        memory_profile = st.text_area(
            "使用者固定資訊 / 偏好",
            value=st.session_state.memory.get("profile", ""),
            height=100,
            placeholder="例如：我希望回答使用繁體中文、程式碼要加註解、回答要適合初學者。"
        )

        if st.button("💾 儲存長期記憶", use_container_width=True):
            st.session_state.memory["profile"] = memory_profile
            save_user_memory(st.session_state.username, st.session_state.memory)
            st.success("長期記憶已儲存！")

        if st.button("🧹 清除長期記憶", use_container_width=True):
            st.session_state.memory = {
                "profile": "",
                "preferences": [],
                "important_notes": []
            }
            save_user_memory(st.session_state.username, st.session_state.memory)
            st.warning("長期記憶已清除！")



        st.divider(); st.title("💬 對話管理")
        
        # 新增對話按鈕
        if st.button("＋ 新增對話", use_container_width=True):
            nid = f"對話 {len(st.session_state.chats) + 1}"
            st.session_state.chats[nid] = []; st.session_state.current_chat_id = nid; st.rerun()
        
        # ✨ 新增：刪除對話功能 ✨
        if st.button("🗑️ 刪除目前對話", use_container_width=True):
            if len(st.session_state.chats) > 1:
                target_id = st.session_state.current_chat_id
                del st.session_state.chats[target_id]
                st.session_state.current_chat_id = list(st.session_state.chats.keys())[0]
                save_user_chats(st.session_state.username, st.session_state.chats)
                st.toast(f"✅ 已刪除對話：{target_id}")
                st.rerun()
            else:
                # 只有一個對話時，清空內容而非刪除 key
                st.session_state.chats[st.session_state.current_chat_id] = []
                save_user_chats(st.session_state.username, st.session_state.chats)
                st.toast("✅ 已清空目前對話 (至少需保留一個對話視窗)")
                st.rerun()

        with st.expander("📝 更改對話名稱"):
            new_name = st.text_input("新名稱", value=st.session_state.current_chat_id)
            if st.button("確認修改"):
                old_id = st.session_state.current_chat_id
                st.session_state.chats[new_name] = st.session_state.chats.pop(old_id)
                st.session_state.current_chat_id = new_name
                save_user_chats(st.session_state.username, st.session_state.chats); st.rerun()

        chat_list = list(st.session_state.chats.keys())
        selected = st.radio("歷史紀錄", chat_list, index=chat_list.index(st.session_state.current_chat_id))
        if selected != st.session_state.current_chat_id:
            st.session_state.current_chat_id = selected; st.rerun()

        # --- ⚙️ 設定面板 (含自訂 System Prompt) ---
        st.divider(); st.title("⚙️ 設定面板")
        model_options = {
            "Llama 3.3 70B｜高品質回答": "llama-3.3-70b-versatile",
            "Llama 3.1 8B｜快速便宜": "llama-3.1-8b-instant",
            "GPT-OSS 120B｜推理能力強": "openai/gpt-oss-120b",
            "GPT-OSS 20B｜速度快": "openai/gpt-oss-20b",
            "Qwen 3 32B｜中文/程式": "qwen/qwen3-32b",
            "Kimi K2｜長文/程式": "moonshotai/kimi-k2-instruct-0905",
        }

        model_name = st.selectbox("選擇模型", list(model_options.keys()))
        sel_model = model_options[model_name]
        custom_sys = st.text_area("自訂 System Prompt", value="你是一位專業助手。請使用繁體中文。若有公式請用 LaTeX。", height=100)
        temp_val = st.slider("創造力 (Temperature)", 0.0, 2.0, 0.7, step=0.1)
        top_p = st.slider("Top-p（回答多樣性）", 0.0, 1.0, 1.0, step=0.05)
        max_tokens = st.slider("最大回覆長度", 256, 4096, 1024, step=256)

    st.title(f"🚀 {st.session_state.current_chat_id}")

    st.divider()
    st.title("🖼️ Multimodal 圖片理解")

    uploaded_image = st.file_uploader(
        "上傳圖片讓 AI 分析",
        type=["png", "jpg", "jpeg"],
        key="vision_image"
    )

    if uploaded_image:
        st.image(uploaded_image, caption="已上傳圖片", use_container_width=True)

    # --- 顯示對話內容 ---
    chats = st.session_state.chats[st.session_state.current_chat_id]
    for idx, m in enumerate(chats):
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            
            if m["role"] == "assistant":
                escaped_text = m["content"].replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace('"', '\\"')
                col1, col2, col3, col4, col5, _ = st.columns([0.15, 0.12, 0.12, 0.12, 0.12, 0.4])
                
                with col1: # 複製 (含 ✅ 特效)
                    components.html(f"""
                        <style>
                            body {{ margin: 0; display: flex; align-items: center; justify-content: center; height: 38px; overflow: hidden; }}
                            .btn {{ background: transparent; border: 1px solid #d1d5db; border-radius: 8px; cursor: pointer; font-size: 16px; width: 100%; height: 38px; display: flex; align-items: center; justify-content: center; transition: 0.2s; }}
                            .btn:hover {{ background-color: #1a1a1a; border-color: #999; }}
                        </style>
                        <button class="btn" id="cp_btn" title="複製回覆">📋</button>
                        <script>
                            document.getElementById('cp_btn').onclick = function() {{
                                const ta = window.parent.document.createElement("textarea");
                                ta.value = "{escaped_text}"; window.parent.document.body.appendChild(ta); ta.select();
                                try {{ 
                                    window.parent.document.execCommand('copy'); 
                                    const btn = document.getElementById('cp_btn');
                                    btn.innerHTML = '✅';
                                    setTimeout(() => {{ btn.innerHTML = '📋'; }}, 2000);
                                }} catch (err) {{}}
                                window.parent.document.body.removeChild(ta);
                            }}
                        </script>
                    """, height=38)

                with col2: # 好評回饋
                    if st.button("👍", key=f"g_{idx}", help="回應良好", use_container_width=True): st.toast("✅ 感謝您的好評！")
                with col3: # 負評回饋
                    if st.button("👎", key=f"b_{idx}", help="回應不佳", use_container_width=True): st.toast("✅ 收到！我們會改進。")
                with col4: # 分享功能
                    if st.button("📤", key=f"share_btn_{idx}", help="生成分享連結", use_container_width=True):
                        share_uuid = uuid.uuid4().hex[:12]
                        shared_data = {"author": st.session_state.username, "user_query": chats[idx-1]["content"] if idx > 0 else "無標題", "ai_response": m["content"]}
                        with open(os.path.join(SHARED_DIR, f"{share_uuid}.json"), "w", encoding="utf-8") as f: json.dump(shared_data, f, ensure_ascii=False)
                        
                        base_url = "http://localhost:8501" 
                        try:
                            if hasattr(st, "context"):
                                host = st.context.headers.get("host")
                                if host: base_url = f"http://{host}"
                        except: pass
                        st.session_state.last_share_url = f"{base_url}/?share={share_uuid}"
                        st.toast("✅ 已成功生成分享連結！")

                with col5: # 重新生成按鈕
                    if idx == len(chats) - 1:
                        if st.button("🔄", key=f"r_{idx}", help="重新生成", use_container_width=True):
                            st.session_state.regen_flag = True; st.rerun()

    if "last_share_url" in st.session_state:
        st.success("🔗 你的分享連結："); st.code(st.session_state.last_share_url)
        if st.button("關閉連結"): del st.session_state.last_share_url; st.rerun()

    # --- AI 輸入邏輯 ---
    if st.session_state.regen_flag:
        st.session_state.regen_flag = False
        prompt_to_use = chats[-2]["content"]; chats.pop()
    else:
        prompt_to_use = st.chat_input("詢問您的文件或聊天...")

    if prompt_to_use:
        if len(chats) == 0:
            new_n = prompt_to_use[:10] + ("..." if len(prompt_to_use) > 10 else "")
            st.session_state.chats[new_n] = st.session_state.chats.pop(st.session_state.current_chat_id)
            st.session_state.current_chat_id = new_n; chats = st.session_state.chats[new_n]
        
        tool_result = run_local_tool(prompt_to_use)

        if tool_result is not None:
            chats.append({"role": "user", "content": prompt_to_use})
            chats.append({"role": "assistant", "content": f"🛠️ 工具執行結果：\n\n{tool_result}"})
            save_user_chats(st.session_state.username, st.session_state.chats)
            st.rerun()

        if not chats or chats[-1]["content"] != prompt_to_use:
            chats.append({"role": "user", "content": prompt_to_use})
            with st.chat_message("user"): st.markdown(prompt_to_use)

        with st.chat_message("assistant"):
            sys_msg = custom_sys

            if "memory" in st.session_state and st.session_state.memory.get("profile"):
                sys_msg += f"""
                
            以下是使用者的長期記憶，回答時請參考：
            {st.session_state.memory.get("profile")}
            """

            if st.session_state.pdf_context: 
                sys_msg += f"\n\n參考資料 (僅限此用戶): \n{st.session_state.pdf_context[:4000]}"
            final_model = sel_model

            if final_model == "auto":
                final_model = route_model(prompt_to_use, has_image=uploaded_image is not None)


            final_messages = [{"role": "system", "content": sys_msg}]

            # 如果有圖片，最後一則 user message 改成 multimodal 格式
            if uploaded_image:
                image_data_url = image_to_data_url(uploaded_image)

                history_without_latest = chats[:-1]
                final_messages += history_without_latest

                final_messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt_to_use
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_data_url
                            }
                        }
                    ]
                })

                final_model = "meta-llama/llama-4-scout-17b-16e-instruct"
            else:
                final_messages += chats

            st.caption(f"目前使用模型：{final_model}")

            res = client.chat.completions.create(
                model=final_model,
                temperature=temp_val,
                top_p=top_p,
                max_tokens=max_tokens,
                messages=final_messages,
                stream=True
            )

            full_res, ph = "", st.empty()
            for chunk in res:
                if chunk.choices[0].delta.content:
                    full_res += chunk.choices[0].delta.content; ph.markdown(full_res + "▌")
            ph.markdown(full_res)
            chats.append({"role": "assistant", "content": full_res})
            save_user_chats(st.session_state.username, st.session_state.chats); st.rerun()