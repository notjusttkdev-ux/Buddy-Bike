"""การตั้งค่าทั้งหมดของระบบ อ่านจาก .env หรือ Environment Variables (เช่น บน Render)

ใช้ pydantic-settings แบบเดียวกับโปรเจกต์ Llama Guard Layer ของอาจารย์
ชื่อตัวแปรใน .env เป็นตัวพิมพ์ใหญ่ เช่น OPENROUTER_API_KEY, CHAT_MODEL
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    # ---- OpenRouter ----
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    chat_model: str = "openai/gpt-4o-mini"              # ตอบคำถาม: ราคาถูก ตอบภาษาไทยได้ดี
    vision_model: str = "google/gemini-2.5-flash"        # อ่านสลิป: รับรูปภาพและอ่านตัวอักษรไทยได้
    guard_model: str = "meta-llama/llama-guard-4-12b"    # ด่านตรวจความปลอดภัย (Week 11)
    request_timeout_seconds: float = 60.0
    guard_timeout_seconds: float = 20.0
    temperature: float = 0.2
    max_tokens: int = 600

    # ---- ข้อมูลร้าน (ข้อมูลจำลอง) ----
    shop_name: str = "Buddy Bike — Ride Now!"
    shop_contact: str = "โทร 02-000-0000 หรือ LINE @buddybike-demo (ทุกวัน 08:00–20:00 น.)"
    shop_account_name: str = "บัดดี้ ไบค์ ไรด์นาว"

    # ---- RAG ----
    rag_enabled: bool = True
    rag_top_k: int = 4
    rag_min_score: float = 0.06

    # ---- Safety ----
    rules_guard_enabled: bool = True      # กฎในโค้ด: Prompt Injection, Sensitive Info, Misinformation
    llama_guard_enabled: bool = True      # Llama Guard 4 ตรวจขาเข้าและขาออก
    blocklist_path: str = "blocklist.txt"
    max_message_chars: int = 500
    rate_limit_per_minute: int = 15
    max_image_mb: float = 5.0
    history_max_messages: int = 6
    admin_token: str = ""                 # ใช้เปิดดูรายการสลิปของเจ้าหน้าที่ ถ้าว่าง = ปิด endpoint นี้

    # ---- ที่เก็บข้อมูลสลิป (บน Render ชี้ไปที่ persistent disk ได้ เช่น /var/data) ----
    data_dir: str = "data"
    uploads_dir: str = "uploads"

    # ---- LINE Official Account (Messaging API) ----
    # เว้นว่าง LINE_CHANNEL_SECRET หรือ LINE_CHANNEL_ACCESS_TOKEN = ปิดช่องทาง LINE (webhook ตอบ 503)
    line_channel_secret: str = ""
    line_channel_access_token: str = ""
    line_admin_user_ids: str = ""          # userId ของเจ้าหน้าที่ที่รับแจ้งเตือน คั่นหลายคนด้วย ,
    line_notify_web: bool = True           # แจ้งเจ้าหน้าที่ด้วย เมื่อคำถามหรือสลิปมาจากหน้าเว็บ
    line_api_base: str = "https://api.line.me"
    line_data_api_base: str = "https://api-data.line.me"

    @property
    def line_enabled(self) -> bool:
        return bool(self.line_channel_secret and self.line_channel_access_token)

    @property
    def line_admins(self) -> list[str]:
        return [u.strip() for u in self.line_admin_user_ids.split(",") if u.strip()]

    # ---- Prompt: full = ใช้งานจริง, basic = ฉบับสั้นสำหรับเทียบผลก่อนปรับปรุง ----
    prompt_variant: str = "full"

    # ---- Server ----
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"

    def path(self, name: str) -> Path:
        return BASE_DIR / name

    @property
    def blocklist_file(self) -> Path:
        p = Path(self.blocklist_path)
        return p if p.is_absolute() else BASE_DIR / p


@lru_cache
def get_settings() -> Settings:
    return Settings()
