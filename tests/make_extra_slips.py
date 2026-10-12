"""สร้างสลิปจำลองชุดเพิ่มเติม 5 ใบ สำหรับทดสอบการอ่านสลิปหลายรูปแบบ (ภาพถูกสร้างไว้แล้วใน tests/images/extra/)

ทุกใบเป็นสลิปที่ถูกต้องและโอนเข้าบัญชีร้าน แต่ต่างกันที่หน้าตาและรูปแบบวันที่ เพื่อดูว่า Vision LLM อ่านได้แม่นแค่ไหน
ธนาคารและชื่อทั้งหมดเป็นของสมมติ ทุกใบมีลายน้ำว่า "ตัวอย่างสำหรับทดสอบระบบ ไม่ใช่สลิปจริง"

ถ้าต้องการสร้างใหม่:  uv run --with playwright python tests/make_extra_slips.py
(ครั้งแรกต้องติดตั้งเบราว์เซอร์ด้วย  uv run --with playwright playwright install chromium)
"""

import asyncio
from pathlib import Path

OUT = Path(__file__).resolve().parent / "images" / "extra"
SHOP = "บัดดี้ ไบค์ ไรด์นาว"
WATERMARK = '<div class="wm">ตัวอย่างสำหรับทดสอบระบบ ไม่ใช่สลิปจริง</div>'

CSS = """
*{box-sizing:border-box} body{margin:0;background:#dfe9f1;font-family:'Loma','Leelawadee UI',Tahoma,sans-serif}
.slip{position:relative;width:420px;overflow:hidden;background:#fff;color:#12283a}
.wm{position:absolute;left:-70px;top:46%;width:580px;text-align:center;transform:rotate(-24deg);
    font-size:22px;font-weight:700;color:rgba(200,40,40,.22);letter-spacing:1px;pointer-events:none}
.lab{font-size:13px;color:#6b7f90}.val{font-size:17px;font-weight:700}.acc{font-size:14px;color:#55697a}
.row{display:flex;justify-content:space-between;align-items:baseline;margin-top:12px;font-size:15px;color:#33495b}

/* แบบ A: หัวน้ำเงิน แบบแอปธนาคารทั่วไป */
.a{padding:26px}
.a .bank{display:flex;align-items:center;gap:10px;color:#1b4f8f;font-weight:700;font-size:18px}
.a .logo{width:34px;height:34px;border-radius:9px;background:#1b4f8f;color:#fff;display:grid;place-items:center;font-size:14px}
.a .ok{margin:18px 0 2px;font-size:22px;font-weight:700;color:#12925f}
.a .when{color:#55697a;font-size:15px}
.a .box{margin-top:14px;padding:14px;border:1px solid #d5e2ec;border-radius:12px}
.a .arrow{text-align:center;color:#8aa0b2;font-size:20px;margin:6px 0}
.a .amt{font-size:26px;font-weight:700}
.a .ref{margin-top:14px;font-size:13px;color:#55697a}
.memo{margin-top:12px;padding:10px 12px;background:#f2f6fa;border-radius:10px;font-size:14px;color:#33495b}

/* แบบ B: หัวสีเขียวเต็มแถบ ยอดเงินอยู่บนสุด */
.b .head{background:#0f7a55;color:#fff;padding:22px 24px 26px;text-align:center}
.b .head .bank{font-size:16px;opacity:.9}.b .head .ok{font-size:15px;margin-top:10px}
.b .head .amt{font-size:34px;font-weight:700;margin-top:4px}
.b .body{padding:20px 24px 24px}
.b .line{display:flex;justify-content:space-between;gap:16px;padding:10px 0;border-bottom:1px dashed #d5e2ec;font-size:15px}
.b .line span:first-child{color:#6b7f90;flex:none}.b .line span:last-child{text-align:right;font-weight:700}

/* แบบ C: โหมดมืด */
.c{background:#141b26;color:#e8eef5;padding:26px}
.c .bank{font-weight:700;font-size:18px;color:#7fb8ff}
.c .ok{margin-top:16px;font-size:20px;font-weight:700;color:#5fe3a5}
.c .when{color:#9fb0c2;font-size:15px}
.c .card{margin-top:14px;padding:14px;background:#1f2937;border-radius:14px}
.c .lab{color:#9fb0c2}.c .acc{color:#9fb0c2}.c .row{color:#c9d5e2}
.c .amt{font-size:28px;font-weight:700;color:#fff}
.c .ref{margin-top:14px;font-size:13px;color:#9fb0c2}
.c .wm{color:rgba(255,110,110,.28)}

/* แบบ D: ใบเสร็จพร้อมเพย์ ตัวอักษรเล็ก ข้อมูลเรียงเป็นตาราง */
.d{padding:22px 24px;font-size:14px}
.d .top{display:flex;justify-content:space-between;align-items:center;border-bottom:2px solid #12283a;padding-bottom:10px}
.d .top b{font-size:17px}.d .tag{padding:2px 10px;border:1.5px solid #12925f;color:#12925f;border-radius:999px;font-size:13px}
.d table{width:100%;border-collapse:collapse;margin-top:10px}
.d td{padding:8px 0;border-bottom:1px solid #e3eaf0;vertical-align:top}
.d td:first-child{color:#6b7f90;width:44%}.d td:last-child{text-align:right;font-weight:700}
.d .big td:last-child{font-size:22px}
"""


