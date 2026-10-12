"""เรียก Llama Guard 4 ผ่าน OpenRouter และแปลผล (ดัดแปลงจาก app/guard.py ของอาจารย์)

Llama Guard ตอบกลับเป็นข้อความสั้น ๆ สองแบบ
    safe
    unsafe\nS1,S10        (บรรทัดที่สองคือรหัสหมวดที่ผิด)

ข้อจำกัดที่ต้องรู้ (สไลด์ Week 11): Llama Guard ตรวจ "เนื้อหาไม่เหมาะสม" เท่านั้น
ไม่ได้ออกแบบมาจับ prompt injection หรือข้อมูลเท็จ ทั้งสองเรื่องนั้นระบบนี้ใช้กฎใน rules.py
"""

import re

import httpx

from ..llm import LLMError, call_model
from ..settings import Settings
from .categories import CATEGORIES

_CODE_RE = re.compile(r"S\d{1,2}", re.IGNORECASE)


class GuardError(Exception):
    """เรียก Llama Guard ไม่สำเร็จ หรืออ่านผลไม่ได้ ผู้เรียกต้องถือว่า "ไม่ผ่าน" (fail-closed)"""


def build_messages(message: str, direction: str, user_message: str | None = None) -> list[dict[str, str]]:
    """input = ข้อความผู้ใช้, output = คำตอบของบอต

    ตอนตรวจ output จะแนบคำถามของผู้ใช้ไปด้วยถ้ามี เพื่อให้โมเดลเห็นบริบทของคำตอบ
    """
    if direction == "input":
        return [{"role": "user", "content": message}]
    if user_message:
        return [{"role": "user", "content": user_message}, {"role": "assistant", "content": message}]
    return [{"role": "assistant", "content": message}]


def parse_verdict(raw: str) -> tuple[bool, list[str]]:
    """คืน (is_unsafe, [รหัสหมวด]) จากผลของ Llama Guard"""
    lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
    if not lines:
        raise GuardError("ผลจาก Llama Guard ว่างเปล่า")
    verdict = lines[0].lower()
    if verdict == "safe":
        return False, []
    if verdict == "unsafe":
        return True, [c.upper() for c in _CODE_RE.findall(" ".join(lines[1:]))]
    raise GuardError(f"อ่านผลจาก Llama Guard ไม่ได้: {raw[:100]!r}")


def pick_blocked(codes: list[str]) -> list[str]:
    """เลือกเฉพาะหมวดที่ตั้งให้บล็อกใน categories.py"""
    return [c for c in codes if c in CATEGORIES and CATEGORIES[c].blocked]


async def classify(
    client: httpx.AsyncClient, settings: Settings, message: str, direction: str, user_message: str | None = None
) -> tuple[bool, list[str]]:
    """คืน (unsafe_ตามหมวดที่บล็อก, [รหัสหมวดที่บล็อก])"""
    try:
        raw = await call_model(
            client, settings, settings.guard_model,
            build_messages(message, direction, user_message),
            temperature=0, max_tokens=20, timeout=settings.guard_timeout_seconds,
        )
    except LLMError as exc:
        raise GuardError(f"เรียก Llama Guard ไม่สำเร็จ: {exc.code}") from exc

    is_unsafe, codes = parse_verdict(raw)
    if not is_unsafe:
        return False, []
    blocked = pick_blocked(codes)
    # unsafe แต่ไม่ระบุหมวดเลย: ถือว่าไม่ผ่านไว้ก่อน (fail-closed)
    if not codes:
        return True, []
    return bool(blocked), blocked
