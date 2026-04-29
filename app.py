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
import time
from io import BytesIO
from PIL import Image

try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:
    Fernet = None
    InvalidToken = Exception

# Google OAuth login. Install with: pip install streamlit-oauth requests
try:
    from streamlit_oauth import OAuth2Component
except Exception:
    OAuth2Component = None

try:
    import requests
except Exception:
    requests = None

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

USER_DATA_FILE = "users.json"  # 舊版帳密登入用；Google OAuth 版本不再使用。
GOOGLE_USERS_FILE = "google_users.json"
CHATS_DIR = "user_chats"
KB_DIR = "user_knowledge"
SHARED_DIR = "shared_content"
MEMORY_DIR = "user_memory"
USER_SECRETS_DIR = "user_secrets"

for folder in [CHATS_DIR, KB_DIR, SHARED_DIR, MEMORY_DIR, USER_SECRETS_DIR]:
    if not os.path.exists(folder):
        os.makedirs(folder)


# ==========================================
# Google OAuth 登入輔助函式
# ==========================================
def sanitize_user_id(email):
    """把 Google Email 轉成安全的檔名 ID，避免特殊字元造成路徑問題。"""
    email = (email or "").strip().lower()
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", email)
    return safe or "unknown_user"


def load_google_users():
    if os.path.exists(GOOGLE_USERS_FILE):
        try:
            with open(GOOGLE_USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_google_users(users):
    with open(GOOGLE_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=4)


# ==========================================
# 使用者 API Key 加密儲存輔助函式
# ==========================================
def get_app_encryption_key():
    """從 Streamlit secrets 讀取 Fernet 加密金鑰。請勿放到 GitHub。"""
    if Fernet is None:
        raise RuntimeError("尚未安裝 cryptography。請執行：pip install cryptography")

    try:
        key = st.secrets.get("APP_ENCRYPTION_KEY", "")
    except Exception:
        key = ""

    key = str(key).strip()
    if not key:
        raise RuntimeError(
            "缺少 APP_ENCRYPTION_KEY。請先在 .streamlit/secrets.toml 加入加密金鑰。"
        )

    try:
        Fernet(key.encode("utf-8"))
    except Exception:
        raise RuntimeError(
            "APP_ENCRYPTION_KEY 格式錯誤。請用 Fernet.generate_key() 產生。"
        )

    return key.encode("utf-8")


def encrypt_text(plain_text):
    fernet = Fernet(get_app_encryption_key())
    return fernet.encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_text(encrypted_text):
    fernet = Fernet(get_app_encryption_key())
    return fernet.decrypt(encrypted_text.encode("utf-8")).decode("utf-8")


def get_user_secret_path(username):
    safe_username = sanitize_user_id(username)
    return os.path.join(USER_SECRETS_DIR, f"secrets_{safe_username}.json")


def load_user_api_key(username):
    """讀取並解密目前使用者自己的 Groq API Key。"""
    path = get_user_secret_path(username)
    if not os.path.exists(path):
        return ""

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        encrypted_key = data.get("groq_api_key", "")
        if not encrypted_key:
            return ""
        return decrypt_text(encrypted_key)
    except InvalidToken:
        st.error("API Key 解密失敗：APP_ENCRYPTION_KEY 可能已更換。請刪除舊 Key 後重新輸入。")
        return ""
    except Exception as e:
        st.error(f"讀取 API Key 失敗：{e}")
        return ""


def save_user_api_key(username, api_key):
    """將目前使用者自己的 Groq API Key 加密後儲存。"""
    api_key = (api_key or "").strip()
    if not api_key:
        raise ValueError("API Key 不可為空。")

    data = {
        "provider": "groq",
        "groq_api_key": encrypt_text(api_key),
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    with open(get_user_secret_path(username), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def delete_user_api_key(username):
    path = get_user_secret_path(username)
    if os.path.exists(path):
        os.remove(path)


def mask_api_key(api_key):
    api_key = api_key or ""
    if len(api_key) <= 10:
        return "已儲存 API Key"
    return f"{api_key[:6]}...{api_key[-4:]}"


def render_api_key_panel(username):
    """在側邊欄顯示 API Key 輸入 / 儲存 / 刪除區塊，並回傳解密後的 Groq API Key。"""
    st.divider()
    st.title("🔐 API Key")

    try:
        stored_key = load_user_api_key(username)
    except Exception as e:
        stored_key = ""
        st.error(str(e))
        st.code("""# 產生 APP_ENCRYPTION_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# .streamlit/secrets.toml
APP_ENCRYPTION_KEY = "貼上剛剛產生的金鑰"
""")

    if stored_key:
        st.success(f"已加密儲存 Groq API Key：{mask_api_key(stored_key)}")
    else:
        st.warning("尚未設定 Groq API Key。請輸入自己的 API Key 才能開始聊天。")

    with st.expander("設定 / 更換 Groq API Key", expanded=not bool(stored_key)):
        new_key = st.text_input(
            "Groq API Key",
            type="password",
            placeholder="gsk_...",
            help="你的 API Key 會用 APP_ENCRYPTION_KEY 加密後，儲存在本機 user_secrets 資料夾。"
        )

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("💾 加密儲存", use_container_width=True):
                try:
                    save_user_api_key(username, new_key)
                    st.session_state.user_groq_api_key = new_key.strip()
                    st.success("API Key 已加密儲存！")
                    st.rerun()
                except Exception as e:
                    st.error(f"儲存失敗：{e}")

        with col_b:
            if st.button("🧹 刪除 Key", use_container_width=True):
                delete_user_api_key(username)
                if "user_groq_api_key" in st.session_state:
                    del st.session_state.user_groq_api_key
                st.warning("已刪除儲存的 API Key。")
                st.rerun()

    # 優先用 session 裡剛儲存的 key，否則用檔案中解密出的 key。
    return st.session_state.get("user_groq_api_key") or stored_key


def render_api_key_compact(username):
    """底部彈出式 API Key 設定，不使用巢狀 expander，適合放在 popover 裡。"""
    try:
        stored_key = load_user_api_key(username)
    except Exception as e:
        stored_key = ""
        st.error(str(e))
        st.code(
            "# 產生 APP_ENCRYPTION_KEY\n"
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"\n\n"
            "# .streamlit/secrets.toml\n"
            "APP_ENCRYPTION_KEY = \"貼上剛剛產生的金鑰\""
        )

    if stored_key:
        st.success(f"已加密儲存 Groq API Key：{mask_api_key(stored_key)}")
    else:
        st.warning("尚未設定 Groq API Key。請輸入自己的 API Key 才能開始聊天。")

    new_key = st.text_input(
        "Groq API Key",
        type="password",
        placeholder="gsk_...",
        key="bottom_groq_api_key_input",
        help="你的 API Key 會用 APP_ENCRYPTION_KEY 加密後，儲存在本機 user_secrets 資料夾。"
    )

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("💾 加密儲存", key="bottom_save_api_key", use_container_width=True):
            try:
                save_user_api_key(username, new_key)
                st.session_state.user_groq_api_key = new_key.strip()
                st.success("API Key 已加密儲存！")
                st.rerun()
            except Exception as e:
                st.error(f"儲存失敗：{e}")

    with col_b:
        if st.button("🧹 刪除 Key", key="bottom_delete_api_key", use_container_width=True):
            delete_user_api_key(username)
            if "user_groq_api_key" in st.session_state:
                del st.session_state.user_groq_api_key
            st.warning("已刪除儲存的 API Key。")
            st.rerun()

    return st.session_state.get("user_groq_api_key") or stored_key


def upsert_google_user(user_info):
    """首次 Google 登入時自動建立使用者資料；之後更新最後登入時間與頭像。"""
    email = user_info.get("email", "").strip().lower()
    user_id = sanitize_user_id(email)
    users = load_google_users()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if user_id not in users:
        users[user_id] = {
            "email": email,
            "name": user_info.get("name") or email,
            "picture": user_info.get("picture", ""),
            "created_at": now,
            "last_login": now,
            "login_provider": "google"
        }
    else:
        users[user_id].update({
            "email": email,
            "name": user_info.get("name") or users[user_id].get("name") or email,
            "picture": user_info.get("picture") or users[user_id].get("picture", ""),
            "last_login": now,
            "login_provider": "google"
        })

    save_google_users(users)
    return user_id, users[user_id]


def get_app_base_url():
    """取得 OAuth redirect URI。部署時可在 secrets.toml 設定 APP_BASE_URL。"""
    try:
        if "APP_BASE_URL" in st.secrets and st.secrets["APP_BASE_URL"]:
            return str(st.secrets["APP_BASE_URL"]).rstrip("/")
    except Exception:
        pass

    try:
        if hasattr(st, "context"):
            host = st.context.headers.get("host")
            proto = st.context.headers.get("x-forwarded-proto", "http")
            if host:
                return f"{proto}://{host}".rstrip("/")
    except Exception:
        pass

    return "http://localhost:8501"


def get_google_oauth_component():
    if OAuth2Component is None:
        return None

    return OAuth2Component(
        client_id=st.secrets["GOOGLE_CLIENT_ID"],
        client_secret=st.secrets["GOOGLE_CLIENT_SECRET"],
        authorize_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
        token_endpoint="https://oauth2.googleapis.com/token",
        refresh_token_endpoint="https://oauth2.googleapis.com/token",
        revoke_token_endpoint="https://oauth2.googleapis.com/revoke",
    )


def get_google_user_info(token):
    """用 access_token 取得 Google 使用者基本資料。"""
    if requests is None:
        raise RuntimeError("尚未安裝 requests，請執行：pip install requests")

    access_token = None
    if isinstance(token, dict):
        access_token = token.get("access_token")
    if not access_token:
        raise RuntimeError("Google OAuth token 中找不到 access_token。")

    res = requests.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    res.raise_for_status()
    return res.json()


def complete_google_login(user_info, token=None):
    """完成登入流程：建立使用者、載入聊天/知識庫/記憶。"""
    email = user_info.get("email", "").strip().lower()
    if not email:
        st.error("Google 沒有回傳 Email，無法登入。")
        st.stop()

    user_id, profile = upsert_google_user(user_info)

    st.session_state.authenticated = True
    st.session_state.login_provider = "google"
    st.session_state.oauth_token = token
    st.session_state.google_user = user_info
    st.session_state.username = user_id              # 內部安全檔名 ID
    st.session_state.user_email = email              # 顯示用 Email
    st.session_state.user_name = profile.get("name") or email
    st.session_state.user_picture = profile.get("picture", "")

    load_user_data(user_id)
    st.session_state.memory = load_user_memory(user_id)
    st.session_state.current_chat_id = list(st.session_state.chats.keys())[0]


def clear_login_session():
    """登出：清掉本機 session，不刪除使用者資料。"""
    keys = [
        "authenticated", "login_provider", "oauth_token", "google_user",
        "username", "user_email", "user_name", "user_picture",
        "chats", "pdf_context", "memory", "current_chat_id",
        "media_cache", "regen_flag", "last_share_url", "user_groq_api_key"
    ]
    for key in keys:
        if key in st.session_state:
            del st.session_state[key]
    st.session_state.authenticated = False


def render_google_login_page():
    st.title("🛡️ 個人 AI 助手")
    st.subheader("使用 Google 帳號登入")
    st.caption("登入後系統會自動建立使用者資料，並用你的 Google Email 區分聊天紀錄、知識庫與長期記憶。")

    if OAuth2Component is None:
        st.error("尚未安裝 streamlit-oauth。請先執行：pip install streamlit-oauth requests")
        st.stop()

    missing = []
    for key in ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]:
        try:
            if key not in st.secrets or not st.secrets[key]:
                missing.append(key)
        except Exception:
            missing.append(key)

    if missing:
        st.error("缺少 Google OAuth 設定：" + ", ".join(missing))
        st.code("""# .streamlit/secrets.toml
GOOGLE_CLIENT_ID = "你的 Google OAuth Client ID"
GOOGLE_CLIENT_SECRET = "你的 Google OAuth Client Secret"
APP_BASE_URL = "http://localhost:8501"
""")
        st.stop()

    oauth2 = get_google_oauth_component()
    redirect_uri = get_app_base_url()

    result = oauth2.authorize_button(
        name="使用 Google 登入",
        icon="https://www.google.com/favicon.ico",
        redirect_uri=redirect_uri,
        scope="openid email profile",
        key="google_login",
    )

    st.info(f"Google Cloud Console 的 Authorized redirect URI 請設定為：{redirect_uri}")

    if result and "token" in result:
        try:
            token = result["token"]
            user_info = get_google_user_info(token)
            complete_google_login(user_info, token=token)
            st.rerun()
        except Exception as e:
            st.error(f"Google 登入失敗：{e}")


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


# ==========================================
# MCP-style 工具層與自動工具呼叫
# ==========================================
# 這裡把原本 /calc、/time、/count 升級成「工具清單 + tools/list + tools/call」。
# LLM 可以先判斷是否要使用工具，再透過這個 MCP-style JSON-RPC 層呼叫工具。

LOCAL_TOOL_SCHEMAS = [
    {
        "name": "calculator",
        "description": "計算基本數學算式，例如 12*(3+4)。只支援安全的四則運算字元。",
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "要計算的數學算式，例如 1+2*3"
                }
            },
            "required": ["expression"]
        }
    },
    {
        "name": "current_time",
        "description": "取得目前系統時間。",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "word_count",
        "description": "計算文字中的中文字數、英文單字數與數字數量。",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "要統計的文字內容"
                }
            },
            "required": ["text"]
        }
    }
]


