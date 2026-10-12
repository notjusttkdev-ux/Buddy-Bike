"""Buddy Bike Chatbot: FastAPI แอปหลัก

Endpoint ทั้งหมด
    GET  /               หน้าเว็บแชต
    GET  /health         ตรวจว่าระบบพร้อม และดูการตั้งค่าที่ใช้อยู่
    POST /api/chat       รับข้อความ หรือรูปสลิป แล้วส่งคำตอบกลับ
    POST /api/reset      ล้างประวัติบทสนทนา
    GET  /api/kb/search  ดูผลการค้นคลังความรู้ (ตรวจ RAG โดยไม่เรียก LLM)
    GET  /api/slips      รายการสลิปที่บันทึกไว้ สำหรับเจ้าหน้าที่เท่านั้น (ต้องมี ADMIN_TOKEN)
    POST /line/webhook   รับข้อความและรูปสลิปจาก LINE Official Account

ลูกค้าถามได้ 2 ช่องทาง (หน้าเว็บ และ LINE) แต่ทั้งสองช่องทางใช้ลำดับการทำงานเดียวกันในฟังก์ชัน respond()
ทำให้ด่านความปลอดภัย RAG และการอ่านสลิปเหมือนกันทุกประการ
"""

import html
import json
import logging
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import BackgroundTasks, FastAPI, File, Form, Header, Query, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import line as line_module
from . import slip as slip_module
from .llm import LLMError, call_model
from .rag import KnowledgeBase, format_context
from .safety import Safety, rules
from .settings import get_settings

settings = get_settings()
logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("buddybike")

# ---- โหลดของที่ใช้ร่วมกันครั้งเดียวตอนเริ่มระบบ ----
kb = KnowledgeBase(settings.path("knowledge"))
safety = Safety(settings, kb.full_text, {c.id for c in kb.chunks})
CANARY = "BB-" + secrets.token_hex(6)      # รหัสดักจับ: ถ้าไปโผล่ในคำตอบ แปลว่า system prompt รั่ว


def _load_prompt(name: str) -> str:
    suffix = "_basic" if settings.prompt_variant == "basic" else ""
    text = (settings.path("prompts") / f"{name}{suffix}.txt").read_text(encoding="utf-8")
    return (text.replace("{shop_name}", settings.shop_name)
                .replace("{shop_contact}", settings.shop_contact)
                .replace("{canary}", CANARY))


CHAT_PROMPT = _load_prompt("chat_system")
SLIP_PROMPT = _load_prompt("slip_system")

INDEX_HTML = (
    (settings.path("static") / "index.html").read_text(encoding="utf-8")
    .replace("{{shop_name}}", html.escape(settings.shop_name))
    .replace("{{shop_contact}}", html.escape(settings.shop_contact))
    .replace("{{max_chars}}", str(settings.max_message_chars))
    .replace("{{max_image_mb}}", f"{settings.max_image_mb:g}")
)

# ---- วันเวลาปัจจุบันของร้าน ให้โมเดลแปลง "พรุ่งนี้" หรือชื่อวันเป็นวันที่จริงได้ ----
# ประเทศไทยไม่มีเวลาออมแสง ใช้ UTC+7 ตายตัว (ไม่ต้องพึ่งฐานข้อมูลเขตเวลาใน Docker)
BANGKOK = timezone(timedelta(hours=7))
_TH_DAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
_TH_MONTHS = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
              "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]


def thai_datetime(now: datetime | None = None) -> str:
    """เช่น 'วันจันทร์ที่ 12 ตุลาคม 2569 เวลา 16:09 น.' พร้อมวันที่ของ 14 วันถัดไป ช่วยให้โมเดลบวกวันได้ถูก"""
    now = now or datetime.now(BANGKOK)
    def fmt(d: datetime) -> str:
        return f"วัน{_TH_DAYS[d.weekday()]}ที่ {d.day} {_TH_MONTHS[d.month - 1]} {d.year + 543}"
    upcoming = "\n".join(f"- อีก {n} วัน: {fmt(now + timedelta(days=n))}" for n in range(1, 15))
    return f"วันนี้คือ {fmt(now)} เวลา {now:%H:%M} น.\n{upcoming}"


