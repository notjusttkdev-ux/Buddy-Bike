"""ด่านตรวจความปลอดภัยของ Buddy Bike: ตรวจทั้งขาเข้าและขาออก (Week 11)

ลำดับการตรวจ (ของถูกและแน่นอนมาก่อน ของแพงมาทีหลัง ตามเหตุผลการออกแบบของ Llama Guard Layer)

    ขาเข้า   1) ความยาวข้อความ  2) blocklist  3) กฎ Prompt Injection  4) กฎ Sensitive Info
             5) Llama Guard 4
    ขาออก   1) blocklist  2) กฎ Prompt leak  3) กฎ PII  4) กฎ Misinformation  5) Llama Guard 4

fail-closed: ถ้าตัวตรวจตัวใดทำงานผิดพลาด ให้ถือว่า "ไม่ผ่าน" เสมอ
"""

import logging
import time
from collections import defaultdict, deque

import httpx

from ..settings import Settings
from . import rules
from .blocklist import Blocklist
from .categories import BLOCKLIST_CODE, BLOCKLIST_MESSAGE, CATEGORIES
from .llama_guard import GuardError, classify
from .rules import OK, MisinformationGuard, Verdict

log = logging.getLogger("buddybike.guard")

GUARD_DOWN = Verdict(False, "GUARD", "GUARD_UNAVAILABLE",
                     "ขออภัยครับ ระบบตรวจสอบความปลอดภัยไม่พร้อมใช้งานชั่วคราว จึงยังตอบไม่ได้ กรุณาลองใหม่อีกครั้งในอีกสักครู่", 503)


class Safety:
    def __init__(self, settings: Settings, kb_text: str, kb_ids: set[str]):
        self.settings = settings
        self.kb_text = kb_text
        self.blocklist = Blocklist(settings.blocklist_file)
        self.misinfo = MisinformationGuard(kb_text, kb_ids)
        self._hits: dict[str, deque] = defaultdict(deque)

    # ---- จำกัดจำนวนคำขอ (Unbounded Consumption) ----
    def allow_request(self, client_key: str) -> bool:
        now = time.monotonic()
        window = self._hits[client_key]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self.settings.rate_limit_per_minute:
            return False
        window.append(now)
        return True

    async def _llama_guard(self, client: httpx.AsyncClient, message: str, direction: str,
                           user_message: str | None = None) -> Verdict:
        if not self.settings.llama_guard_enabled:
            return OK
        try:
            unsafe, codes = await classify(client, self.settings, message, direction, user_message)
        except GuardError as exc:
            log.error("llama guard failed (%s): %s", direction, exc)
            return GUARD_DOWN
        if not unsafe:
            return OK
        reply = CATEGORIES[codes[0]].message if codes else BLOCKLIST_MESSAGE
        return Verdict(False, "CONTENT", "LLAMA_GUARD_" + (",".join(codes) or "UNSAFE"), reply)

    def clean_field(self, value: str | None) -> str | None:
        """คืนค่าเดิมถ้าปลอดภัย หรือ None ถ้าข้อความที่อ่านจากรูปมีคำต้องห้ามหรือมีลักษณะเป็นคำสั่งหลอก"""
        if not value:
            return None
        try:
            if self.settings.rules_guard_enabled and (self.blocklist.matches(value) or rules.field_suspicious(value)):
                return None
        except Exception:
            return None
        return value

    # ---- ขาเข้า ----
    async def check_input(self, client: httpx.AsyncClient, text: str) -> Verdict:
        s = self.settings
        try:
            if len(text) > s.max_message_chars:
                return Verdict(False, "LIMIT", "INPUT_TOO_LONG",
                               f"ข้อความยาวเกิน {s.max_message_chars} ตัวอักษร กรุณาพิมพ์คำถามให้สั้นลงครับ")
            if s.rules_guard_enabled:
                if self.blocklist.matches(text):
                    return Verdict(False, "CONTENT", BLOCKLIST_CODE, BLOCKLIST_MESSAGE)
                for check in (rules.check_prompt_injection, rules.check_sensitive_request):
                    verdict = check(text, s.shop_contact)
                    if not verdict.ok:
                        return verdict
        except Exception:
            log.exception("input rules failed")
            return GUARD_DOWN
        return await self._llama_guard(client, text, "input")

    # ---- ขาออก ----
    async def check_output(self, client: httpx.AsyncClient, answer: str, question: str, canary: str) -> Verdict:
        s = self.settings
        try:
            if s.rules_guard_enabled:
                if self.blocklist.matches(answer):
                    return Verdict(False, "CONTENT", BLOCKLIST_CODE, BLOCKLIST_MESSAGE)
                for verdict in (
                    rules.check_prompt_leak(answer, canary),
                    rules.check_pii_output(answer, self.kb_text),
                    self.misinfo.check(answer, s.shop_contact),
                ):
                    if not verdict.ok:
                        return verdict
        except Exception:
            log.exception("output rules failed")
            return GUARD_DOWN
        return await self._llama_guard(client, answer, "output", question)