def style_a(sender, amount, when, ref, memo="", bank="ธนาคารตัวอย่าง DEMO BANK", logo="DB"):
    memo_html = f'<div class="memo">บันทึกช่วยจำ: {memo}</div>' if memo else ""
    return f"""<div class="slip a" id="shot">
  <div class="bank"><div class="logo">{logo}</div>{bank}</div>
  <div class="ok">โอนเงินสำเร็จ</div><div class="when">{when}</div>
  <div class="box"><div class="lab">จาก</div><div class="val">{sender}</div><div class="acc">xxx-x-x4821-x</div></div>
  <div class="arrow">▼</div>
  <div class="box"><div class="lab">ไปยัง</div><div class="val">{SHOP}</div><div class="acc">xxx-x-x5666-x</div></div>
  <div class="row"><span>จำนวนเงิน</span><span class="amt">{amount} บาท</span></div>
  <div class="row"><span>ค่าธรรมเนียม</span><span>0.00 บาท</span></div>
  <div class="ref">เลขที่อ้างอิง {ref}</div>{memo_html}
  {WATERMARK}
</div>"""


def style_b(sender, amount, when_date, when_time, ref):
    return f"""<div class="slip b" id="shot">
  <div class="head"><div class="bank">ธนาคารสมมติ MOCK BANK</div><div class="ok">ทำรายการสำเร็จ</div>
    <div class="amt">฿ {amount}</div></div>
  <div class="body">
    <div class="line"><span>ผู้โอน</span><span>{sender}</span></div>
    <div class="line"><span>ผู้รับ</span><span>{SHOP}</span></div>
    <div class="line"><span>บัญชีผู้รับ</span><span>xxx-x-x5666-x</span></div>
    <div class="line"><span>วันที่</span><span>{when_date}</span></div>
    <div class="line"><span>เวลา</span><span>{when_time}</span></div>
    <div class="line"><span>รหัสอ้างอิง</span><span>{ref}</span></div>
  </div>
  {WATERMARK}
</div>"""


def style_c(sender, amount, when, ref):
    return f"""<div class="slip c" id="shot">
  <div class="bank">TEST PAY แอปทดสอบ</div>
  <div class="ok">✓ โอนเงินสำเร็จ</div><div class="when">{when}</div>
  <div class="card"><div class="lab">ผู้โอน</div><div class="val">{sender}</div><div class="acc">xxx-x-x7310-x</div></div>
  <div class="card"><div class="lab">ผู้รับ</div><div class="val">{SHOP}</div><div class="acc">xxx-x-x5666-x</div></div>
  <div class="row"><span>จำนวน</span><span class="amt">{amount} บาท</span></div>
  <div class="ref">หมายเลขรายการ {ref}</div>
  {WATERMARK}
</div>"""


