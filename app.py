import streamlit as st
from groq import Groq
import json
import os
import hashlib
import uuid
from pypdf import PdfReader
import streamlit.components.v1 as components
import base64
import datetime
import re
import tempfile
from io import BytesIO
from PIL import Image

# Optional: video frame extraction. Install with: pip install opencv-python
try:
    import cv2
except Exception:
    cv2 = None

# ==========================================
# 1. 頁面配置與全局 CSS
# ==========================================
st.set_page_config(page_title="My Own ChatGPT Pro", layout="centered", page_icon="🚀")

st.markdown("""
<style>
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
def hash_password(password):
    return hashlib.sha256(str.encode(password)).hexdigest()


def load_user_data(username):
    cp = os.path.join(CHATS_DIR, f"chats_{username}.json")
    kp = os.path.join(KB_DIR, f"kb_{username}.txt")
    st.session_state.chats = json.load(open(cp, "r", encoding="utf-8")) if os.path.exists(cp) else {"新對話 1": []}
    st.session_state.pdf_context = open(kp, "r", encoding="utf-8").read() if os.path.exists(kp) else ""


def save_user_chats(username, chats):
    json.dump(chats, open(os.path.join(CHATS_DIR, f"chats_{username}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=4)


def save_user_kb(username, text):
    with open(os.path.join(KB_DIR, f"kb_{username}.txt"), "w", encoding="utf-8") as f:
        f.write(text)


def default_memory():
    return {
        "profile": "",
        "preferences": [],
        "important_notes": [],
        "auto_memories": []
    }


def load_user_memory(username):
    memory_path = os.path.join(MEMORY_DIR, f"memory_{username}.json")
    if os.path.exists(memory_path):
        with open(memory_path, "r", encoding="utf-8") as f:
            memory = json.load(f)
        base = default_memory()
        base.update(memory)
        for key in ["preferences", "important_notes", "auto_memories"]:
            if not isinstance(base.get(key), list):
                base[key] = []
        return base
    return default_memory()


def save_user_memory(username, memory):
    memory_path = os.path.join(MEMORY_DIR, f"memory_{username}.json")
    with open(memory_path, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=4)


def dedupe_list(items, max_items=30):
    result = []
    seen = set()
    for item in items:
        item = str(item).strip()
        if not item:
            continue
        key = item.lower()
        if key not in seen:
            result.append(item)
            seen.add(key)
    return result[-max_items:]


def memory_to_prompt(memory):
    parts = []
    if memory.get("profile"):
        parts.append(f"使用者固定資訊 / 偏好：\n{memory.get('profile')}")
    if memory.get("preferences"):
        parts.append("偏好設定：\n" + "\n".join([f"- {x}" for x in memory["preferences"]]))
    if memory.get("important_notes"):
        parts.append("重要事項：\n" + "\n".join([f"- {x}" for x in memory["important_notes"]]))
    if memory.get("auto_memories"):
        parts.append("自動記憶：\n" + "\n".join([f"- {x}" for x in memory["auto_memories"]]))
    return "\n\n".join(parts)


def safe_json_loads(text):
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            return None
    return None


def auto_update_memory(client, username, memory, user_text, assistant_text):
    """使用 LLM 自動從對話中萃取值得長期保存的記憶。"""
    if not user_text or len(user_text.strip()) < 4:
        return memory, []

    memory_prompt = f"""
你是一個長期記憶萃取器。請從使用者訊息與助理回覆中，判斷是否有值得未來長期保存的資訊。

只保存長期有用、未來回答會用到的內容，例如：
- 使用者偏好的語言、格式、教學風格、程式碼註解方式
- 使用者正在做的長期專案、課程、作業方向
- 使用者明確要求「記住」、「以後都」、「之後請」的偏好

不要保存：
- 一次性的短期問題
- 密碼、金鑰、身分證、精確地址、電話等敏感個資
- 健康、政治、宗教、種族、性取向等敏感身分資訊，除非使用者明確要求保存

請只輸出 JSON，不要輸出其他文字。格式如下：
{{
  "profile_append": "可加入 profile 的一句話，沒有則空字串",
  "preferences": ["偏好1", "偏好2"],
  "important_notes": ["重要事項1"],
  "auto_memories": ["一般自動記憶1"]
}}

目前既有記憶：
{json.dumps(memory, ensure_ascii=False)}

使用者訊息：
{user_text[:2500]}

助理回覆：
{assistant_text[:2500]}
"""
    try:
        res = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": memory_prompt}],
            temperature=0,
            max_tokens=600
        )
        data = safe_json_loads(res.choices[0].message.content or "")
        if not data:
            return memory, []

        changed = []
        profile_append = str(data.get("profile_append", "")).strip()
        if profile_append and profile_append not in memory.get("profile", ""):
            if memory.get("profile"):
                memory["profile"] += "\n" + profile_append
            else:
                memory["profile"] = profile_append
            changed.append(profile_append)

        for key in ["preferences", "important_notes", "auto_memories"]:
            new_items = data.get(key, [])
            if isinstance(new_items, list):
                before = set(memory.get(key, []))
                memory[key] = dedupe_list(memory.get(key, []) + new_items)
                for item in memory[key]:
                    if item not in before:
                        changed.append(item)

        if changed:
            save_user_memory(username, memory)
        return memory, changed
    except Exception:
        # 記憶萃取失敗不應該影響主要聊天功能
        return memory, []


def get_pdf_text(pdf_docs):
    text = ""
    for pdf in pdf_docs:
        try:
            for page in PdfReader(pdf).pages:
                content = page.extract_text()
                if content:
                    text += content + "\n"
        except Exception as e:
            text += f"\n[PDF 讀取失敗：{getattr(pdf, 'name', 'unknown')}，原因：{e}]\n"
    return text


def route_model(prompt, has_media=False):
    text = prompt.lower()

    if has_media:
        return "meta-llama/llama-4-scout-17b-16e-instruct"

    code_keywords = ["code", "python", "c++", "java", "bug", "錯誤", "程式", "演算法", "debug", "streamlit", "github", "api"]
    reasoning_keywords = ["推理", "分析", "比較", "證明", "為什麼", "詳細解釋", "step by step", "邏輯", "規劃"]
    chinese_keywords = ["翻譯", "中文", "英文", "作文", "報告", "簡報", "講稿"]

    if any(k in text for k in code_keywords):
        return "qwen/qwen3-32b"
    if any(k in text for k in reasoning_keywords):
        return "openai/gpt-oss-120b"
    if any(k in text for k in chinese_keywords):
        return "llama-3.3-70b-versatile"
    if len(prompt) < 80:
        return "llama-3.1-8b-instant"
    return "llama-3.3-70b-versatile"


def file_to_data_url(uploaded_file):
    file_bytes = uploaded_file.getvalue()
    encoded = base64.b64encode(file_bytes).decode("utf-8")
    mime_type = uploaded_file.type or "application/octet-stream"
    return f"data:{mime_type};base64,{encoded}"


def pil_image_to_data_url(image, fmt="JPEG"):
    buf = BytesIO()
    image.save(buf, format=fmt)
    encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/{fmt.lower()};base64,{encoded}"


def transcribe_audio(client, uploaded_file):
    suffix = os.path.splitext(uploaded_file.name)[1] or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name
    try:
        with open(tmp_path, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                file=(uploaded_file.name, audio_file, uploaded_file.type or "audio/mpeg"),
                model="whisper-large-v3"
            )
        return getattr(transcription, "text", str(transcription))
    except Exception as e:
        return f"[音訊轉文字失敗：{uploaded_file.name}，原因：{e}]"
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


def extract_video_frames(uploaded_file, max_frames=4):
    """從影片平均擷取數張影格，讓 vision model 進行視覺理解。"""
    frames = []
    if cv2 is None:
        return frames, "未安裝 opencv-python，無法擷取影片影格。請執行：pip install opencv-python"

    suffix = os.path.splitext(uploaded_file.name)[1] or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name

    try:
        cap = cv2.VideoCapture(tmp_path)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total <= 0:
            cap.release()
            return frames, "影片無法讀取或沒有影格。"

        positions = [int(total * (i + 1) / (max_frames + 1)) for i in range(max_frames)]
        for pos in positions:
            cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
            ok, frame = cap.read()
            if not ok:
                continue
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(frame)
            frames.append(pil_image_to_data_url(image, fmt="JPEG"))
        cap.release()
        return frames, ""
    except Exception as e:
        return frames, f"影片影格擷取失敗：{e}"
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


def read_text_file(uploaded_file):
    try:
        raw = uploaded_file.getvalue()
        return raw.decode("utf-8")
    except Exception:
        try:
            return uploaded_file.getvalue().decode("big5", errors="ignore")
        except Exception as e:
            return f"[文字檔讀取失敗：{uploaded_file.name}，原因：{e}]"


def prepare_multimodal_inputs(client, uploaded_files, video_frame_count=8):
    """處理混合檔案：圖片送 vision、音訊轉文字、影片擷取影格、文件抽文字。"""
    image_urls = []
    text_blocks = []
    summaries = []

    for f in uploaded_files or []:
        mime = f.type or ""
        name = f.name

        if mime.startswith("image/"):
            image_urls.append(file_to_data_url(f))
            summaries.append(f"圖片：{name}")

        elif mime.startswith("audio/"):
            transcript = transcribe_audio(client, f)
            text_blocks.append(f"[音訊檔：{name} 轉文字]\n{transcript}")
            summaries.append(f"音訊：{name}")

        elif mime.startswith("video/"):
            frames, warning = extract_video_frames(f, max_frames=video_frame_count)
            image_urls.extend(frames)
            if warning:
                text_blocks.append(f"[影片檔：{name}] {warning}")
            else:
                text_blocks.append(f"[影片檔：{name}] 已擷取 {len(frames)} 張代表影格供視覺模型分析。注意：這是抽樣影格分析，不是逐秒完整影片串流分析。")
            summaries.append(f"影片：{name}")

        elif mime == "application/pdf" or name.lower().endswith(".pdf"):
            text = get_pdf_text([f])
            text_blocks.append(f"[PDF 文件：{name}]\n{text[:6000]}")
            summaries.append(f"PDF：{name}")

        elif mime.startswith("text/") or name.lower().endswith((".txt", ".md", ".csv", ".json", ".py", ".cpp", ".java", ".html", ".css", ".js")):
            text = read_text_file(f)
            text_blocks.append(f"[文字 / 程式檔：{name}]\n{text[:6000]}")
            summaries.append(f"文字檔：{name}")

        else:
            text_blocks.append(f"[不支援直接解析的檔案：{name}，MIME：{mime}] 請改上傳 PDF、文字檔、圖片、音訊或影片。")
            summaries.append(f"其他檔案：{name}")

    return {
        "image_urls": image_urls,
        "text_context": "\n\n".join(text_blocks),
        "summary": "、".join(summaries)
    }


def get_uploaded_files_signature(uploaded_files, video_frame_count):
    """建立附件指紋，用來判斷檔案是否改變；沒改變就可以重用快取。"""
    signatures = []
    for f in uploaded_files or []:
        file_bytes = f.getvalue()
        digest = hashlib.md5(file_bytes).hexdigest()
        signatures.append({
            "name": f.name,
            "type": f.type or "",
            "size": len(file_bytes),
            "md5": digest
        })
    return json.dumps({
        "files": signatures,
        "video_frame_count": video_frame_count
    }, sort_keys=True, ensure_ascii=False)


def get_cached_multimodal_inputs(client, uploaded_files, video_frame_count=8):
    """
    多模態附件快取：
    同一批檔案、同一個影片抽幀數，不重複做 PDF 解析、音訊轉錄、影片抽幀。
    """
    signature = get_uploaded_files_signature(uploaded_files, video_frame_count)

    if "media_cache" not in st.session_state:
        st.session_state.media_cache = {}

    cached = st.session_state.media_cache.get(signature)
    if cached is not None:
        return cached, True

    payload = prepare_multimodal_inputs(
        client=client,
        uploaded_files=uploaded_files,
        video_frame_count=video_frame_count
    )

    # 只保留最近 3 組快取，避免 session_state 太大。
    st.session_state.media_cache[signature] = payload
    if len(st.session_state.media_cache) > 3:
        oldest_key = next(iter(st.session_state.media_cache))
        del st.session_state.media_cache[oldest_key]

    return payload, False


def calculator_tool(expression):
    try:
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
        with open(share_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        st.title("📢 分享的 AI 回應")
        st.info(f"來自用戶 **{data['author']}** 的對話分享")
        with st.chat_message("user"):
            st.markdown(data["user_query"])
        with st.chat_message("assistant"):
            st.markdown(data["ai_response"])
        st.divider()
        if st.button("返回系統"):
            st.query_params.clear()
            st.rerun()
        st.stop()

# ==========================================
# 4. 身份驗證與對話管理
# ==========================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "regen_flag" not in st.session_state:
    st.session_state.regen_flag = False

if not st.session_state.authenticated:
    st.title("🛡️ 個人 AI 助手")
    t1, t2 = st.tabs(["登入", "註冊"])
    with t1:
        u = st.text_input("帳號", key="l_u")
        p = st.text_input("密碼", type="password", key="l_p")
        if st.button("進入系統"):
            users = json.load(open(USER_DATA_FILE)) if os.path.exists(USER_DATA_FILE) else {}
            if u in users and users[u] == hash_password(p):
                st.session_state.authenticated = True
                st.session_state.username = u
                load_user_data(u)
                st.session_state.memory = load_user_memory(u)
                st.session_state.current_chat_id = list(st.session_state.chats.keys())[0]
                st.rerun()
            else:
                st.error("帳號或密碼錯誤")
    with t2:
        nu = st.text_input("新帳號", key="n_u")
        np = st.text_input("新密碼", type="password", key="n_p")
        if st.button("建立空間"):
            users = json.load(open(USER_DATA_FILE)) if os.path.exists(USER_DATA_FILE) else {}
            if nu in users:
                st.error("帳號已存在")
            else:
                users[nu] = hash_password(np)
                json.dump(users, open(USER_DATA_FILE, "w"))
                st.success("註冊成功")
else:
    client = Groq(api_key=st.secrets["GROQ_API_KEY"])

    with st.sidebar:
        st.write(f"👤 用戶: **{st.session_state.username}**")
        if st.button("登出"):
            st.session_state.authenticated = False
            st.rerun()

        st.divider()
        st.title("📚 個人知識庫")
        files = st.file_uploader("上傳 PDF (隔離保護)", type="pdf", accept_multiple_files=True)
        if st.button("學習文件"):
            if files:
                with st.spinner("分析中..."):
                    text = get_pdf_text(files)
                    st.session_state.pdf_context = text
                    save_user_kb(st.session_state.username, text)
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
        if st.session_state.pdf_context:
            st.caption("✅ 已啟用個人知識庫")

        st.divider()
        st.title("🧠 長期記憶")
        if "memory" not in st.session_state:
            st.session_state.memory = load_user_memory(st.session_state.username)

        memory_profile = st.text_area(
            "手動記憶：使用者固定資訊 / 偏好",
            value=st.session_state.memory.get("profile", ""),
            height=100,
            placeholder="例如：我希望回答使用繁體中文、程式碼要加註解、回答要適合初學者。"
        )
        if st.button("💾 儲存手動記憶", use_container_width=True):
            st.session_state.memory["profile"] = memory_profile
            save_user_memory(st.session_state.username, st.session_state.memory)
            st.success("長期記憶已儲存！")

        with st.expander("查看自動記憶"):
            st.write("偏好設定")
            st.json(st.session_state.memory.get("preferences", []))
            st.write("重要事項")
            st.json(st.session_state.memory.get("important_notes", []))
            st.write("一般自動記憶")
            st.json(st.session_state.memory.get("auto_memories", []))

        enable_auto_memory = st.checkbox("啟用自動長期記憶", value=True)

        if st.button("🧹 清除長期記憶", use_container_width=True):
            st.session_state.memory = default_memory()
            save_user_memory(st.session_state.username, st.session_state.memory)
            st.warning("長期記憶已清除！")

        st.divider()
        st.title("💬 對話管理")
        if st.button("＋ 新增對話", use_container_width=True):
            nid = f"對話 {len(st.session_state.chats) + 1}"
            st.session_state.chats[nid] = []
            st.session_state.current_chat_id = nid
            st.rerun()

        if st.button("🗑️ 刪除目前對話", use_container_width=True):
            if len(st.session_state.chats) > 1:
                target_id = st.session_state.current_chat_id
                del st.session_state.chats[target_id]
                st.session_state.current_chat_id = list(st.session_state.chats.keys())[0]
                save_user_chats(st.session_state.username, st.session_state.chats)
                st.toast(f"✅ 已刪除對話：{target_id}")
                st.rerun()
            else:
                st.session_state.chats[st.session_state.current_chat_id] = []
                save_user_chats(st.session_state.username, st.session_state.chats)
                st.toast("✅ 已清空目前對話")
                st.rerun()

        with st.expander("📝 更改對話名稱"):
            new_name = st.text_input("新名稱", value=st.session_state.current_chat_id)
            if st.button("確認修改"):
                old_id = st.session_state.current_chat_id
                st.session_state.chats[new_name] = st.session_state.chats.pop(old_id)
                st.session_state.current_chat_id = new_name
                save_user_chats(st.session_state.username, st.session_state.chats)
                st.rerun()

        chat_list = list(st.session_state.chats.keys())
        selected = st.radio("歷史紀錄", chat_list, index=chat_list.index(st.session_state.current_chat_id))
        if selected != st.session_state.current_chat_id:
            st.session_state.current_chat_id = selected
            st.rerun()

        st.divider()
        st.title("⚙️ 設定面板")
        model_options = {
            "Auto｜自動選擇模型": "auto",
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
    st.title("🧩 Multimodal 混合檔案理解")
    uploaded_files = st.file_uploader(
        "可同時上傳圖片、音訊、影片、PDF、文字檔 / 程式檔",
        type=[
            "png", "jpg", "jpeg", "webp",
            "mp3", "wav", "m4a", "ogg", "flac",
            "mp4", "mov", "avi", "mkv", "webm",
            "pdf", "txt", "md", "csv", "json", "py", "cpp", "java", "html", "css", "js"
        ],
        accept_multiple_files=True,
        key="mixed_files"
    )

    video_frame_count = st.slider(
        "影片代表影格數",
        min_value=4,
        max_value=16,
        value=8,
        step=2,
        help="數字越高，影片畫面理解越完整，但會增加處理時間與 vision token 成本。"
    )
    st.caption("影片分析方式：系統會從影片中抽取代表影格給視覺模型分析，不是逐秒完整影片串流分析。")

    if uploaded_files:
        for f in uploaded_files:
            if (f.type or "").startswith("image/"):
                st.image(f, caption=f.name, use_container_width=True)
            elif (f.type or "").startswith("audio/"):
                st.audio(f)
            elif (f.type or "").startswith("video/"):
                st.video(f)
            else:
                st.caption(f"📎 已上傳：{f.name}")

    chats = st.session_state.chats[st.session_state.current_chat_id]
    for idx, m in enumerate(chats):
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

            if m["role"] == "assistant":
                js_text = json.dumps(m["content"], ensure_ascii=False)
                col1, col2, col3, col4, col5, _ = st.columns([0.15, 0.12, 0.12, 0.12, 0.12, 0.4])

                with col1:
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
                                ta.value = {js_text}; window.parent.document.body.appendChild(ta); ta.select();
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

                with col2:
                    if st.button("👍", key=f"g_{idx}", help="回應良好", use_container_width=True):
                        st.toast("✅ 感謝您的好評！")
                with col3:
                    if st.button("👎", key=f"b_{idx}", help="回應不佳", use_container_width=True):
                        st.toast("✅ 收到！我們會改進。")
                with col4:
                    if st.button("📤", key=f"share_btn_{idx}", help="生成分享連結", use_container_width=True):
                        share_uuid = uuid.uuid4().hex[:12]
                        shared_data = {
                            "author": st.session_state.username,
                            "user_query": chats[idx - 1]["content"] if idx > 0 else "無標題",
                            "ai_response": m["content"]
                        }
                        with open(os.path.join(SHARED_DIR, f"{share_uuid}.json"), "w", encoding="utf-8") as f:
                            json.dump(shared_data, f, ensure_ascii=False)

                        base_url = "http://localhost:8501"
                        try:
                            if hasattr(st, "context"):
                                host = st.context.headers.get("host")
                                if host:
                                    base_url = f"http://{host}"
                        except Exception:
                            pass
                        st.session_state.last_share_url = f"{base_url}/?share={share_uuid}"
                        st.toast("✅ 已成功生成分享連結！")

                with col5:
                    if idx == len(chats) - 1:
                        if st.button("🔄", key=f"r_{idx}", help="重新生成", use_container_width=True):
                            st.session_state.regen_flag = True
                            st.rerun()

    if "last_share_url" in st.session_state:
        st.success("🔗 你的分享連結：")
        st.code(st.session_state.last_share_url)
        if st.button("關閉連結"):
            del st.session_state.last_share_url
            st.rerun()

    # --- AI 輸入邏輯 ---
    if st.session_state.regen_flag:
        st.session_state.regen_flag = False
        if len(chats) >= 2 and chats[-1].get("role") == "assistant":
            prompt_to_use = chats[-2]["content"]
            # 若上一輪使用者訊息含有附件摘要，只取真正提問文字，避免把附件摘要重複塞回去。
            if "\n\n📎 附件：" in prompt_to_use:
                prompt_to_use = prompt_to_use.split("\n\n📎 附件：", 1)[0]
            chats.pop()
        else:
            prompt_to_use = None
            st.warning("目前沒有足夠的對話可以重新生成。")
    else:
        prompt_to_use = st.chat_input("詢問您的文件、圖片、音訊、影片或聊天...")

    if prompt_to_use:
        if len(chats) == 0:
            new_n = prompt_to_use[:10] + ("..." if len(prompt_to_use) > 10 else "")
            st.session_state.chats[new_n] = st.session_state.chats.pop(st.session_state.current_chat_id)
            st.session_state.current_chat_id = new_n
            chats = st.session_state.chats[new_n]

        tool_result = run_local_tool(prompt_to_use)
        if tool_result is not None:
            chats.append({"role": "user", "content": prompt_to_use})
            chats.append({"role": "assistant", "content": f"🛠️ 工具執行結果：\n\n{tool_result}"})
            save_user_chats(st.session_state.username, st.session_state.chats)
            st.rerun()

        media_payload, used_media_cache = get_cached_multimodal_inputs(client, uploaded_files, video_frame_count)
        media_context = media_payload["text_context"]
        image_urls = media_payload["image_urls"]
        media_summary = media_payload["summary"]
        if used_media_cache and media_summary:
            st.toast("📎 已使用附件快取，沒有重複解析檔案")

        display_user_text = prompt_to_use
        if media_summary:
            display_user_text += f"\n\n📎 附件：{media_summary}"

        if not chats or chats[-1]["content"] != display_user_text:
            chats.append({"role": "user", "content": display_user_text})
            with st.chat_message("user"):
                st.markdown(display_user_text)

        with st.chat_message("assistant"):
            sys_msg = custom_sys

            memory_prompt_text = memory_to_prompt(st.session_state.memory)
            if memory_prompt_text:
                sys_msg += f"\n\n以下是使用者的長期記憶，回答時請參考：\n{memory_prompt_text}"

            if st.session_state.pdf_context:
                sys_msg += f"\n\n參考資料 (僅限此用戶): \n{st.session_state.pdf_context[:4000]}"

            final_model = sel_model
            if final_model == "auto":
                final_model = route_model(prompt_to_use, has_media=bool(image_urls or media_context))

            final_messages = [{"role": "system", "content": sys_msg}]

            prompt_with_context = prompt_to_use
            if media_context:
                prompt_with_context += f"\n\n以下是本次上傳檔案解析內容：\n{media_context[:12000]}"

            # 有圖片或影片影格時，使用 vision 格式
            if image_urls:
                history_without_latest = chats[:-1]
                final_messages += history_without_latest
                content_parts = [{"type": "text", "text": prompt_with_context}]
                for url in image_urls[:16]:
                    content_parts.append({"type": "image_url", "image_url": {"url": url}})
                final_messages.append({"role": "user", "content": content_parts})
                final_model = "meta-llama/llama-4-scout-17b-16e-instruct"
            else:
                final_messages += chats[:-1]
                final_messages.append({"role": "user", "content": prompt_with_context})

            st.caption(f"目前使用模型：{final_model}")

            try:
                res = client.chat.completions.create(
                    model=final_model,
                    temperature=temp_val,
                    top_p=top_p,
                    max_tokens=max_tokens,
                    messages=final_messages,
                    stream=True
                )

                full_res = ""
                ph = st.empty()
                for chunk in res:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        full_res += delta
                        ph.markdown(full_res + "▌")
                ph.markdown(full_res)

            except Exception as e:
                full_res = f"AI 回覆失敗：{e}"
                st.error(full_res)
                # 如果模型呼叫失敗，不把錯誤回答存成正式 assistant 回覆。
                st.stop()

            chats.append({"role": "assistant", "content": full_res})
            save_user_chats(st.session_state.username, st.session_state.chats)

            # 回答完成後，自動萃取長期記憶
            if enable_auto_memory:
                updated_memory, changed_items = auto_update_memory(
                    client=client,
                    username=st.session_state.username,
                    memory=st.session_state.memory,
                    user_text=display_user_text,
                    assistant_text=full_res
                )
                st.session_state.memory = updated_memory
                if changed_items:
                    st.toast(f"🧠 已自動新增 {len(changed_items)} 筆長期記憶")

            st.rerun()