def mcp_tools_list():
    """MCP-style tools/list：回傳目前可用工具清單。"""
    return {
        "tools": LOCAL_TOOL_SCHEMAS
    }


def mcp_tools_call(name, arguments=None):
    """MCP-style tools/call：根據工具名稱與 arguments 呼叫本地工具。"""
    arguments = arguments or {}

    if name == "calculator":
        expression = str(arguments.get("expression", "")).strip()
        if not expression:
            return {"is_error": True, "content": "calculator 需要 expression 參數。"}
        return {"is_error": False, "content": calculator_tool(expression)}

    if name == "current_time":
        return {"is_error": False, "content": time_tool()}

    if name == "word_count":
        text = str(arguments.get("text", ""))
        if not text:
            return {"is_error": True, "content": "word_count 需要 text 參數。"}
        return {"is_error": False, "content": word_count_tool(text)}

    return {"is_error": True, "content": f"未知工具：{name}"}


def mcp_handle_jsonrpc(request):
    """簡化版 MCP JSON-RPC handler，支援 tools/list 與 tools/call。"""
    try:
        method = request.get("method")
        request_id = request.get("id")
        params = request.get("params", {}) or {}

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": mcp_tools_list()
            }

        if method == "tools/call":
            result = mcp_tools_call(
                name=params.get("name"),
                arguments=params.get("arguments", {})
            )
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }

        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32601,
                "message": f"Method not found: {method}"
            }
        }
    except Exception as e:
        return {
            "jsonrpc": "2.0",
            "id": request.get("id") if isinstance(request, dict) else None,
            "error": {
                "code": -32603,
                "message": str(e)
            }
        }