def style_d(sender, amount, when, ref):
    return f"""<div class="slip d" id="shot">
  <div class="top"><b>ธนาคารตัวอย่าง DEMO BANK</b><span class="tag">สำเร็จ</span></div>
  <table>
    <tr><td>ประเภทรายการ</td><td>โอนเงินพร้อมเพย์</td></tr>
    <tr><td>วันที่ทำรายการ</td><td>{when}</td></tr>
    <tr><td>ชื่อผู้โอน</td><td>{sender}</td></tr>
    <tr><td>ชื่อผู้รับ</td><td>{SHOP}</td></tr>
    <tr><td>พร้อมเพย์ผู้รับ</td><td>xxx-xxx-0000</td></tr>
    <tr class="big"><td>จำนวนเงิน (บาท)</td><td>{amount}</td></tr>
    <tr><td>ค่าธรรมเนียม (บาท)</td><td>0.00</td></tr>
    <tr><td>เลขที่รายการ</td><td>{ref}</td></tr>
  </table>
  {WATERMARK}
</div>"""


IMAGES = {
    # 1) แบบมาตรฐาน มัดจำรถ 160 ซีซี ปี พ.ศ. 4 หลัก
    "07_deposit_3000.png": style_a("นาย ทดลอง ระบบดี", "3,000.00", "12 ต.ค. 2569 - 10:15 น.", "DEMO202610120007"),
    # 2) เงินจอง มีบันทึกช่วยจำ และวันที่เป็นตัวเลขทับ
    "08_booking_500_memo.png": style_a("น.ส. สมมุติ รักเที่ยว", "500.00", "12/10/2569 13:40", "DEMO202610120008",
                                       memo="จอง PCX160 วันที่ 15 ต.ค."),
    # 3) ยอดอยู่บนสุด เดือนเขียนเต็ม มัดจำรถ 300 ซีซีขึ้นไป
    "09_deposit_5000_fullmonth.png": style_b("นาง ตัวอย่าง มีสุข", "5,000.00", "12 ตุลาคม 2569", "16:02:37", "MOCK8812026101209"),
    # 4) โหมดมืด ชื่อผู้โอนภาษาอังกฤษ ปี 2 หลัก
    "10_rent_1350_darkmode.png": style_c("MR. DEMO TESTER", "1,350.00", "12 ต.ค. 69 18:27", "TP20261012X0010"),
    # 5) พร้อมเพย์ แบบตาราง ปี ค.ศ.
    "11_promptpay_2700.png": style_d("นาย จำลอง ขับขี่", "2,700.00", "12/10/2026 19:05", "DEMO202610120011"),
}

# ค่าที่ระบบควรอ่านได้ ใช้ตรวจผลด้วยตา (วันที่ที่ระบบเก็บเป็น ค.ศ.)
EXPECTED = {
    "07_deposit_3000.png": ("นาย ทดลอง ระบบดี", "3,000.00", "12/10/2026", "10:15"),
    "08_booking_500_memo.png": ("น.ส. สมมุติ รักเที่ยว", "500.00", "12/10/2026", "13:40"),
    "09_deposit_5000_fullmonth.png": ("นาง ตัวอย่าง มีสุข", "5,000.00", "12/10/2026", "16:02"),
    "10_rent_1350_darkmode.png": ("MR. DEMO TESTER", "1,350.00", "12/10/2026", "18:27"),
    "11_promptpay_2700.png": ("นาย จำลอง ขับขี่", "2,700.00", "12/10/2026", "19:05"),
}


async def main():
    from playwright.async_api import async_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 420, "height": 800}, device_scale_factor=2)
        for name, body in IMAGES.items():
            await page.set_content(f"<html><head><style>{CSS}</style></head><body>{body}</body></html>")
            await (await page.query_selector("#shot")).screenshot(path=str(OUT / name))
            print("สร้างแล้ว:", name)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
