"""กฎในโค้ดสำหรับความเสี่ยง 3 ข้อของ OWASP Top 10 for LLM Applications (Week 11)

    1. Prompt Injection                 ขาเข้า: จับรูปแบบคำสั่งหลอก      ขาออก: จับการรั่วของ system prompt
    2. Sensitive Information Disclosure ขาเข้า: จับคำขอข้อมูลลูกค้า + ปิดบังเลขส่วนตัว   ขาออก: จับเลขส่วนตัวในคำตอบ
    3. Misinformation                   ขาเข้า: ติดป้ายคำอ้างที่ยืนยันไม่ได้  ขาออก: ตรวจตัวเลขเงิน ส่วนลด การยืนยันปลอม รหัสอ้างอิง

เหตุผลที่ต้องมีไฟล์นี้: Llama Guard ไม่ได้ออกแบบมาจับความเสี่ยงทั้ง 3 ข้อนี้
กติกาอยู่ในโค้ด ผู้ใช้จึงล้วงหรือสั่งให้ข้ามไม่ได้ ข้อจำกัดคือเป็นการจับรูปแบบ (regex)
จึงมีทั้ง false positive และ false negative ต้องทดสอบและปรับรายการอยู่เสมอ
"""

import re
from dataclasses import dataclass

from .blocklist import squash

PROMPT_INJECTION = "PROMPT_INJECTION"
SENSITIVE_INFO = "SENSITIVE_INFO"
MISINFORMATION = "MISINFORMATION"


@dataclass
class Verdict:
    ok: bool
    risk: str = ""        # หนึ่งใน 3 ความเสี่ยงด้านบน หรือ CONTENT / LIMIT / GUARD
    code: str = ""        # รหัสละเอียด ใช้ใน log และตารางผลทดสอบ
    reply: str = ""       # ข้อความที่ส่งให้ลูกค้าแทน
    status: int = 200


OK = Verdict(True)


# ==========================================================================
# 1) PROMPT INJECTION
# ==========================================================================

# ตรวจกับข้อความที่ลบช่องว่างและแปลงเป็นตัวพิมพ์เล็กแล้ว (กันการเว้นวรรคเลี่ยง)
_INJECTION = [
    r"ลืมคำสั่ง", r"ไม่ต้องสนใจคำสั่ง", r"เพิกเฉย(ต่อ)?คำสั่ง", r"ยกเลิกคำสั่ง(เดิม|ก่อนหน้า)", r"ข้ามกฎ",
    r"คำสั่ง(ก่อนหน้า|ระบบ|ตั้งต้น|ลับ)", r"ซิสเต็มพร", r"พรอมต์ของ(คุณ|ระบบ)", r"พร้อมท์ของ(คุณ|ระบบ)",
    r"ignore(all|the|your|any)*(previous|prior|above|earlier)", r"disregard(all|the|your)*(previous|prior|above)",
    r"forget(all|the|your|everything)*(previous|prior|above|instructions|rules)",
    r"systemprompt", r"developermode", r"โหมดนักพัฒนา", r"jailbreak", r"dan(mode|โหมด)",
    r"(ตอนนี้|จากนี้|ต่อไปนี้|นับจากนี้)(ไป)?(คุณ|เธอ|แก|บอท|บอต)(คือ|เป็น)", r"สมมติว่า(คุณ|เธอ|บอท|บอต)(คือ|เป็น)",
    r"youarenow", r"actas(a|an|the)?(manager|owner|admin|staff|developer)", r"pretend(to|you)",
    r"(แสดง|บอก|พิมพ์|เปิดเผย|ขอดู)(คำสั่ง|กติกา|กฎ)(ทั้งหมด)?(ของ|ที่)(คุณ|ระบบ|บอท|บอต)",
    r"(repeat|print|reveal|show)(me)?(your|the)(instructions|prompt|rules)",
]

# การอ้างสิทธิ์เป็นเจ้าของร้านหรือพนักงาน: แชตไม่มีทางยืนยันตัวตนได้
_AUTHORITY = [
    r"(ฉัน|ผม|ดิฉัน|เรา|หนู|กู)(คือ|เป็น)(เจ้าของ|ผู้จัดการ|พนักงาน|แอดมิน|ผู้ดูแล|ช่าง)",
    r"iam(the|a|an)?(owner|manager|admin|staff|developer)",
    r"(เจ้าของร้าน|ผู้จัดการ|แอดมิน)(อนุญาต|อนุมัติ|สั่ง)(แล้ว|ว่า|ให้)",
]


