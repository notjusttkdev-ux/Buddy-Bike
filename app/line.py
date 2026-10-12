"""ช่องทาง LINE Official Account (Messaging API)

ต่อยอดจากตัวอย่าง LINE OA x OpenRouter ของอาจารย์ โดยใช้หลักการเดิม
    1) ตรวจลายเซ็น x-line-signature ด้วย HMAC-SHA256 ก่อนเชื่อข้อมูลใด ๆ
    2) ตอบลูกค้าด้วย Reply API และแจ้งเจ้าหน้าที่ด้วย Push API (คนละข้อความ คนละ API call)
    3) ดึงชื่อที่แสดงของลูกค้าเฉพาะตอนต้องแจ้งเจ้าหน้าที่

สิ่งที่ปรับจากตัวอย่าง
    - ถ้าไม่ได้ตั้ง LINE_CHANNEL_SECRET ระบบ "ปิด" webhook (fail-closed) แทนการข้ามการตรวจลายเซ็น
    - ไม่ตั้งตัวตอบเอง: ข้อความจาก LINE ผ่านด่านความปลอดภัย RAG และ LLM ชุดเดียวกับหน้าเว็บ (ดู app/main.py)
    - รองรับรูปสลิป: ดาวน์โหลดรูปจาก LINE แล้วส่งเข้าโหมดสลิปเดียวกับหน้าเว็บ
    - บน Render เซิร์ฟเวอร์เปิดค้างไว้ จึงตอบ LINE ว่า 200 ทันที แล้วประมวลผลต่อเบื้องหลัง (BackgroundTasks)
      ต่างจากตัวอย่างบน Vercel ที่ต้องรอให้งานเสร็จก่อนตอบ เพราะเครื่องอาจถูกพักหลังส่งคำตอบ
"""

import base64
import hashlib
import hmac
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx

from .settings import Settings

log = logging.getLogger("buddybike.line")

MAX_TEXT = 4900                      # LINE จำกัดข้อความละ 5,000 ตัวอักษร
BANGKOK = timezone(timedelta(hours=7))


def verify_signature(channel_secret: str, body: bytes, signature: str | None) -> bool:
    """เทียบลายเซ็นที่ LINE ส่งมา กับลายเซ็นที่คำนวณเองจาก channel secret"""
    if not channel_secret or not signature:
        return False
    digest = hmac.new(channel_secret.encode("utf-8"), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode("utf-8"), signature)


def to_line_text(text: str) -> str:
    """LINE แสดงข้อความล้วน จึงตัดเครื่องหมายตัวหนา **...** ออก และตัดความยาวไม่ให้เกินขีดจำกัด"""
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text or "").strip()
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "..."


class LineAPI:
    """เรียก LINE Messaging API ทุกฟังก์ชันไม่โยน error ออกไป เพื่อไม่ให้ปัญหาฝั่ง LINE ทำให้ระบบล้ม"""

    def __init__(self, http: httpx.AsyncClient, settings: Settings):
        self.http = http
        self.s = settings
        self.headers = {"Authorization": f"Bearer {settings.line_channel_access_token}"}

    async def _post(self, path: str, payload: dict) -> bool:
        try:
            r = await self.http.post(f"{self.s.line_api_base}{path}", json=payload, headers=self.headers, timeout=15)
        except httpx.HTTPError as exc:
            log.error("LINE %s failed: %s", path, exc)
            return False
        if r.status_code >= 300:
            log.error("LINE %s status=%s body=%s", path, r.status_code, r.text[:300])
            return False
        return True

    async def reply(self, reply_token: str, text: str) -> bool:
        """ตอบลูกค้า ใช้ reply token ได้ครั้งเดียว และไม่นับโควตาข้อความของ LINE OA"""
        return await self._post("/v2/bot/message/reply",
                                {"replyToken": reply_token, "messages": [{"type": "text", "text": to_line_text(text)}]})

    async def push(self, to: str, text: str) -> bool:
        """ส่งข้อความหาผู้ใช้โดยตรง ใช้แจ้งเจ้าหน้าที่ (นับโควตาข้อความของ LINE OA)"""
        return await self._post("/v2/bot/message/push",
                                {"to": to, "messages": [{"type": "text", "text": to_line_text(text)}]})

    async def show_loading(self, user_id: str, seconds: int = 20) -> None:
        """แสดงภาพกำลังพิมพ์ในหน้าแชต LINE ระหว่างบอตคิด (เทียบเท่าภาพกำลังคิดบนหน้าเว็บ)"""
        await self._post("/v2/bot/chat/loading/start", {"chatId": user_id, "loadingSeconds": seconds})

    async def display_name(self, user_id: str) -> str:
        try:
            r = await self.http.get(f"{self.s.line_api_base}/v2/bot/profile/{user_id}", headers=self.headers, timeout=10)
            if r.status_code == 200:
                return r.json().get("displayName") or "ไม่ทราบชื่อ"
        except (httpx.HTTPError, ValueError) as exc:
            log.error("LINE profile failed: %s", exc)
        return "ไม่ทราบชื่อ"

    async def image_content(self, message_id: str, max_bytes: int) -> bytes | None:
        """ดาวน์โหลดรูปที่ลูกค้าส่งใน LINE คืน None ถ้าดาวน์โหลดไม่ได้ และคืน b"" ถ้าใหญ่เกินกำหนด"""
        url = f"{self.s.line_data_api_base}/v2/bot/message/{message_id}/content"
        try:
            r = await self.http.get(url, headers=self.headers, timeout=30)
        except httpx.HTTPError as exc:
            log.error("LINE content failed: %s", exc)
            return None
        if r.status_code != 200:
            log.error("LINE content status=%s", r.status_code)
            return None
        return r.content if len(r.content) <= max_bytes else b""


