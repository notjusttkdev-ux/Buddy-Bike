"""อ่านสลิปการโอนเงินด้วย Vision LLM แล้วบันทึกลง CSV ให้เจ้าหน้าที่ตรวจสอบ

ต่อยอดจากตัวอย่าง "แชตบอตอ่านใบเสร็จ" ของอาจารย์ (Week 10) โดยใช้เทคนิคเดิม 4 อย่าง
    1) ให้โมเดลตอบเป็น JSON  2) แกะ JSON แบบทนทาน  3) ลองใหม่ 1 ครั้งถ้าตอบผิดรูปแบบ
    4) normalize วันที่ (พ.ศ. -> ค.ศ.) และจำนวนเงินด้วยโค้ด ไม่เชื่อโมเดลอย่างเดียว

สิ่งที่เพิ่มเพื่อความปลอดภัย
    - ตรวจว่าเป็นสลิปจริงหรือไม่ ทั้งจากโมเดลและจากโค้ด (กันการส่งรูปมั่ว)
    - รับเฉพาะสลิปที่ชื่อผู้รับเงินเป็นชื่อบัญชีของร้าน (SHOP_ACCOUNT_NAME) ชื่ออื่นถือว่าสลิปไม่ถูกต้อง
    - ข้อความตอบลูกค้าสร้างจากโค้ด ไม่ใช่ข้อความอิสระของโมเดล บอตจึงยืนยันการชำระเงินไม่ได้
      แม้ในรูปจะมีข้อความหลอกให้ยืนยันก็ตาม
    - CSV เป็นบันทึกของเจ้าหน้าที่เท่านั้น ไม่ถูกแนบเข้าแชต ลูกค้าจึงถามข้อมูลการโอนของคนอื่นไม่ได้
    - ไม่เก็บเลขบัญชี
"""

import csv
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import httpx

from .llm import call_model, image_to_data_url
from .safety.blocklist import squash
from .settings import Settings

CSV_COLUMNS = ["saved_at", "transfer_date", "transfer_time", "amount", "sender_name", "receiver_name",
               "receiver_match", "bank", "ref_no", "status", "source_image"]
STATUS_PENDING = "รอเจ้าหน้าที่ตรวจสอบ"
MAX_AMOUNT = 1_000_000

# ภาพที่อ่านไม่ได้ ต้องตอบว่า "ขอรูปใหม่" ไม่ใช่ "ไม่ใช่สลิป"
BAD_QUALITY = {
    "blurry": "รูปเบลอ",
    "dark": "รูปมืดหรือสว่างเกินไป",
    "cropped": "รูปถูกตัดหรือถูกบดบัง",
}
# สำรองไว้กรณีโมเดลไม่ได้ใส่ image_quality แต่เขียนเหตุผลว่าภาพไม่ชัด
_UNCLEAR_REASON = re.compile(r"เบลอ|มืด|ไม่ชัด|อ่านไม่ออก|อ่านไม่ได้|มองไม่เห็น|ไม่โฟกัส|blur|dark|unreadable|illegible|low.?quality",
                             re.IGNORECASE)

RETRY_INSTRUCTION = "กรุณาตอบใหม่เป็น JSON object เดียวเท่านั้น ห้ามมีข้อความอื่นล้อมรอบ"


@dataclass
class SlipResult:
    kind: str                 # saved | not_slip | unreadable | wrong_receiver | duplicate
    reply: str                # ข้อความตอบลูกค้า (โค้ดสร้างเอง)
    data: dict | None = None  # ข้อมูลที่ส่งให้หน้าเว็บแสดงการ์ดสลิป
    details: dict | None = None   # ข้อมูลเต็มสำหรับแจ้งเจ้าหน้าที่ทาง LINE เท่านั้น ไม่ส่งให้ลูกค้า


# --------------------------------------------------------------------------
# แกะและทำความสะอาดคำตอบของโมเดล
# --------------------------------------------------------------------------

def parse_json(raw: str) -> dict | None:
    """ดึง JSON object ออกจากคำตอบของโมเดล แม้จะมีข้อความหรือ code fence ปนมา"""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"```$", "", text).strip()
    for candidate in (text, (re.search(r"\{.*\}", text, re.DOTALL) or [None])[0]):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def clean_text(value, max_len: int = 80) -> str | None:
    """ตัดช่องว่าง ขึ้นบรรทัดใหม่ และจำกัดความยาว กันข้อความแปลกปลอมจากในรูป"""
    if value is None:
        return None
    v = re.sub(r"\s+", " ", str(value)).strip()
    if v.lower() in ("null", "none", "", "-"):
        return None
    return v[:max_len]