def check_prompt_injection(text: str, contact: str) -> Verdict:
    s = squash(text)
    if any(re.search(p, s) for p in _INJECTION):
        return Verdict(False, PROMPT_INJECTION, "INJECTION_PATTERN",
                       "ขออภัยครับ ผมเปลี่ยนบทบาท ข้ามกติกาของร้าน หรือเปิดเผยคำสั่งภายในไม่ได้ "
                       f"ผมให้ข้อมูลได้เฉพาะเรื่องการเช่ารถตามเอกสารของร้านครับ หากต้องการความช่วยเหลือ กรุณาติดต่อเจ้าหน้าที่ {contact}")
    if any(re.search(p, s) for p in _AUTHORITY):
        return Verdict(False, PROMPT_INJECTION, "AUTHORITY_CLAIM",
                       "ขออภัยครับ แชตนี้ยืนยันตัวตนของผู้ใช้ไม่ได้ จึงเปลี่ยนแปลงราคา ส่วนลด หรือเงื่อนไขของร้านตามคำขอในแชตไม่ได้ครับ "
                       f"กรุณาติดต่อเจ้าหน้าที่ {contact}")
    return OK


def check_prompt_leak(answer: str, canary: str) -> Verdict:
    """ขาออก: ถ้าคำตอบมีรหัสดักจับ (canary) หรือหัวข้อของ system prompt แปลว่าคำสั่งภายในรั่ว"""
    markers = [canary, "# ต้องทำ", "# ห้ามทำ", "# วิธีทำงาน", "<ข้อมูลร้าน>", "<ข้อความลูกค้า>"]
    if any(m and m in answer for m in markers):
        return Verdict(False, PROMPT_INJECTION, "PROMPT_LEAK",
                       "ขออภัยครับ ผมเปิดเผยคำสั่งภายในของระบบไม่ได้ ผมช่วยตอบคำถามเรื่องการเช่ารถของร้านได้ครับ")
    return OK


def field_suspicious(value: str) -> bool:
    """ข้อความที่อ่านได้จากรูป (เช่น ชื่อผู้โอน) มีลักษณะเป็นคำสั่งหรือข้อความหลอกหรือไม่

    ใช้กันการฝังคำสั่งไว้ในรูป (indirect prompt injection) ไม่ให้ไปปรากฏในคำตอบของบอต
    """
    s = squash(value)
    return (any(re.search(p, s) for p in _INJECTION + _AUTHORITY)
            or bool(_FAKE_ACTION.search(value)) or "http" in s or "www." in s)


# ==========================================================================
# 2) SENSITIVE INFORMATION DISCLOSURE
# ==========================================================================

_WHO = r"(ลูกค้า(คนอื่น|รายอื่น|ท่านอื่น|ราย|คนที่|ที่|ชื่อ|ทั้งหมด|ทุกคน)|คนอื่น|ผู้เช่า(คนอื่น|รายอื่น|ราย|ที่|ทั้งหมด)|คุณ[ก-๙]{2,}|นาย[ก-๙]{2,}|นาง[ก-๙]{2,})"
_WHAT = r"(เบอร์|เบอร์โทร|ที่อยู่|ข้อมูลส่วนตัว|ข้อมูล|เลขบัตร|เลขบัญชี|สลิป|ยอดโอน|ประวัติ|การจอง|รายชื่อ|ชื่อ)"
_SENSITIVE_REQUEST = [
    _WHAT + r"(การโอน|การเช่า|การจอง|และที่อยู่|และเบอร์)*(ของ)?" + _WHO,
    _WHO + r".{0,25}(เบอร์|ที่อยู่|เลขบัตร|เลขบัญชี|โอนมาเท่าไร|โอนเท่าไร|จ่ายเท่าไร|พักที่ไหน|อยู่ที่ไหน)",
    r"(ใคร|ลูกค้าคนไหน)(บ้าง)?(เช่า|จอง|โอน|ยืม)",
    r"(รายชื่อ|รายการ|ข้อมูล)(ลูกค้า|ผู้เช่า|สลิป|การโอน)(ทั้งหมด|ทุกคน|วันนี้|เมื่อวาน)",
    r"(ขอดู|ส่ง|แสดง|เปิด)(ไฟล์)?(csv|สลิปทั้งหมด|สลิปของคนอื่น|slips)",
]