# --------------------------------------------------------------------------
# ข้อความแจ้งเจ้าหน้าที่
# --------------------------------------------------------------------------

def _now() -> str:
    d = datetime.now(BANGKOK)
    return f"{d.day:02d}/{d.month:02d}/{d.year + 543} {d:%H:%M} น."


def _who(channel: str, name: str | None, user_id: str | None) -> list[str]:
    if channel == "line":
        return ["ช่องทาง: LINE", f"ลูกค้า: {name or 'ไม่ทราบชื่อ'}", f"LINE userId: {user_id}"]
    return ["ช่องทาง: เว็บไซต์ (ตอบกลับลูกค้าทางนี้ไม่ได้ บอตแนะนำให้ลูกค้าติดต่อร้านแล้ว)"]


def admin_question_text(channel: str, question: str, name: str | None = None, user_id: str | None = None) -> str:
    lines = ["[Buddy Bike] คำถามที่บอตตอบไม่ได้", *_who(channel, name, user_id),
             f"คำถาม: \"{question}\"", f"เวลา: {_now()}"]
    if channel == "line":
        lines.append("ตอบลูกค้าได้ที่หน้าแชตของ LINE Official Account Manager")
    return "\n".join(lines)


def admin_slip_text(channel: str, kind: str, d: dict, name: str | None = None, user_id: str | None = None) -> str:
    """สรุปเนื้อหาสลิปให้เจ้าหน้าที่ ข้อมูลทุกช่องผ่านการกรองข้อความหลอกจากรูปมาแล้ว (clean_field)"""
    head = {"saved": "[Buddy Bike] สลิปใหม่ รอตรวจสอบยอดเงิน",
            "wrong_receiver": "[Buddy Bike] สลิปผู้รับเงินไม่ใช่บัญชีร้าน (ไม่ได้บันทึก)"}[kind]
    amount = d.get("amount")
    date = d.get("transfer_date") or ""
    if date.count("/") == 2:
        dd, mm, yy = date.split("/")
        date = f"{dd}/{mm}/{int(yy) + 543}"
    lines = [head, *_who(channel, name, user_id),
             f"ชื่อผู้โอน: {d.get('sender_name') or 'อ่านไม่ได้'}",
             f"ชื่อผู้รับ: {d.get('receiver_name') or 'อ่านไม่ได้'} ({d.get('receiver_match') or '-'}กับบัญชีร้าน)",
             f"ยอดเงิน: {amount:,.2f} บาท" if isinstance(amount, (int, float)) else "ยอดเงิน: อ่านไม่ได้",
             f"วันที่โอน: {date or 'อ่านไม่ได้'}" + (f" เวลา {d['transfer_time']} น." if d.get("transfer_time") else ""),
             f"ธนาคาร: {d.get('bank') or '-'}",
             f"เลขที่อ้างอิง: {d.get('ref_no') or '-'}",
             f"รับเมื่อ: {_now()}"]
    lines.append("กรุณาตรวจยอดเงินเข้าบัญชี แล้วยืนยันกับลูกค้า" if kind == "saved"
                 else "ลูกค้าได้รับแจ้งแล้วว่าสลิปไม่ถูกต้อง")
    return "\n".join(lines)


async def notify_admins(http: httpx.AsyncClient, settings: Settings, text: str) -> bool:
    """ส่งข้อความหาเจ้าหน้าที่ทุกคนใน LINE_ADMIN_USER_IDS คืน True ถ้าส่งถึงอย่างน้อย 1 คน"""
    if not (settings.line_channel_access_token and settings.line_admins):
        return False
    api = LineAPI(http, settings)
    sent = False
    for admin in settings.line_admins:
        sent = await api.push(admin, text) or sent
    return sent
