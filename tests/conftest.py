"""ตั้งค่าสำหรับ pytest: ใช้ key ปลอม และเก็บสลิปทดสอบในโฟลเดอร์ชั่วคราว (ไม่เรียก OpenRouter จริง)"""

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="buddybike-test-")
os.environ["OPENROUTER_API_KEY"] = "test-key"
os.environ["DATA_DIR"] = os.path.join(_TMP, "data")
os.environ["UPLOADS_DIR"] = os.path.join(_TMP, "uploads")
os.environ["RATE_LIMIT_PER_MINUTE"] = "1000"
os.environ["ADMIN_TOKEN"] = "staff-secret"
os.environ["PROMPT_VARIANT"] = "full"
os.environ["RULES_GUARD_ENABLED"] = "true"
os.environ["LLAMA_GUARD_ENABLED"] = "true"
os.environ["RAG_ENABLED"] = "true"