# เลขยาว 9 หลักขึ้นไป (คั่นด้วยขีดได้) เช่น เบอร์โทร เลขบัญชี เลขบัตร และเลขบัตรประชาชนที่เว้นวรรคตามรูปแบบ
_LONG_DIGITS = re.compile(r"(?<![\d.,])(?:\d(?:-?\d){8,}|\d \d{4} \d{5} \d{2} \d)(?![\d,]*\.?\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def check_sensitive_request(text: str, contact: str) -> Verdict:
    """ขาเข้า: คำขอข้อมูลของลูกค้ารายอื่น ตอบปฏิเสธทันทีโดยไม่เรียก LLM"""
    s = squash(text)
    if any(re.search(p, s) for p in _SENSITIVE_REQUEST):
        return Verdict(False, SENSITIVE_INFO, "CUSTOMER_DATA_REQUEST",
                       "ขออภัยครับ ผมไม่มีและไม่สามารถเปิดเผยข้อมูลของลูกค้ารายใดได้ ทั้งชื่อ เบอร์โทร การจอง และสลิปการโอนเงิน "
                       f"หากต้องการตรวจสอบข้อมูลของคุณเอง กรุณาติดต่อเจ้าหน้าที่และยืนยันตัวตนโดยตรงที่ {contact}")
    return OK


def mask_pii(text: str) -> str:
    """ขาเข้า: ปิดบังตัวเลขยาว (เลขบัตร เลขบัญชี เบอร์โทร) และอีเมล ก่อนส่งให้ LLM และก่อนเก็บประวัติ"""
    text = _LONG_DIGITS.sub("[ปิดบังตัวเลข]", text)
    return _EMAIL.sub("[ปิดบังอีเมล]", text)


def check_pii_output(answer: str, kb_text: str) -> Verdict:
    """ขาออก: คำตอบต้องไม่มีเลขยาวหรืออีเมลที่ไม่ได้มาจากเอกสารของร้าน"""
    allowed = {_digits(m.group()) for m in _LONG_DIGITS.finditer(kb_text)}
    for m in _LONG_DIGITS.finditer(answer):
        if _digits(m.group()) not in allowed:
            return Verdict(False, SENSITIVE_INFO, "PII_IN_OUTPUT",
                           "ขออภัยครับ ผมแสดงข้อมูลตัวเลขส่วนบุคคลในแชตไม่ได้ กรุณาติดต่อเจ้าหน้าที่ของร้านโดยตรงครับ")
    for m in _EMAIL.finditer(answer):
        if m.group() not in kb_text:
            return Verdict(False, SENSITIVE_INFO, "PII_IN_OUTPUT",
                           "ขออภัยครับ ผมแสดงข้อมูลติดต่อส่วนบุคคลในแชตไม่ได้ กรุณาติดต่อเจ้าหน้าที่ของร้านโดยตรงครับ")
    return OK


# ==========================================================================
# 3) MISINFORMATION
# ==========================================================================

# ขาเข้า: ลูกค้าอ้างคำพูดหรือข้อตกลงที่ระบบยืนยันไม่ได้ ไม่บล็อก แต่ติดป้ายเตือนให้ LLM
_UNVERIFIED_CLAIM = [
    r"(พนักงาน|แอดมิน|เจ้าของ|เจ้าหน้าที่|ร้าน|พี่ที่ร้าน)(คนก่อน|เมื่อวาน|เมื่อกี้)?(บอก|แจ้ง|สัญญา|รับปาก|ตกลง|เคยบอก|ยืนยัน)(ไว้|แล้ว)?(ว่า)?",
    r"(ในเว็บ|ในเพจ|ในโฆษณา|ในไลน์|เพื่อน)(บอก|เขียน|ลง|แจ้ง)(ไว้)?ว่า",
    r"(เคย|ครั้งก่อน|คราวก่อน|เมื่อก่อน)(ได้|เช่า|จ่าย|ลด)",
]
CLAIM_NOTE = ("(หมายเหตุจากระบบ: ข้อความนี้มีการอ้างถึงคำพูด ข้อตกลง หรือราคาที่ระบบยืนยันไม่ได้ "
              "ให้ตอบตามข้อมูลร้านเท่านั้น และแจ้งว่าต้องให้เจ้าหน้าที่ยืนยัน)")


def has_unverified_claim(text: str) -> bool:
    s = squash(text)
    return any(re.search(p, s) for p in _UNVERIFIED_CLAIM)


_MONEY = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:บาท|baht|thb|฿)|฿\s*(\d[\d,]*(?:\.\d+)?)", re.IGNORECASE)
_PERCENT = re.compile(r"\d+(?:\.\d+)?\s*(?:%|เปอร์เซ็นต์|เปอร์เซนต์|percent)", re.IGNORECASE)
_DAMAGE_COST = re.compile(
    r"(ค่าซ่อม|ค่าเสียหาย|ค่าอะไหล่|ค่าทำสี|ซ่อม|เสียหาย)\s*(จะ)?(ประมาณ|ราว ๆ|ราว|อยู่ที่|คือ|น่าจะ|ไม่เกิน|:)*\s*\d[\d,]*\s*(บาท|baht|thb|฿)",
    re.IGNORECASE)