def normalize_date(value) -> str | None:
    """คืนวันที่รูปแบบ DD/MM/YYYY (ค.ศ.) หรือ None ถ้าไม่ใช่วันที่จริง

    สลิปไทยเขียนปีเป็น พ.ศ. ทั้งแบบ 4 หลัก (2569) และ 2 หลัก (69)
    - ปี 4 หลักที่มากกว่า 2400 ถือเป็น พ.ศ. ให้ลบ 543
    - ปี 2 หลักตั้งแต่ 40 ขึ้นไป ถือเป็น พ.ศ. 25xx (เช่น 69 -> 2569 -> 2026) น้อยกว่านั้นถือเป็น ค.ศ. 20xx
    """
    v = clean_text(value, 20)
    if not v:
        return None
    m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})$", v)
    if not m:
        return None
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if year < 100:
        year = 2500 + year if year >= 40 else 2000 + year
    if year > 2400:
        year -= 543
    try:
        parsed = date(year, month, day)
    except ValueError:
        return None
    if not (2000 <= parsed.year <= date.today().year + 1):
        return None
    return f"{day:02d}/{month:02d}/{year:04d}"


def normalize_time(value) -> str | None:
    v = clean_text(value, 12)
    m = re.match(r"^(\d{1,2})[:.](\d{2})", v or "")
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def normalize_amount(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        amount = float(value)
    else:
        v = str(value).replace(",", "").replace("บาท", "").replace("฿", "").replace("THB", "").strip()
        try:
            amount = float(v)
        except ValueError:
            return None
    return round(amount, 2) if 0 < amount <= MAX_AMOUNT else None


# คำนำหน้าที่แอปธนาคารอาจใส่ไว้หน้าชื่อบัญชี ตัดออกก่อนเทียบ
_NAME_PREFIX = re.compile(r"^(นาย|นางสาว|นาง|น\.ส\.|ร้าน|บจก\.|หจก\.|บริษัท|mr\.|mrs\.|ms\.|miss)\s*", re.IGNORECASE)
_NAME_NOISE = re.compile(r"[\s.\-_,()\[\]'\"“”]+")


def _name_key(name: str) -> str:
    return _NAME_NOISE.sub("", _NAME_PREFIX.sub("", squash(name)))


def receiver_matches(receiver: str | None, shop_account_name: str) -> str:
    """เทียบชื่อผู้รับเงินในสลิปกับชื่อบัญชีร้าน คืน ตรง / ไม่ตรง / อ่านไม่ได้

    ต้องพบชื่อบัญชีของร้าน "ครบทั้งชื่อ" ในชื่อผู้รับ จึงถือว่าตรง ไม่ยอมรับชื่อที่ตรงแค่บางส่วน เช่น "บัดดี้"
    ไม่สนใจช่องว่าง จุด ขีด ตัวพิมพ์เล็กใหญ่ และคำนำหน้า เช่น "ร้าน" หรือ "บจก."
    ถ้าร้านมีชื่อบัญชีหลายแบบ (เช่น ชื่อภาษาอังกฤษ) ใส่ใน SHOP_ACCOUNT_NAME โดยคั่นด้วย |
    """
    if not receiver or not _name_key(receiver):
        return "อ่านไม่ได้"
    got = _name_key(receiver)
    names = [_name_key(n) for n in shop_account_name.split("|") if _name_key(n)]
    return "ตรง" if any(n in got for n in names) else "ไม่ตรง"


# --------------------------------------------------------------------------
# CSV (บันทึกของเจ้าหน้าที่)
# --------------------------------------------------------------------------

def _csv_path(settings: Settings) -> Path:
    return settings.path(settings.data_dir) / "slips.csv"


def ensure_csv(settings: Settings) -> Path:
    """สร้างไฟล์พร้อมหัวคอลัมน์ถ้ายังไม่มี เขียน BOM ครั้งเดียวตอนสร้าง เพื่อให้ Excel เปิดภาษาไทยได้"""
    path = _csv_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f).writerow(CSV_COLUMNS)
    return path


def read_slips(settings: Settings) -> list[dict]:
    path = ensure_csv(settings)
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: r.get("saved_at", ""), reverse=True)
    return rows


