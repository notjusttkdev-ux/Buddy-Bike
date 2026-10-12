"""สร้างแผนภาพ architecture และ data flow เป็นไฟล์ SVG

รัน:  python docs/make_diagrams.py
ได้:  docs/architecture.svg และ docs/dataflow.svg (เปิดด้วยเบราว์เซอร์ หรือแทรกใน Word ได้)
ถ้าแก้โครงสร้างระบบ ให้แก้ข้อความในไฟล์นี้แล้วรันใหม่ เพื่อให้แผนภาพตรงกับโค้ดจริงเสมอ
"""

from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parent
FONT = "'IBM Plex Sans Thai','Leelawadee UI','Noto Sans Thai',Tahoma,Loma,sans-serif"
INK, MUTED, LINE = "#1c2321", "#5d6763", "#9aa39f"
C_UI, C_API, C_GUARD, C_RAG, C_LLM, C_DATA, C_EXT = (
    "#e8f0fb", "#e3f1ee", "#fff5d9", "#eaf4e2", "#f3e9f7", "#f1eee6", "#fde9e2")


def svg(width, height, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
            f'font-family="{FONT}">\n'
            '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M0 0L10 5L0 10z" fill="{INK}"/></marker></defs>\n'
            f'<rect width="{width}" height="{height}" fill="#ffffff"/>\n' + "\n".join(body) + "\n</svg>\n")


def text(x, y, s, size=15, weight=400, fill=INK, anchor="start"):
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}">{escape(s)}</text>')


def box(x, y, w, h, title, lines, fill, sub=None, stroke=LINE):
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>',
           text(x + 16, y + 28, title, 16, 600)]
    yy = y + 28
    if sub:
        yy += 20
        out.append(text(x + 16, yy, sub, 12.5, 400, MUTED))
    for line in lines:
        yy += 23
        out.append(text(x + 16, yy, line, 14))
    return "\n".join(out)