# ประวัติบทสนทนาเก็บในหน่วยความจำ รีสตาร์ตแล้วหาย (ข้อจำกัดเดียวกับ Week 6-7)
conversation_store: dict[str, list[dict]] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient()
    yield
    await app.state.http.aclose()


app = FastAPI(title="Buddy Bike Chatbot", lifespan=lifespan, redoc_url=None)
app.mount("/static", StaticFiles(directory=settings.path("static")), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """จำกัดสิ่งที่หน้าเว็บโหลดและรันได้ ลดผลกระทบถ้ามีโค้ดแปลกปลอมหลุดเข้ามาในคำตอบ (Improper Output Handling)"""
    response = await call_next(request)
    if not request.url.path.startswith(("/docs", "/openapi.json")):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob: data:; "
            "style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com"
        )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


# --------------------------------------------------------------------------
# ตัวช่วย
# --------------------------------------------------------------------------

def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": code, "message": message})


def _client_key(request: Request) -> str:
    """ระบุผู้ใช้สำหรับ rate limit: บน Render คำขอผ่าน proxy จึงต้องดู X-Forwarded-For ก่อน"""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _detect_image(data: bytes) -> str | None:
    """ตรวจชนิดไฟล์จากไบต์ต้นไฟล์จริง ไม่เชื่อนามสกุลหรือ header ที่ผู้ใช้ส่งมา"""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _session_id(request: Request, response: Response) -> str:
    sid = request.cookies.get("session_id", "")
    if sid not in conversation_store:
        sid = uuid.uuid4().hex
        conversation_store[sid] = []
        response.set_cookie("session_id", sid, httponly=True, samesite="lax", max_age=60 * 60 * 6)
    return sid


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(INDEX_HTML)


@app.get("/health")
async def health():
    return {
        "status": "ok", "kb_chunks": len(kb.chunks),
        "chat_model": settings.chat_model, "vision_model": settings.vision_model, "guard_model": settings.guard_model,
        "api_key_set": bool(settings.openrouter_api_key),
        "rag_enabled": settings.rag_enabled, "rag_top_k": settings.rag_top_k,
        "rules_guard": settings.rules_guard_enabled, "llama_guard": settings.llama_guard_enabled,
        "prompt_variant": settings.prompt_variant,
        "line_enabled": settings.line_enabled, "line_admins": len(settings.line_admins),
    }


@app.get("/api/kb/search")
async def kb_search(q: str = Query(..., min_length=1, max_length=200), top_k: int = Query(4, ge=1, le=10)):
    return {"query": q, "results": kb.search(q, top_k=top_k, min_score=settings.rag_min_score)}


@app.post("/api/reset")
async def reset(request: Request):
    sid = request.cookies.get("session_id", "")
    if sid in conversation_store:
        conversation_store[sid] = []
    return {"status": "cleared"}


@app.get("/api/slips")
async def list_slips(authorization: str = Header("")):
    """สำหรับเจ้าหน้าที่เท่านั้น: ต้องส่ง header  Authorization: Bearer <ADMIN_TOKEN>"""
    if not settings.admin_token:
        return _error(404, "not_enabled", "ยังไม่ได้เปิดใช้หน้ารายการสลิป (ตั้งค่า ADMIN_TOKEN ก่อน)")
    expected = f"Bearer {settings.admin_token}"
    if not secrets.compare_digest(authorization.encode(), expected.encode()):
        return _error(401, "unauthorized", "ไม่มีสิทธิ์เข้าถึงรายการสลิป")
    return {"slips": slip_module.read_slips(settings)}


# --------------------------------------------------------------------------
# ลำดับการทำงานของ 1 ข้อความ ใช้ร่วมกันทั้งหน้าเว็บและ LINE
# --------------------------------------------------------------------------