def tools_prompt_text():
    return json.dumps(mcp_tools_list(), ensure_ascii=False, indent=2)


def auto_select_mcp_tool(client, prompt):
    """
    讓 LLM 自動判斷是否需要工具。
    若需要，回傳 {use_tool, tool_name, arguments, reason}；否則 use_tool=False。
    """
    selector_prompt = f"""
你是一個工具路由器。請判斷使用者問題是否需要呼叫工具。

可用工具如下：
{tools_prompt_text()}

判斷規則：
- 只有在使用者明確要求「計算數學算式」、「查目前時間」、「統計字數」時才使用工具。
- 如果使用者是在要求「寫程式、產生程式碼、debug、解釋程式、Python/C++/Java 範例」，不要使用 calculator，即使題目裡出現數字。
- 如果使用者只是舉例輸入兩個數字、寫一個加總程式、教學或作業說明，不要使用工具。
- 一般聊天、翻譯、寫作、程式解釋、文件分析，不要使用工具。
- 所有中文請使用繁體中文。
- 請只輸出 JSON，不要輸出其他文字。

輸出格式：
{{
  "use_tool": true 或 false,
  "tool_name": "calculator/current_time/word_count 其中之一，若不用工具則空字串",
  "arguments": {{"expression": "..." 或 "text": "..."}},
  "reason": "簡短原因"
}}

使用者問題：
{prompt}
"""
    try:
        res = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": selector_prompt}],
            temperature=0,
            max_tokens=300
        )
        data = safe_json_loads(res.choices[0].message.content or "")
        if not isinstance(data, dict):
            return {"use_tool": False, "tool_name": "", "arguments": {}, "reason": "工具路由輸出無法解析"}
        return data
    except Exception:
        return {"use_tool": False, "tool_name": "", "arguments": {}, "reason": "工具路由失敗"}