def arrow(x1, y1, x2, y2, label=None, lx=None, ly=None, both=False, dashed=False):
    start = ' marker-start="url(#arrow)"' if both else ""
    dash = ' stroke-dasharray="6 5"' if dashed else ""
    out = [f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{INK}" stroke-width="1.8" marker-end="url(#arrow)"{start}{dash}/>']
    if label:
        out.append(text(lx if lx is not None else (x1 + x2) / 2, ly if ly is not None else (y1 + y2) / 2 - 8,
                        label, 12.5, 500, MUTED, "middle"))
    return "\n".join(out)


def architecture():
    b = [text(30, 40, "แผนภาพสถาปัตยกรรม: Buddy Bike Chatbot", 22, 600),
         text(30, 64, "แต่ละกล่องคือไฟล์หรือโฟลเดอร์จริงในโปรเจกต์ และทุก endpoint ในภาพทำงานจริง", 14, 400, MUTED)]

    b.append(box(30, 215, 280, 235, "Browser ของลูกค้า", [
        "static/index.html", "static/style.css", "static/chat.js", "",
        "หน้าจอเริ่มต้น, ภาพกำลังคิด,", "แถบแจ้งปัญหา, แนบสลิป"], C_UI, "หน้าเว็บแชต (UI)"))
    b.append(box(30, 520, 280, 153, "เจ้าหน้าที่ร้าน", [
        "เปิดดูรายการสลิป (ADMIN_TOKEN)", "รับแจ้งเตือนทาง LINE", "ตอบลูกค้าใน LINE OA Manager"], C_UI, "ผู้ตรวจสอบการชำระเงิน"))
    b.append(box(30, 715, 280, 160, "LINE Platform", [
        "ลูกค้าแชตกับ LINE OA", "ส่ง webhook มาที่ /line/webhook", "Reply API: ตอบลูกค้า",
        "Push API: แจ้งเจ้าหน้าที่"], C_EXT, "LINE Messaging API"))

    b.append(f'<rect x="370" y="90" width="770" height="800" rx="16" fill="#fafaf7" stroke="{INK}" stroke-width="1.5" stroke-dasharray="7 5"/>')
    b.append(text(390, 118, "Backend: FastAPI รันใน Docker บน Render", 15, 600))

    b.append(box(390, 135, 730, 223, "app/main.py", [
        "GET  /                  หน้าเว็บแชต",
        "GET  /health            ตรวจว่าระบบพร้อม และดูการตั้งค่า",
        "POST /api/chat          รับข้อความ หรือรูปสลิป แล้วส่งคำตอบกลับ",
        "POST /api/reset         ล้างประวัติบทสนทนา",
        "GET  /api/kb/search     ดูผลการค้นคลังความรู้ (ตรวจ RAG)",
        "GET  /api/slips         รายการสลิป สำหรับเจ้าหน้าที่เท่านั้น",
        "POST /line/webhook      รับข้อความและรูปสลิปจาก LINE OA"], C_API, "API Endpoint ทั้งหมดของระบบ (เว็บและ LINE ใช้ลำดับเดียวกัน)"))

    b.append(box(390, 380, 230, 215, "app/safety/", [
        "blocklist.py + blocklist.txt", "rules.py  กฎ 3 ความเสี่ยง", "llama_guard.py", "categories.py  หมวด S1-S14",
        "ตรวจขาเข้าและขาออก", "fail-closed"], C_GUARD, "Safety / Guardrails"))
    b.append(box(640, 380, 230, 215, "app/rag.py", [
        "ตัดคำ PyThaiNLP", "เวกเตอร์ TF-IDF", "cosine similarity", "คืน 4 หัวข้อที่ตรงที่สุด"], C_RAG, "RAG: ค้นคลังความรู้"))
    b.append(box(890, 380, 230, 215, "app/slip.py", [
        "ส่งรูปให้ Vision LLM", "แกะ JSON + ลองใหม่ 1 ครั้ง", "ตรวจสลิปจริง ความชัด ชื่อผู้รับ", "แปลง พ.ศ. และยอดเงิน",
        "กันสลิปซ้ำ บันทึก CSV"], C_LLM, "อ่านสลิปการโอนเงิน"))

    b.append(box(390, 640, 230, 130, "app/settings.py + .env", [
        "API key และชื่อโมเดล", "สวิตช์เปิดปิดแต่ละด่าน"], C_DATA, "การตั้งค่า"))
    b.append(box(640, 640, 230, 130, "knowledge/ + prompts/", [
        "คลังความรู้ 80 หัวข้อ", "system prompt 2 โหมด"], C_DATA, "ข้อมูลร้านและคำสั่ง AI"))
    b.append(box(890, 640, 230, 130, "data/ + uploads/", [
        "slips.csv", "รูปสลิปต้นฉบับ"], C_DATA, "บันทึกของเจ้าหน้าที่"))

    b.append(box(390, 800, 355, 72, "app/line.py", [], C_API, "ตรวจลายเซ็น, Reply / Push, ข้อความแจ้งเจ้าหน้าที่"))
    b.append(box(765, 800, 355, 72, "app/llm.py", [], C_API, "จุดเดียวที่เรียกโมเดล และแปล error เป็นภาษาไทย"))

    b.append(box(1200, 560, 290, 312, "OpenRouter", [
        "ตอบคำถาม", "  openai/gpt-4o-mini", "อ่านสลิป (Vision)", "  google/gemini-2.5-flash",
        "ด่านตรวจความปลอดภัย", "  meta-llama/llama-guard-4-12b", "", "POST /chat/completions"], C_EXT, "ผู้ให้บริการโมเดล"))

    b.append(arrow(310, 300, 390, 215, "HTTP request (ข้อความ / รูปสลิป)", 170, 200))
    b.append(arrow(390, 265, 310, 380, "JSON response", 170, 476))
    b.append(arrow(310, 585, 390, 322, "GET /api/slips", 170, 694))
    b.append(arrow(310, 740, 390, 345))
    b.append(arrow(310, 836, 390, 836, "Reply/Push", 350, 826, both=True))
    b.append(arrow(505, 358, 505, 380))
    b.append(arrow(755, 358, 755, 380))
    b.append(arrow(1005, 358, 1005, 380))
    b.append(arrow(505, 640, 505, 595))
    b.append(arrow(755, 595, 755, 640))
    b.append(arrow(1005, 595, 1005, 640))
    b.append(arrow(1120, 836, 1200, 836, "HTTPS", 1160, 826))
    return svg(1520, 920, b)


def dataflow():
    steps = [
        ("Browser / LINE", C_UI, "ลูกค้าพิมพ์คำถาม หรือแนบรูปสลิป ผ่านหน้าเว็บ หรือแชต LINE OA",
         "static/index.html หรือแอป LINE"),
        ("Browser / LINE", C_UI, "เว็บ: chat.js ส่ง POST /api/chat  |  LINE: ส่ง webhook มาที่ POST /line/webhook",
         "LINE: ตรวจลายเซ็น ตอบ 200 ทันที แล้วทำงานต่อเบื้องหลัง พร้อมแสดงสถานะกำลังพิมพ์"),
        ("FastAPI", C_API, "app/main.py: จำกัดจำนวนคำขอ ตรวจชนิดและขนาดรูปจากไบต์จริง สร้าง session",
         "ไม่ผ่าน: ตอบ 429 / 413 / 415 พร้อมข้อความภาษาไทย"),
        ("Guard", C_GUARD, "ด่านขาเข้า: blocklist > กฎ Prompt Injection > กฎ Sensitive Info > Llama Guard 4",
         "app/safety/  ตัวตรวจล่ม = ไม่ผ่าน (fail-closed, ตอบ 503)"),
        ("FastAPI", C_API, "ปิดบังเลขส่วนตัวในข้อความ และติดป้ายคำอ้างที่ยืนยันไม่ได้",
         "rules.mask_pii และ rules.has_unverified_claim"),
        ("RAG", C_RAG, "app/rag.py ค้นคลังความรู้: ตัดคำ > TF-IDF > cosine > 4 หัวข้อที่ตรงที่สุด",
         "ได้ข้อมูลพร้อมรหัสอ้างอิง เช่น FAQ-07, BIKE-11, POL-03"),
        ("LLM", C_LLM, "ประกอบ prompt แล้วเรียก openai/gpt-4o-mini ผ่าน app/llm.py",
         "system prompt + ประวัติ + <วันเวลาปัจจุบัน> + <ข้อมูลร้าน> + <ข้อความลูกค้า>"),
        ("Guard", C_GUARD, "ด่านขาออก: blocklist > Prompt leak > เลขส่วนตัว > Misinformation > Llama Guard 4",
         "ตัวเลขเงินต้องมีในคลังความรู้ ห้ามยืนยันการจองหรือการชำระเงิน"),
        ("FastAPI", C_API, "เก็บประวัติ แล้วตอบ JSON: type, reply, sources, guard, slip, elapsed_ms",
         "log เฉพาะชนิดคำตอบ ด่านที่ทำงาน และเวลา ไม่เก็บข้อความลูกค้า"),
        ("LINE Push API", C_EXT, "แจ้งเจ้าหน้าที่ทาง LINE: คำถามที่บอตตอบไม่ได้ และสรุปสลิปใหม่",
         "ส่งคำถามที่ปิดบังเลขส่วนตัวแล้ว ข้อความที่ถูกด่านบล็อกไม่ถูกส่งต่อ"),
        ("Browser / LINE", C_UI, "เว็บ: chat.js แสดงคำตอบด้วย textContent  |  LINE: ตอบด้วย Reply API",
         "ถ้าเป็นสลิป แสดงสรุปยอด พร้อมสถานะรอเจ้าหน้าที่ตรวจสอบ"),
    ]
    x, w, h, gap, top = 110, 720, 84, 26, 96
    b = [text(30, 40, "แผนภาพการไหลของข้อมูลของ 1 ข้อความ: Buddy Bike Chatbot", 22, 600),
         text(30, 64, "ตัวเลขคือลำดับขั้นตอน สีของกล่องบอกส่วนของระบบที่ทำงาน", 14, 400, MUTED)]
    for i, (lane, fill, main, sub) in enumerate(steps):
        y = top + i * (h + gap)
        b.append(f'<circle cx="60" cy="{y + h / 2}" r="20" fill="{INK}"/>')
        b.append(text(60, y + h / 2 + 6, str(i + 1), 17, 600, "#ffffff", "middle"))
        b.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="{LINE}" stroke-width="1.5"/>')
        b.append(text(x + 16, y + 24, lane.upper(), 11.5, 600, MUTED))
        b.append(text(x + 16, y + 48, main, 15, 600))
        b.append(text(x + 16, y + 70, sub, 13.5, 400, MUTED))
        if i < len(steps) - 1:
            b.append(arrow(x + w / 2, y + h, x + w / 2, y + h + gap))

    def row_y(i):
        return top + i * (h + gap)

    bx = x + w + 60
    # ทางออกเมื่อไม่ผ่านด่านขาเข้า
    b.append(arrow(x + w, row_y(3) + h / 2, bx, row_y(3) + h / 2, "ไม่ผ่าน", x + w + 30, row_y(3) + h / 2 - 8, dashed=True))
    b.append(box(bx, row_y(3) - 14, 350, 112, "ตอบข้อความปฏิเสธทันที", [
        "ไม่เรียก RAG และไม่เรียกโมเดลตอบคำถาม", "guard = input / PROMPT_INJECTION ฯลฯ"], "#ffffff", stroke="#c98b00"))

    # โหมดสลิป (เมื่อมีรูปแนบ)
    sy = row_y(4) + 6
    b.append(arrow(x + w, row_y(4) + h / 2, bx, row_y(4) + h / 2, "มีรูป", x + w + 30, row_y(4) + h / 2 - 8))
    b.append(box(bx, sy, 350, 312, "โหมดสลิป: app/slip.py", [
        "- ส่งรูปให้ Vision LLM ตอบเป็น JSON",
        "- แกะ JSON ลองใหม่ได้ 1 ครั้ง",
        "- รูปเบลอหรือมืด: ขอรูปใหม่",
        "- ไม่ใช่สลิป หรืออ่านยอด/วันที่ไม่ได้: ไม่บันทึก",
        "- แปลง พ.ศ. เป็น ค.ศ. และยอดเงิน",
        "- ทิ้งข้อความในรูปที่เป็นคำสั่งหลอก",
        "- ผู้รับไม่ใช่บัญชีร้าน: สลิปไม่ถูกต้อง",
        "- กันสลิปซ้ำ แล้วบันทึก slips.csv",
        "- โค้ดสร้างข้อความตอบ: รอเจ้าหน้าที่ตรวจสอบ",
        "  (ไม่ยืนยันการชำระเงิน)",
        "แล้วไปขั้นที่ 9"], C_LLM, "ข้ามขั้นที่ 5-8", stroke="#8d6aa8"))

    # ทางออกเมื่อไม่ผ่านด่านขาออก
    b.append(arrow(x + w, row_y(7) + h / 2, bx, row_y(7) + h / 2, "ไม่ผ่าน", x + w + 30, row_y(7) + h / 2 - 8, dashed=True))
    b.append(box(bx, row_y(7) + 4, 350, 96, "แทนที่ด้วยข้อความปลอดภัย", [
        "ทิ้งคำตอบของ LLM ทั้งหมด", "guard = output / MISINFORMATION ฯลฯ"], "#ffffff", stroke="#c98b00"))

    # เส้นกลับไปขั้นที่ 10
    xr = bx + 380
    y10 = row_y(10) + h / 2
    b.append(f'<path d="M{bx + 350} {row_y(3) + 42} L{xr} {row_y(3) + 42} L{xr} {y10} L{x + w + 4} {y10}" stroke="{INK}" '
             f'stroke-width="1.6" stroke-dasharray="6 5" fill="none" marker-end="url(#arrow)"/>')
    b.append(f'<path d="M{bx + 350} {row_y(7) + 52} L{xr} {row_y(7) + 52}" stroke="{INK}" stroke-width="1.6" stroke-dasharray="6 5" fill="none"/>')
    b.append(text(xr - 12, y10 - 10, "ส่งข้อความปฏิเสธกลับไปหาลูกค้า", 12.5, 500, MUTED, "end"))

    height = top + len(steps) * (h + gap) + 10
    return svg(xr + 40, height, b)


if __name__ == "__main__":
    (OUT / "architecture.svg").write_text(architecture(), encoding="utf-8")
    (OUT / "dataflow.svg").write_text(dataflow(), encoding="utf-8")
    print("สร้างแล้ว:", OUT / "architecture.svg", "และ", OUT / "dataflow.svg")