# ข้อความที่ system prompt สั่งให้ใช้เมื่อคลังความรู้ไม่มีคำตอบ ใช้ตรวจว่าต้องส่งคำถามต่อให้เจ้าหน้าที่หรือไม่
UNKNOWN_MARKER = "ยังไม่มีข้อมูลเรื่องนี้"


@dataclass
class Outcome:
    kind: str                         # chat | blocked | slip | slip_rejected | error
    reply: str
    sources: list = field(default_factory=list)
    guard: dict | None = None
    slip: dict | None = None
    status: int = 200                 # รหัส HTTP เมื่อเกิดปัญหา (เช่น 503 ตัวตรวจล่ม, 502 โมเดลล่ม)
    error: str | None = None
    unknown: bool = False             # True = คลังความรู้ไม่มีคำตอบ ต้องส่งต่อให้เจ้าหน้าที่
    question: str = ""                # คำถามที่ปิดบังเลขส่วนตัวแล้ว ใช้ส่งต่อให้เจ้าหน้าที่
    slip_result: slip_module.SlipResult | None = None


async def respond(http: httpx.AsyncClient, sid: str, message: str, image_bytes: bytes = b"", mime: str = "") -> Outcome:
    """ขั้นที่ 3–8 ของการตอบ 1 ข้อความ (ขั้นที่ 1–2 คือจำกัดคำขอและตรวจไฟล์ ทำก่อนเรียกฟังก์ชันนี้)"""

    def blocked(stage: str, verdict: rules.Verdict) -> Outcome:
        if verdict.status != 200:      # ตัวตรวจล่ม: fail-closed ไม่ตอบคำถาม
            return Outcome("error", verdict.reply, status=verdict.status, error="guard_unavailable",
                           guard={"stage": stage, "risk": verdict.risk, "code": verdict.code})
        return Outcome("blocked", verdict.reply, guard={"stage": stage, "risk": verdict.risk, "code": verdict.code})

    # ---- ขั้นที่ 3: ด่านตรวจขาเข้า (กฎในโค้ด + Llama Guard 4) ----
    if message:
        verdict = await safety.check_input(http, message)
        if not verdict.ok:
            return blocked("input", verdict)

    try:
        # ================= โหมดสลิป =================
        if image_bytes:
            result = await slip_module.process_slip(http, settings, SLIP_PROMPT, image_bytes, mime, safety.clean_field)
            saved = result.kind == "saved"
            return Outcome("slip" if saved else "slip_rejected", result.reply, slip=result.data, slip_result=result,
                           guard=None if saved else {"stage": "image", "risk": "SLIP_CHECK", "code": result.kind.upper()})

        # ================= โหมดถามตอบ =================
        # ขั้นที่ 4: ปิดบังเลขส่วนตัว และติดป้ายคำอ้างที่ยืนยันไม่ได้
        safe_message = rules.mask_pii(message) if settings.rules_guard_enabled else message
        claim_note = rules.CLAIM_NOTE if settings.rules_guard_enabled and rules.has_unverified_claim(message) else ""

        # ขั้นที่ 5: RAG ค้นคลังความรู้ (Retrieval) แล้วแนบเข้า prompt (Augmentation)
        results = kb.search(safe_message, settings.rag_top_k, settings.rag_min_score) if settings.rag_enabled else []
        context = format_context(results) if settings.rag_enabled else "(ปิดการค้นคลังความรู้)"
        sources = [{"id": r["id"], "title": r["title"]} for r in results]
        user_text = (f"<วันเวลาปัจจุบัน>\n{thai_datetime()}\n</วันเวลาปัจจุบัน>\n\n"
                     f"<ข้อมูลร้าน>\n{context}\n</ข้อมูลร้าน>\n\n"
                     f"<ข้อความลูกค้า>\n{safe_message}\n</ข้อความลูกค้า>" + (f"\n\n{claim_note}" if claim_note else ""))

        # ขั้นที่ 6: LLM เขียนคำตอบ (Generation)
        history = conversation_store.get(sid, [])
        messages = [{"role": "system", "content": CHAT_PROMPT}, *history, {"role": "user", "content": user_text}]
        answer = await call_model(http, settings, settings.chat_model, messages)

    except LLMError as exc:
        log.warning("llm error code=%s", exc.code)
        return Outcome("error", exc.message, status=exc.status, error=exc.code)

    # ---- ขั้นที่ 7: ด่านตรวจขาออก (กฎในโค้ด + Llama Guard 4) ----
    verdict = await safety.check_output(http, answer, safe_message, CANARY)
    if not verdict.ok:
        return blocked("output", verdict)

    # ---- ขั้นที่ 8: เก็บประวัติ (ข้อความที่ปิดบังเลขแล้ว) และตอบกลับ ----
    history = history + [{"role": "user", "content": safe_message}, {"role": "assistant", "content": answer}]
    conversation_store[sid] = history[-settings.history_max_messages:]
    return Outcome("chat", answer, sources=sources, unknown=UNKNOWN_MARKER in answer, question=safe_message)