def run_local_tool(prompt):
    """保留手動 slash command，同時底層改用 MCP-style tools/call。"""
    text = prompt.strip()
    if text.startswith("/calc"):
        expression = text.replace("/calc", "", 1).strip()
        result = mcp_tools_call("calculator", {"expression": expression})
        return result["content"]
    if text.startswith("/time"):
        result = mcp_tools_call("current_time", {})
        return result["content"]
    if text.startswith("/count"):
        content = text.replace("/count", "", 1).strip()
        result = mcp_tools_call("word_count", {"text": content})
        return result["content"]
    return None


def should_consider_auto_tool(prompt):
    """
    先用規則過濾，避免把「請寫程式」誤判成 calculator。
    只有明確計算、查時間、統計字數才進入 LLM 工具路由器。
    """
    text = (prompt or "").lower()

    block_keywords = [
        "寫一個", "請寫", "程式", "python", "c++", "java", "javascript",
        "debug", "除錯", "程式碼", "函式", "input", "output", "輸入", "輸出"
    ]
    if any(k in text for k in block_keywords):
        if not any(k in text for k in ["幫我算", "請計算", "計算", "算出", "等於多少"]):
            return False

    time_keywords = ["現在幾點", "目前時間", "現在時間", "今天日期", "現在日期"]
    count_keywords = ["字數", "單字數", "統計這段文字", "統計文字", "word count"]
    calc_keywords = ["幫我算", "請計算", "計算", "算出", "等於多少", "calculate"]
    has_math_expression = bool(re.search(r"\d\s*[+\-*/%]\s*\d", text))

    return (
        any(k in text for k in time_keywords)
        or any(k in text for k in count_keywords)
        or (any(k in text for k in calc_keywords) and has_math_expression)
    )


