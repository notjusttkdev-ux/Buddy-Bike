"""เรียกโมเดลบน OpenRouter ผ่าน endpoint /chat/completions (มาตรฐาน OpenAI-compatible)

ใช้ httpx แบบ async เพื่อไม่ให้เซิร์ฟเวอร์ค้างระหว่างรอคำตอบ (Week 7)
ทั้งโมเดลตอบคำถาม โมเดลอ่านรูป และ Llama Guard เรียกผ่านฟังก์ชันเดียวกันนี้
"""

import base64

import httpx

from .settings import Settings


class LLMError(Exception):
    """error ที่แปลเป็นข้อความภาษาไทยสำหรับแสดงให้ลูกค้าแล้ว"""

    def __init__(self, code: str, message: str, status: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


# ข้อความที่ลูกค้าเห็น ไม่เปิดเผยรายละเอียดภายใน รายละเอียดจริงอยู่ใน log ของเซิร์ฟเวอร์
_STATUS_MESSAGES = {
    400: ("llm_bad_request", "ระบบส่งคำขอไปยังบริการ AI ไม่สำเร็จ กรุณาลองใหม่ หรือลองส่งรูปอื่น"),
    401: ("llm_unauthorized", "ระบบ AI ของร้านยังตั้งค่าไม่เรียบร้อย กรุณาติดต่อเจ้าหน้าที่"),
    402: ("llm_no_credit", "ระบบ AI ของร้านไม่พร้อมให้บริการชั่วคราว กรุณาติดต่อเจ้าหน้าที่"),
    403: ("llm_forbidden", "ระบบ AI ของร้านไม่พร้อมให้บริการชั่วคราว กรุณาติดต่อเจ้าหน้าที่"),
    404: ("llm_model_not_found", "ระบบ AI ของร้านยังตั้งค่าไม่เรียบร้อย กรุณาติดต่อเจ้าหน้าที่"),
    408: ("llm_timeout", "บริการ AI ใช้เวลาตอบนานเกินไป กรุณาลองใหม่อีกครั้ง"),
    429: ("llm_rate_limited", "ขณะนี้มีผู้ใช้งานจำนวนมาก กรุณารอสักครู่แล้วลองใหม่อีกครั้ง"),
    503: ("llm_unavailable", "ผู้ให้บริการ AI ไม่พร้อมให้บริการชั่วคราว กรุณาลองใหม่ภายหลัง"),
}


def image_to_data_url(data: bytes, mime: str) -> str:
    """แปลงไบต์ภาพเป็น data URL แบบ Base64 สำหรับฟิลด์ image_url (Week 10)"""
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


async def call_model(
    client: httpx.AsyncClient,
    settings: Settings,
    model: str,
    messages: list[dict],
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
) -> str:
    """ส่ง messages ไปยังโมเดลที่ระบุ แล้วคืนข้อความคำตอบ ถ้าผิดพลาดจะ raise LLMError"""
    if not settings.openrouter_api_key:
        raise LLMError("llm_not_configured", "ระบบ AI ของร้านยังตั้งค่าไม่เรียบร้อย กรุณาติดต่อเจ้าหน้าที่", 503)

    payload = {
        "model": model,
        "messages": messages,
        "temperature": settings.temperature if temperature is None else temperature,
        "max_tokens": settings.max_tokens if max_tokens is None else max_tokens,
        "stream": False,
    }
    try:
        response = await client.post(
            f"{settings.openrouter_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout or settings.request_timeout_seconds,
        )
    except httpx.TimeoutException:
        raise LLMError("llm_timeout", "บริการ AI ใช้เวลาตอบนานเกินไป กรุณาลองใหม่อีกครั้ง", 504)
    except httpx.HTTPError:
        raise LLMError("llm_unreachable", "เชื่อมต่อบริการ AI ไม่ได้ กรุณาลองใหม่อีกครั้งในอีกสักครู่", 502)

    if response.status_code != 200:
        code, message = _STATUS_MESSAGES.get(
            response.status_code, ("llm_error", "บริการ AI ขัดข้อง กรุณาลองใหม่ภายหลัง"))
        raise LLMError(code, message, 502)

    try:
        text = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError):
        raise LLMError("llm_bad_response", "บริการ AI ตอบกลับในรูปแบบที่อ่านไม่ได้ กรุณาลองใหม่อีกครั้ง", 502)

    if not isinstance(text, str) or not text.strip():
        raise LLMError("llm_empty_response", "บริการ AI ไม่ได้ส่งคำตอบกลับมา กรุณาลองใหม่อีกครั้ง", 502)
    return text.strip()