async def alert_staff(outcome: Outcome, channel: str, name: str | None = None, user_id: str | None = None) -> bool:
    """ขั้นที่ 9: แจ้งเจ้าหน้าที่ทาง LINE เมื่อบอตตอบไม่ได้ หรือมีสลิปเข้ามา คืน True ถ้าส่งถึงเจ้าหน้าที่"""
    if channel == "web" and not settings.line_notify_web:
        return False
    text = None
    if outcome.kind == "chat" and outcome.unknown:
        text = line_module.admin_question_text(channel, outcome.question, name, user_id)
    elif outcome.slip_result and outcome.slip_result.kind in ("saved", "wrong_receiver"):
        text = line_module.admin_slip_text(channel, outcome.slip_result.kind, outcome.slip_result.details or {},
                                           name, user_id)
    if not text:
        return False
    try:
        return await line_module.notify_admins(app.state.http, settings, text)
    except Exception:                  # การแจ้งเจ้าหน้าที่ล้มเหลวต้องไม่กระทบคำตอบของลูกค้า
        log.exception("alert staff failed")
        return False


# --------------------------------------------------------------------------
# ช่องทางที่ 1: หน้าเว็บ
# --------------------------------------------------------------------------

@app.post("/api/chat")
async def chat(
    request: Request,
    response: Response,
    background: BackgroundTasks,
    message: str = Form(""),
    image: UploadFile | None = File(None),
):
    started = time.perf_counter()
    http: httpx.AsyncClient = request.app.state.http

    # ---- ขั้นที่ 1: จำกัดจำนวนคำขอ ----
    if not safety.allow_request(_client_key(request)):
        return _error(429, "rate_limited", "คุณส่งข้อความถี่เกินไป กรุณารอประมาณ 1 นาทีแล้วลองใหม่ครับ")

    message = message.strip()
    has_image = image is not None and bool(image.filename)
    if not message and not has_image:
        return _error(400, "empty_message", "กรุณาพิมพ์คำถาม หรือแนบรูปสลิปก่อนส่งครับ")

    # ---- ขั้นที่ 2: ตรวจไฟล์ภาพ (ขนาดและชนิด) ----
    image_bytes, mime = b"", ""
    if has_image:
        max_bytes = int(settings.max_image_mb * 1024 * 1024)
        image_bytes = await image.read(max_bytes + 1)
        if len(image_bytes) > max_bytes:
            return _error(413, "image_too_large", f"รูปมีขนาดเกิน {settings.max_image_mb:g} MB กรุณาส่งรูปที่เล็กลงครับ")
        if not image_bytes:
            return _error(400, "empty_image", "ไฟล์รูปว่างเปล่าหรืออ่านไม่ได้ กรุณาเลือกรูปใหม่ครับ")
        mime = _detect_image(image_bytes) or ""
        if not mime:
            return _error(415, "unsupported_image", "ไฟล์นี้ไม่ใช่รูปภาพที่รองรับ กรุณาส่งรูป JPG, PNG หรือ WEBP ครับ")

    sid = _session_id(request, response)
    out = await respond(http, sid, message, image_bytes, mime)
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    # log เฉพาะข้อมูลกำกับ ไม่บันทึกข้อความหรือชื่อของลูกค้า (PDPA)
    log.info("chat channel=web sid=%s mode=%s type=%s guard=%s sources=%s ms=%d", sid[:8],
             "slip" if image_bytes else "chat", out.kind, (out.guard or {}).get("code", "-"),
             ",".join(x["id"] for x in out.sources) or "-", elapsed_ms)
    if out.kind == "error":
        return _error(out.status, out.error or "error", out.reply)

    # ขั้นที่ 9: แจ้งเจ้าหน้าที่ทาง LINE หลังส่งคำตอบให้ลูกค้าแล้ว ลูกค้าจึงไม่ต้องรอ
    background.add_task(alert_staff, out, "web")
    return {"type": out.kind, "reply": out.reply, "sources": out.sources, "guard": out.guard, "slip": out.slip,
            "elapsed_ms": elapsed_ms}