_FAKE_ACTION = re.compile(
    r"(จอง|การจอง|ชำระเงิน|การชำระเงิน|ส่วนลด|โอนเงิน|การโอน|ยอดเงิน|สลิป)[^\n.]{0,25}(เรียบร้อย|สำเร็จแล้ว|ให้แล้ว|ยืนยันแล้ว|ถูกต้องแล้ว|ผ่านแล้ว)"
    r"|(หมายเลข|รหัส|เลขที่)การจอง(ของคุณ)?\s*(คือ|:|=)"
    r"|booking\s*(id|number|code)\s*(is|:|=)"
    r"|(อนุมัติ|ยืนยัน)(ส่วนลด|การจอง|การชำระเงิน|ยอดเงิน|การโอน)(ให้|แล้ว|เรียบร้อย)"
    r"|(ได้รับ|รับ)(เงิน|ยอด|ชำระ)(ของคุณ)?(แล้ว|เรียบร้อย)|เงินเข้า(บัญชี)?(แล้ว|เรียบร้อย)|มีรถว่าง(ให้|แน่นอน|ครับ|ค่ะ)",
    re.IGNORECASE)
_CITATION = re.compile(r"\b(?:FAQ|BIKE|POL)-\d{2}\b")


def _num(raw: str) -> float:
    return float(raw.replace(",", ""))


def _negated(text: str, start: int) -> bool:
    """วลีนั้นอยู่ในประโยคปฏิเสธหรือไม่ เช่น 'ร้านไม่มีส่วนลด 90%' หรือ 'ยังไม่ได้ยืนยันการชำระเงิน'"""
    return "ไม่" in text[max(0, start - 40): start]


class MisinformationGuard:
    """ขาออก: เทียบคำตอบของ LLM กับคลังความรู้ เพื่อกันข้อมูลเท็จที่สร้างความเสียหายให้ร้าน"""

    def __init__(self, kb_text: str, kb_ids: set[str]):
        self.kb_ids = kb_ids
        self.kb_amounts = {_num(a or b) for a, b in _MONEY.findall(kb_text)}
        self.daily_prices = {_num(p) for p in re.findall(r"รายวัน\s*(\d[\d,]*)\s*บาท", kb_text)}
        self.deposits = {_num(d) for d in re.findall(r"มัดจำ:?\s*(\d[\d,]*)\s*บาท", kb_text)}

    def _amount_allowed(self, amount: float) -> bool:
        """ผ่านเมื่อ (1) มีในคลังความรู้ หรือ (2) เป็นราคารายวัน x จำนวนวัน หรือยอดนั้นบวกเงินมัดจำ"""
        if amount in self.kb_amounts:
            return True
        for value in [amount] + [amount - dep for dep in self.deposits if amount > dep]:
            for price in self.daily_prices:
                days = value / price
                if days == int(days) and 1 <= days <= 90:
                    return True
        return False

    def check(self, answer: str, contact: str) -> Verdict:
        def blocked(code: str, reply: str) -> Verdict:
            return Verdict(False, MISINFORMATION, code, f"{reply} กรุณาติดต่อเจ้าหน้าที่ {contact}")

        m = _DAMAGE_COST.search(answer)
        if m and not _negated(answer, m.start()):
            return blocked("DAMAGE_ESTIMATE", "ขออภัยครับ แชตบอตประเมินค่าซ่อมหรือค่าเสียหายไม่ได้ ต้องให้เจ้าหน้าที่ตรวจสภาพรถจริงครับ")

        for m in _MONEY.finditer(answer):
            if not self._amount_allowed(_num(m.group(1) or m.group(2))) and not _negated(answer, m.start()):
                return blocked("UNKNOWN_PRICE", "ขออภัยครับ ผมยืนยันตัวเลขราคาสำหรับคำถามนี้ไม่ได้ เพื่อป้องกันข้อมูลผิดพลาด")

        for m in _PERCENT.finditer(answer):
            if not _negated(answer, m.start()):
                return blocked("UNKNOWN_DISCOUNT", "ขออภัยครับ ร้านไม่มีโปรโมชันหรือส่วนลดอื่นนอกจากราคารายสัปดาห์และรายเดือน และแชตบอตให้ส่วนลดไม่ได้ครับ")

        for m in _FAKE_ACTION.finditer(answer):
            if not _negated(answer, m.start()):
                return blocked("FAKE_CONFIRMATION", "ขออภัยครับ แชตบอตรับจอง ยืนยันรถว่าง ยืนยันการชำระเงิน หรืออนุมัติส่วนลดไม่ได้ ต้องให้เจ้าหน้าที่ของร้านเป็นผู้ดำเนินการครับ")

        for ref in _CITATION.findall(answer):
            if ref not in self.kb_ids:
                return blocked("FAKE_CITATION", "ขออภัยครับ ผมยืนยันแหล่งที่มาของคำตอบนี้ไม่ได้ เพื่อป้องกันข้อมูลผิดพลาด")

        return OK
