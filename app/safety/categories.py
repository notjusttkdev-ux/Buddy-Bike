"""หมวดของ Llama Guard 4 และข้อความปฏิเสธภาษาไทยรายหมวด (ดัดแปลงจากของอาจารย์)

- blocked=False -> ถ้าโมเดลตอบ unsafe เฉพาะหมวดนี้ จะถือว่า safe
- แก้ว่าหมวดไหนบล็อก และแก้ข้อความปฏิเสธ ได้ที่ไฟล์นี้ที่เดียว
"""

from dataclasses import dataclass

_TAIL = "หากต้องการสอบถามเรื่องการเช่ารถของร้าน ยินดีช่วยเหลือครับ"


@dataclass(frozen=True)
class Category:
    code: str
    name: str
    blocked: bool
    message: str | None = None


_CATEGORIES = [
    Category("S1", "Violent Crimes", True, f"ขออภัยครับ ไม่สามารถตอบเนื้อหาที่เกี่ยวข้องกับความรุนแรงได้ {_TAIL}"),
    Category("S2", "Non-Violent Crimes", True, f"ขออภัยครับ ไม่สามารถตอบเนื้อหาที่เกี่ยวข้องกับการกระทำผิดกฎหมายได้ {_TAIL}"),
    Category("S3", "Sex-Related Crimes", True, f"ขออภัยครับ ไม่สามารถตอบเนื้อหาที่เกี่ยวข้องกับอาชญากรรมทางเพศได้ {_TAIL}"),
    Category("S4", "Child Sexual Exploitation", True, "ขออภัยครับ ไม่สามารถตอบเนื้อหาที่เกี่ยวข้องกับการล่วงละเมิดเด็กได้"),
    Category("S5", "Defamation", True, "ขออภัยครับ ไม่สามารถตอบเนื้อหาที่อาจเป็นการใส่ร้ายหรือหมิ่นประมาทบุคคลหรือองค์กรได้"),
    Category("S6", "Specialized Advice", True, "ขออภัยครับ ไม่สามารถให้คำแนะนำเฉพาะทาง เช่น การแพทย์ กฎหมาย หรือการเงินได้ กรุณาปรึกษาผู้เชี่ยวชาญโดยตรงครับ"),
    Category("S7", "Privacy", True, "ขออภัยครับ ไม่สามารถตอบเนื้อหาที่เกี่ยวข้องกับข้อมูลส่วนบุคคลของผู้อื่นได้ เพื่อความเป็นส่วนตัวของลูกค้าทุกคน"),
    Category("S8", "Intellectual Property", False),
    Category("S9", "Indiscriminate Weapons", True, "ขออภัยครับ ไม่สามารถตอบเนื้อหาที่เกี่ยวข้องกับอาวุธได้"),
    Category("S10", "Hate", True, "ขออภัยครับ ไม่สามารถตอบเนื้อหาที่แสดงความเกลียดชังหรือเลือกปฏิบัติต่อบุคคลหรือกลุ่มใดได้"),
    Category("S11", "Suicide & Self-Harm", True, "ขออภัยครับ ไม่สามารถตอบเนื้อหาเรื่องนี้ได้ หากคุณกำลังรู้สึกไม่ไหว โปรดพูดคุยกับคนใกล้ชิดหรือโทรสายด่วนสุขภาพจิต 1323 นะครับ"),
    Category("S12", "Sexual Content", True, f"ขออภัยครับ ไม่สามารถตอบเนื้อหาทางเพศได้ {_TAIL}"),
    Category("S13", "Elections", False),
    Category("S14", "Code Interpreter Abuse", False),
]

CATEGORIES: dict[str, Category] = {c.code: c for c in _CATEGORIES}

BLOCKLIST_CODE = "BLOCKLIST"
BLOCKLIST_MESSAGE = f"ขออภัยครับ ไม่สามารถตอบข้อความนี้ได้ กรุณาใช้ถ้อยคำสุภาพ {_TAIL}"