# --------------------------------------------------------------------------
# ช่องทางที่ 2: LINE Official Account
# --------------------------------------------------------------------------

LINE_UNSUPPORTED = "น้องบัดดี้ตอบได้เฉพาะข้อความ และรูปสลิปการโอนเงินครับ ลองพิมพ์คำถามเกี่ยวกับการเช่ารถได้เลยครับ"
LINE_WELCOME = ("สวัสดีครับ ผมน้องบัดดี้ ผู้ช่วย AI ของร้าน Buddy Bike Ride Now ยินดีช่วยตอบเรื่องรถ ราคา และเงื่อนไขการเช่าครับ\n"
                "พิมพ์คำถามได้เลย หรือส่งรูปสลิปหลังโอนเงินจอง/มัดจำ เพื่อให้เจ้าหน้าที่ตรวจสอบครับ")
LINE_FORWARDED = "ผมส่งคำถามนี้ให้เจ้าหน้าที่แล้วครับ เจ้าหน้าที่จะตอบกลับในแชตนี้ในเวลาทำการ 08:00–20:00 น."
LINE_SLIP_FORWARDED = "ผมส่งข้อมูลสลิปให้เจ้าหน้าที่ตรวจสอบแล้วครับ"


@app.post("/line/webhook")
async def line_webhook(request: Request, background: BackgroundTasks):
    """LINE ยิงข้อความของลูกค้ามาที่นี่ ตรวจลายเซ็นแล้วตอบ 200 ทันที จากนั้นประมวลผลต่อเบื้องหลัง

    LINE ต้องการให้ webhook ตอบกลับเร็ว ส่วนการเรียกโมเดลอาจใช้เวลาหลายวินาที
    บน Render เซิร์ฟเวอร์เปิดค้างไว้ งานเบื้องหลังจึงทำงานต่อจนจบได้หลังส่งคำตอบให้ LINE แล้ว
    """
    if not settings.line_enabled:
        return _error(503, "line_not_configured", "ยังไม่ได้ตั้งค่า LINE_CHANNEL_SECRET และ LINE_CHANNEL_ACCESS_TOKEN")
    body = await request.body()
    if not line_module.verify_signature(settings.line_channel_secret, body, request.headers.get("x-line-signature")):
        log.warning("line webhook: invalid signature")
        return _error(403, "invalid_signature", "ลายเซ็นไม่ถูกต้อง")
    try:
        events = (json.loads(body) or {}).get("events", [])
    except ValueError:
        return _error(400, "invalid_json", "รูปแบบข้อมูลไม่ถูกต้อง")
    for event in events:
        background.add_task(handle_line_event, event)
    return PlainTextResponse("OK")