def auto_run_mcp_tool_if_needed(client, prompt):
    """由 LLM 自動選工具，並透過 MCP-style tools/call 執行。"""
    if not should_consider_auto_tool(prompt):
        return None

    decision = auto_select_mcp_tool(client, prompt)
    if not decision.get("use_tool"):
        return None

    tool_name = decision.get("tool_name", "")
    arguments = decision.get("arguments", {}) or {}
    result = mcp_tools_call(tool_name, arguments)

    if result.get("is_error"):
        return f"🧰 MCP 工具呼叫失敗：\n\n工具：{tool_name}\n原因：{result.get('content')}"

    return (
        f"工具：{tool_name}\n\n"
        f"參數：{json.dumps(arguments, ensure_ascii=False)}\n\n"
        f"結果：{result.get('content')}"
    )

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
    render_google_login_page()
else:
    if "memory" not in st.session_state:
        st.session_state.memory = load_user_memory(st.session_state.username)

    user_groq_api_key = ""
    enable_auto_memory = True
    enable_auto_tools = True

    with st.sidebar:
        st.title("👤 使用者")
        if st.session_state.get("user_picture"):
            st.image(st.session_state.user_picture, width=72)
        st.markdown(f"**{st.session_state.get('user_name', 'Google User')}**")
        st.caption(st.session_state.get("user_email", st.session_state.get("username", "")))
        st.caption("登入方式：Google OAuth")
        if st.button("登出 Google", use_container_width=True):
            clear_login_session()
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

        # --- 側邊欄最下方個人設定：像 ChatGPT 帳號區，點開才顯示 ---
        st.divider()
        st.markdown("### 👤 個人設定")
        with st.popover("API Key / 記憶 / MCP", use_container_width=True):
            st.caption(f"目前登入：{st.session_state.get('user_email', st.session_state.get('username', ''))}")
            tab_api, tab_memory, tab_tools = st.tabs(["🔐 API Key", "🧠 長期記憶", "🧰 工具 / MCP"])

            with tab_api:
                user_groq_api_key = render_api_key_compact(st.session_state.username)

            with tab_memory:
                st.write("手動記憶")
                memory_profile = st.text_area(
                    "使用者固定資訊 / 偏好",
                    value=st.session_state.memory.get("profile", ""),
                    height=100,
                    placeholder="例如：我希望回答使用繁體中文、程式碼要加註解、回答要適合初學者。",
                    key="sidebar_bottom_memory_profile"
                )
                if st.button("💾 儲存手動記憶", key="sidebar_bottom_save_memory", use_container_width=True):
                    st.session_state.memory["profile"] = memory_profile
                    save_user_memory(st.session_state.username, st.session_state.memory)
                    st.success("長期記憶已儲存！")
                    st.rerun()

                st.write("自動記憶")
                st.json({
                    "preferences": st.session_state.memory.get("preferences", []),
                    "important_notes": st.session_state.memory.get("important_notes", []),
                    "auto_memories": st.session_state.memory.get("auto_memories", [])
                })

                enable_auto_memory = st.checkbox("啟用自動長期記憶", value=True, key="sidebar_bottom_enable_auto_memory")

                if st.button("🧹 清除長期記憶", key="sidebar_bottom_clear_memory", use_container_width=True):
                    st.session_state.memory = default_memory()
                    save_user_memory(st.session_state.username, st.session_state.memory)
                    st.warning("長期記憶已清除！")
                    st.rerun()

            with tab_tools:
                enable_auto_tools = st.checkbox("啟用自動工具呼叫", value=True, key="sidebar_bottom_enable_auto_tools")
                st.caption("系統會先判斷是否需要 calculator、current_time、word_count 工具；需要時會自動透過 MCP-style tools/call 執行。")
                st.write("MCP tools/list")
                st.json(mcp_tools_list())

    st.title(f"🚀 {st.session_state.current_chat_id}")

    st.divider()

    st.caption("請按下方聊天輸入框左側的「＋」上傳本次對話要分析的圖片、音訊、影片、PDF、文字檔或程式檔。")

    video_frame_count = 8

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

    client = Groq(api_key=user_groq_api_key) if user_groq_api_key else None

    # --- AI 輸入邏輯 ---
    if st.session_state.regen_flag:
        st.session_state.regen_flag = False
        if len(chats) >= 2 and chats[-1].get("role") == "assistant":
            prompt_to_use = chats[-2]["content"]
            if "\n\n📎 附件：" in prompt_to_use:
                prompt_to_use = prompt_to_use.split("\n\n📎 附件：", 1)[0]
            chats.pop()
            uploaded_files = []
        else:
            prompt_to_use = None
            uploaded_files = []
            st.warning("目前沒有足夠的對話可以重新生成。")
    else:
        uploaded_files = []
        prompt_payload = st.chat_input(
            "詢問您的文件、圖片、音訊、影片或聊天...",
            accept_file="multiple",
            file_type=[
                "png", "jpg", "jpeg", "webp",
                "mp3", "wav", "m4a", "ogg", "flac",
                "mp4", "mov", "avi", "mkv", "webm",
                "pdf", "txt", "md", "csv", "json", "py", "cpp", "java", "html", "css", "js"
            ]
        )

        if prompt_payload:
            if isinstance(prompt_payload, str):
                prompt_to_use = prompt_payload
                uploaded_files = []
            else:
                prompt_to_use = getattr(prompt_payload, "text", "") or ""
                uploaded_files = list(getattr(prompt_payload, "files", []) or [])
        else:
            prompt_to_use = None
            uploaded_files = []

    if prompt_to_use:
        if client is None:
            st.warning("請先到側邊欄最下方「👤 個人設定 → API Key / 記憶 / MCP」，在 API Key 分頁輸入並加密儲存 Groq API Key，才能開始聊天。")
            st.stop()

        if len(chats) == 0:
            new_n = prompt_to_use[:10] + ("..." if len(prompt_to_use) > 10 else "")
            st.session_state.chats[new_n] = st.session_state.chats.pop(st.session_state.current_chat_id)
            st.session_state.current_chat_id = new_n
            chats = st.session_state.chats[new_n]

        tool_result = run_local_tool(prompt_to_use)
        tool_prefix = "🛠️ 手動工具執行結果"

        if tool_result is None and enable_auto_tools:
            tool_result = auto_run_mcp_tool_if_needed(client, prompt_to_use)
            tool_prefix = "🧰 自動工具 / MCP 執行結果"

        if tool_result is not None:
            chats.append({"role": "user", "content": prompt_to_use})
            chats.append({"role": "assistant", "content": f"{tool_prefix}：\n\n{tool_result}"})
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
            sys_msg += "\n\n重要：所有中文回答都必須使用繁體中文，不要使用簡體中文。"

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