def _csv_safe(value) -> str:
    """กัน CSV injection: ถ้าขึ้นต้นด้วยอักขระสูตร ให้เติม ' นำหน้า เพื่อไม่ให้ Excel รันเป็นสูตร"""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def append_slip(settings: Settings, row: dict) -> None:
    path = ensure_csv(settings)
    with open(path, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([_csv_safe(row.get(col)) for col in CSV_COLUMNS])


def is_duplicate(settings: Settings, ref_no: str | None) -> bool:
    if not ref_no:
        return False
    return any(r.get("ref_no", "").lstrip("'") == ref_no for r in read_slips(settings))


# --------------------------------------------------------------------------
# ขั้นตอนหลัก
# --------------------------------------------------------------------------

def _thai_date(ddmmyyyy: str) -> str:
    d, m, y = ddmmyyyy.split("/")
    return f"{d}/{m}/{y} (พ.ศ. {int(y) + 543})"


async def process_slip(client: httpx.AsyncClient, settings: Settings, system_prompt: str,
                       image_bytes: bytes, mime: str, clean_field=lambda value: value) -> SlipResult:
    """clean_field คือฟังก์ชันของด่านความปลอดภัย ใช้ทิ้งข้อความจากรูปที่มีลักษณะเป็นคำสั่งหลอก"""
    contact = settings.shop_contact
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": [
            {"type": "text", "text": "กรุณาตรวจและอ่านข้อมูลจากภาพนี้"},
            {"type": "image_url", "image_url": {"url": image_to_data_url(image_bytes, mime)}},
        ]},
    ]

    # ---- เรียก Vision LLM และลองใหม่ 1 ครั้งถ้าไม่ได้ JSON ----
    raw = await call_model(client, settings, settings.vision_model, messages, temperature=0, max_tokens=400)
    parsed = parse_json(raw)
    if parsed is None:
        retry = messages + [{"role": "assistant", "content": raw}, {"role": "user", "content": RETRY_INSTRUCTION}]
        parsed = parse_json(await call_model(client, settings, settings.vision_model, retry, temperature=0, max_tokens=400))
    if parsed is None:
        return SlipResult("unreadable",
                          "ระบบอ่านข้อมูลจากรูปนี้ไม่ได้ครับ กรุณาส่งรูปสลิปอีกครั้ง โดยให้เห็นทั้งใบและตัวหนังสือชัดเจน "
                          f"หรือติดต่อเจ้าหน้าที่ {contact}")

    # ---- ด่านที่ 1: ภาพไม่ชัดจนตัดสินไม่ได้ ต้องขอรูปใหม่ ไม่ใช่ตอบว่าไม่ใช่สลิป ----
    quality = str(parsed.get("image_quality") or "").strip().lower()
    # ใช้เหตุผลเป็นตัวช่วยเฉพาะเมื่อโมเดลไม่ได้ระบุ image_quality มา (เช่น prompt แบบ basic)
    unclear = quality in BAD_QUALITY or (not quality
                                         and bool(_UNCLEAR_REASON.search(str(parsed.get("reason") or ""))))
    if parsed.get("is_slip") is not True and unclear:
        problem = BAD_QUALITY.get(quality, "รูปไม่ชัด")
        return SlipResult("unreadable",
                          f"ระบบอ่านรูปนี้ไม่ได้ครับ ({problem}) จึงยังไม่ได้บันทึก "
                          "กรุณาส่งรูปสลิปใหม่ที่ชัด ไม่มืด ไม่เบลอ และเห็นครบทั้งใบ "
                          "แนะนำให้บันทึกภาพหน้าจอจากแอปธนาคารแทนการถ่ายรูปหน้าจอ "
                          f"หรือติดต่อเจ้าหน้าที่ {contact}")

    # ---- ด่านที่ 2: โมเดลบอกว่าไม่ใช่สลิป ----
    if parsed.get("is_slip") is not True:
        return SlipResult("not_slip",
                          "รูปนี้ไม่ใช่สลิปการโอนเงินครับ ระบบจึงไม่ได้บันทึก "
                          "กรุณาส่งรูปสลิปที่ได้จากแอปธนาคารหลังโอนเงินสำเร็จ โดยให้เห็นยอดเงิน วันที่ และชื่อผู้รับเงินครบถ้วน")

    amount = normalize_amount(parsed.get("amount"))
    transfer_date = normalize_date(parsed.get("transfer_date"))
    transfer_time = normalize_time(parsed.get("transfer_time"))
    sender = clean_field(clean_text(parsed.get("sender_name")))
    receiver = clean_field(clean_text(parsed.get("receiver_name")))
    bank = clean_field(clean_text(parsed.get("bank"), 40))
    ref_no = clean_field(clean_text(parsed.get("ref_no"), 40))

    # ---- ด่านที่ 3: โค้ดตรวจซ้ำ สลิปจริงต้องมียอดเงิน วันที่ และข้อมูลระบุรายการอย่างน้อย 1 อย่าง ----
    if amount is None or transfer_date is None or not (sender or receiver or ref_no):
        missing = [name for name, value in (("ยอดเงิน", amount), ("วันที่โอน", transfer_date)) if value is None]
        if quality in BAD_QUALITY:
            missing.append(BAD_QUALITY[quality])
        return SlipResult("unreadable",
                          "ระบบอ่านสลิปนี้ได้ไม่ครบครับ" + (f" (อ่านไม่ได้: {', '.join(missing)})" if missing else "")
                          + " จึงยังไม่ได้บันทึก กรุณาถ่ายหรือบันทึกภาพสลิปใหม่ให้ชัด ไม่มืด ไม่เบลอ และเห็นครบทั้งใบ "
                          f"หรือติดต่อเจ้าหน้าที่ {contact}")

    # ---- ด่านที่ 4: ผู้รับเงินต้องเป็นบัญชีของร้านเท่านั้น ----
    shop_name = settings.shop_account_name.split("|")[0].strip()
    match = receiver_matches(receiver, settings.shop_account_name)
    if match == "อ่านไม่ได้":
        return SlipResult("unreadable",
                          "ระบบอ่านชื่อผู้รับเงินในสลิปนี้ไม่ได้ครับ จึงยังตรวจไม่ได้ว่าโอนเข้าบัญชีของร้านหรือไม่ และยังไม่ได้บันทึก "
                          "กรุณาส่งรูปสลิปใหม่ที่เห็นชื่อผู้รับเงินชัดเจน "
                          f"หรือติดต่อเจ้าหน้าที่ {contact}")
    details = {"sender_name": sender, "receiver_name": receiver, "receiver_match": match, "amount": amount,
               "transfer_date": transfer_date, "transfer_time": transfer_time, "bank": bank, "ref_no": ref_no}
    if match == "ไม่ตรง":
        return SlipResult("wrong_receiver",
                          f"สลิปไม่ถูกต้องครับ ชื่อผู้รับเงินในสลิปคือ \"{receiver}\" ซึ่งไม่ใช่บัญชีของร้าน ระบบจึงไม่ได้บันทึกสลิปนี้\n"
                          f"บัญชีรับเงินของร้านมีบัญชีเดียว คือ ชื่อบัญชี {shop_name}\n"
                          "หากโอนเข้าบัญชีอื่นไปแล้ว กรุณาติดต่อธนาคารของคุณ "
                          f"และหากระบบอ่านชื่อผิด กรุณาส่งรูปที่ชัดขึ้นหรือติดต่อเจ้าหน้าที่ {contact}",
                          details=details)

    # ---- ด่านที่ 5: สลิปซ้ำ ----
    if is_duplicate(settings, ref_no):
        return SlipResult("duplicate",
                          f"สลิปเลขที่อ้างอิง {ref_no} เคยส่งเข้ามาแล้วครับ ระบบจึงไม่บันทึกซ้ำ "
                          f"หากต้องการสอบถามผลการตรวจสอบ กรุณาติดต่อเจ้าหน้าที่ {contact}")

    # ---- บันทึกภาพต้นฉบับและ CSV ----
    now = datetime.now()
    ext = {"image/png": ".png", "image/webp": ".webp"}.get(mime, ".jpg")
    source_image = now.strftime("%Y%m%d-%H%M%S-%f") + ext      # ตั้งชื่อใหม่ ไม่ใช้ชื่อไฟล์จากผู้ใช้
    uploads = settings.path(settings.uploads_dir)
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / source_image).write_bytes(image_bytes)

    row = {
        "saved_at": now.strftime("%Y-%m-%d %H:%M:%S.%f"), "transfer_date": transfer_date,
        "transfer_time": transfer_time or "", "amount": f"{amount:.2f}", "sender_name": sender or "",
        "receiver_name": receiver or "", "receiver_match": match, "bank": bank or "", "ref_no": ref_no or "",
        "status": STATUS_PENDING, "source_image": source_image,
    }
    append_slip(settings, row)

    # ---- ข้อความตอบลูกค้า: สร้างจากโค้ดเท่านั้น และไม่ยืนยันการชำระเงิน ----
    lines = [
        "ได้รับสลิปแล้วครับ ข้อมูลที่อ่านได้คือ",
        f"- ชื่อผู้โอน: {sender or 'อ่านไม่ได้'}",
        f"- ยอดเงิน: {amount:,.2f} บาท",
        f"- วันที่โอน: {_thai_date(transfer_date)}" + (f" เวลา {transfer_time} น." if transfer_time else ""),
        "",
        "สถานะ: รอเจ้าหน้าที่ตรวจสอบ ระบบยังไม่ได้ยืนยันการชำระเงินหรือการจอง "
        "เจ้าหน้าที่จะตรวจยอดเงินเข้าบัญชีและติดต่อกลับในเวลาทำการครับ",
    ]
    lines.append("หากข้อมูลที่อ่านได้ไม่ถูกต้อง กรุณาแจ้งเจ้าหน้าที่ครับ")

    public = {"sender_name": sender, "amount": amount, "transfer_date": transfer_date,
              "transfer_time": transfer_time, "receiver_match": match, "status": STATUS_PENDING}
    return SlipResult("saved", "\n".join(lines), public, details)