async def handle_line_event(event: dict) -> None:
    http: httpx.AsyncClient = app.state.http
    api = line_module.LineAPI(http, settings)
    source = event.get("source") or {}
    user_id = source.get("userId")
    token = event.get("replyToken")
    if source.get("type") != "user" or not user_id or not token:
        return                         # ตอบเฉพาะแชตส่วนตัวกับลูกค้า ไม่ตอบในกลุ่ม

    async def send(text: str) -> None:
        if not await api.reply(token, text):      # reply token หมดอายุ → ส่งแบบ push แทน
            await api.push(user_id, text)

    try:
        if event.get("type") == "follow":
            await send(LINE_WELCOME)
            return
        if event.get("type") != "message":
            return
        msg = event.get("message") or {}
        mtype = msg.get("type")

        if mtype == "text" and msg.get("text", "").strip().lower() in ("myid", "/myid"):
            await send(f"LINE userId ของคุณคือ\n{user_id}\n(ใช้ตั้งค่า LINE_ADMIN_USER_IDS สำหรับเจ้าหน้าที่)")
            return
        if mtype not in ("text", "image"):
            await send(LINE_UNSUPPORTED)
            return

        # ---- ขั้นที่ 1: จำกัดจำนวนคำขอต่อผู้ใช้ LINE ----
        if not safety.allow_request(f"line:{user_id}"):
            await send("คุณส่งข้อความถี่เกินไป กรุณารอประมาณ 1 นาทีแล้วลองใหม่ครับ")
            return
        await api.show_loading(user_id)

        # ---- ขั้นที่ 2: ข้อความ หรือดาวน์โหลดรูปจาก LINE แล้วตรวจชนิดและขนาด ----
        message, image_bytes, mime = "", b"", ""
        if mtype == "text":
            message = msg.get("text", "").strip()
        else:
            max_bytes = int(settings.max_image_mb * 1024 * 1024)
            image_bytes = await api.image_content(msg.get("id", ""), max_bytes)
            if image_bytes is None:
                await send("ขออภัยครับ ระบบดาวน์โหลดรูปจาก LINE ไม่สำเร็จ กรุณาส่งรูปสลิปอีกครั้งครับ")
                return
            if not image_bytes:
                await send(f"รูปมีขนาดเกิน {settings.max_image_mb:g} MB กรุณาส่งรูปที่เล็กลงครับ")
                return
            mime = _detect_image(image_bytes) or ""
            if not mime:
                await send("ไฟล์นี้ไม่ใช่รูปภาพที่รองรับ กรุณาส่งรูปสลิป JPG, PNG หรือ WEBP ครับ")
                return

        # ---- ขั้นที่ 3–8: ลำดับเดียวกับหน้าเว็บ (ประวัติสนทนาแยกตามผู้ใช้ LINE) ----
        started = time.perf_counter()
        out = await respond(http, f"line:{user_id}", message, image_bytes, mime)
        log.info("chat channel=line mode=%s type=%s guard=%s ms=%d", "slip" if image_bytes else "chat", out.kind,
                 (out.guard or {}).get("code", "-"), round((time.perf_counter() - started) * 1000))

        # ---- ขั้นที่ 9: แจ้งเจ้าหน้าที่ก่อน เพื่อบอกลูกค้าได้ว่าส่งต่อสำเร็จหรือไม่ ----
        reply = out.reply
        if (out.kind == "chat" and out.unknown) or (out.slip_result and out.slip_result.kind == "saved"):
            name = await api.display_name(user_id)
            if await alert_staff(out, "line", name, user_id):
                reply += "\n\n" + (LINE_FORWARDED if out.kind == "chat" else LINE_SLIP_FORWARDED)
        elif out.slip_result and out.slip_result.kind == "wrong_receiver":
            await alert_staff(out, "line", await api.display_name(user_id), user_id)
        await send(reply)
    except Exception:
        log.exception("line event failed")
        await send("ขออภัยครับ ระบบขัดข้องชั่วคราว กรุณาลองใหม่อีกครั้ง หรือติดต่อเจ้าหน้าที่ " + settings.shop_contact)
