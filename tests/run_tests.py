"""ทดสอบแชตบอตกับ LLM จริง แล้วบันทึกผลลงตาราง (คำตอบ + ผ่าน/ไม่ผ่าน + เวลาตอบ)

ต้องเปิดเซิร์ฟเวอร์ไว้ก่อน (uv run python run.py) แล้วรันในอีกหน้าต่างหนึ่ง

    uv run python tests/run_tests.py                      # ครบทุกชุด
    uv run python tests/run_tests.py --only questions     # เฉพาะคำถาม 10 ข้อ
    uv run python tests/run_tests.py --label before_rag   # ตั้งชื่อรอบทดสอบ ใช้ทำผลก่อน-หลัง

ผลลัพธ์อยู่ใน tests/results/ เป็นไฟล์ .md และ .csv (เปิดด้วย Excel ได้)
ผล "ผ่าน/ไม่ผ่าน" ที่สคริปต์ให้ เป็นการคัดกรองด้วยคำสำคัญเท่านั้น
ผู้ทดสอบต้องอ่านคำตอบจริงและยืนยันผลในคอลัมน์ "ผลที่ผู้ทดสอบยืนยัน" ด้วยตนเอง

หมายเหตุ: ระบบไม่บันทึกสลิปซ้ำ ถ้ารันชุดภาพเป็นรอบที่สอง ให้ลบไฟล์ data/slips.csv ก่อน
"""

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

TESTS_DIR = Path(__file__).resolve().parent
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
TITLES = {"questions": "ชุดคำถามทดสอบ 10 ข้อ", "safety": "ชุดทดสอบความปลอดภัย 5 กรณี", "images": "ชุดภาพทดสอบ 5 ภาพ"}


def judge(result: dict, case: dict) -> tuple[str, str]:
    """คัดกรองอัตโนมัติด้วยคำสำคัญและชนิดคำตอบ คืน (ผล, เหตุผล)"""
    if result["status"] != 200:
        return "ไม่ผ่าน", f"HTTP {result['status']}"
    if result["guard_code"] == "DUPLICATE":
        return "ทดสอบใหม่", "สลิปนี้ถูกบันทึกจากรอบก่อน ให้ลบ data/slips.csv แล้วรันใหม่"
    problems = []
    if case.get("expect_type") and result["type"] != case["expect_type"]:
        problems.append(f"ชนิดคำตอบเป็น {result['type']} (คาดหวัง {case['expect_type']})")
    for group in case.get("expect_all", []):
        if not any(option in result["reply"] for option in group.split("|")):
            problems.append(f"ไม่พบ: {group}")
    for word in case.get("expect_none", []):
        if word in result["reply"]:
            problems.append(f"พบคำต้องห้าม: {word}")
    return ("ผ่าน", "") if not problems else ("ไม่ผ่าน", "; ".join(problems))


def call(base_url: str, message: str, image_path: Path | None) -> dict:
    """ส่งหนึ่งคำถาม ใช้ client ใหม่ทุกครั้งเพื่อไม่ให้ประวัติของข้อก่อนหน้ามีผล"""
    files = None
    if image_path is not None:
        files = {"image": (image_path.name, image_path.read_bytes(), MIME.get(image_path.suffix.lower(), "image/png"))}
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=180) as client:
            response = client.post(f"{base_url}/api/chat", data={"message": message}, files=files)
        seconds = round(time.perf_counter() - started, 2)
        data = response.json()
    except Exception as exc:
        return {"status": 0, "type": "error", "reply": f"[เรียก API ไม่สำเร็จ: {exc}]", "guard": "", "guard_code": "",
                "sources": "", "seconds": 0.0}
    guard = data.get("guard") or {}
    return {
        "status": response.status_code,
        "type": data.get("type") or "error",
        "reply": data.get("reply") or f"[{data.get('error')}] {data.get('message')}",
        "guard": " / ".join(x for x in (guard.get("stage"), guard.get("risk"), guard.get("code")) if x),
        "guard_code": guard.get("code", ""),
        "sources": ", ".join(s["id"] for s in data.get("sources", [])),
        "seconds": seconds,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="ทดสอบแชตบอต Buddy Bike")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--only", choices=list(TITLES), help="ทดสอบเฉพาะชุดเดียว")
    parser.add_argument("--label", default="run", help="ชื่อรอบทดสอบ เช่น before_rag, after_rag")
    parser.add_argument("--delay", type=float, default=4.5, help="วินาทีที่รอระหว่างข้อ เพื่อไม่ให้ชน rate limit")
    args = parser.parse_args()

    cases = json.loads((TESTS_DIR / "test_cases.json").read_text(encoding="utf-8"))
    try:
        health = httpx.get(f"{args.base_url}/health", timeout=10).json()
    except Exception as exc:
        print(f"เชื่อมต่อเซิร์ฟเวอร์ที่ {args.base_url} ไม่ได้: {exc}\nกรุณาเปิดเซิร์ฟเวอร์ก่อนด้วย: uv run python run.py")
        return 1
    if not health.get("api_key_set"):
        print("คำเตือน: เซิร์ฟเวอร์ยังไม่ได้ตั้งค่า OPENROUTER_API_KEY ผลทดสอบจะไม่ผ่านทุกข้อ")

    suites = [args.only] if args.only else list(TITLES)
    rows = []
    for suite in suites:
        print(f"\n== {TITLES[suite]} ==")
        for case in cases[suite]:
            image_path = None
            if case.get("image"):
                image_path = TESTS_DIR / "images" / case["image"]
                if not image_path.exists():
                    print(f"  {case['id']} ข้าม: ไม่พบไฟล์ tests/images/{case['image']}")
                    rows.append({"suite": suite, "id": case["id"], "input": f"[ไม่พบไฟล์ {case['image']}]",
                                 "expected": case["expected"], "reply": "", "type": "", "guard": "", "sources": "",
                                 "auto": "ยังไม่ได้ทดสอบ", "reason": "ไม่พบไฟล์ภาพ", "seconds": ""})
                    continue

            result = call(args.base_url, case["message"], image_path)
            auto, reason = judge(result, case)
            shown = case["message"] or "(ไม่มีข้อความ)"
            if image_path:
                shown = f"[ภาพ {image_path.name}" + (f": {case['scene']}" if case.get("scene") else "") + f"] {shown}"
            if suite == "safety":
                shown = f"[{case['risk']}] {shown}"
            rows.append({"suite": suite, "id": case["id"], "input": shown, "expected": case["expected"],
                         "reply": result["reply"], "type": result["type"], "guard": result["guard"],
                         "sources": result["sources"], "auto": auto, "reason": reason, "seconds": result["seconds"]})
            print(f"  {case['id']} {auto:10s} {result['seconds']:>6}s  {result['type']:14s} {result['guard'] or '-'}")
            time.sleep(args.delay)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = TESTS_DIR / "results"
    out_dir.mkdir(exist_ok=True)
    base = out_dir / f"{args.label}_{stamp}"

    with open(f"{base}.csv", "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["suite", "id", "input", "expected", "reply", "type", "guard",
                                               "sources", "auto", "reason", "seconds"])
        writer.writeheader()
        writer.writerows(rows)

    def cell(text) -> str:
        return str(text).replace("|", "\\|").replace("\n", "<br>")

    lines = [f"# บันทึกผลการทดสอบ Buddy Bike Chatbot — รอบ `{args.label}`", "",
             f"- วันที่ทดสอบ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
             f"- โมเดล: ตอบคำถาม `{health.get('chat_model')}`, อ่านสลิป `{health.get('vision_model')}`, "
             f"ด่านตรวจ `{health.get('guard_model')}`",
             f"- การตั้งค่า: RAG={health.get('rag_enabled')} (top_k={health.get('rag_top_k')}), "
             f"กฎในโค้ด={health.get('rules_guard')}, Llama Guard={health.get('llama_guard')}, "
             f"prompt={health.get('prompt_variant')}, คลังความรู้ {health.get('kb_chunks')} หัวข้อ", ""]
    for suite in suites:
        part = [r for r in rows if r["suite"] == suite]
        tested = [r for r in part if r["seconds"] != ""]
        passed = sum(r["auto"] == "ผ่าน" for r in tested)
        times = [r["seconds"] for r in tested]
        lines += [f"## {TITLES[suite]}", "",
                  f"ผลคัดกรองอัตโนมัติ: ผ่าน {passed}/{len(tested)} ข้อ"
                  + (f" | เวลาตอบเฉลี่ย {sum(times) / len(times):.2f} วินาที" if times else ""), "",
                  "| รหัส | สิ่งที่ส่ง | ผลที่คาดหวัง | คำตอบของบอต | ชนิดคำตอบ | ด่านที่ทำงาน | แหล่งอ้างอิง | คัดกรองอัตโนมัติ | เวลาตอบ (วินาที) | ผลที่ผู้ทดสอบยืนยัน |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for r in part:
            auto = r["auto"] + (f" ({r['reason']})" if r["reason"] else "")
            lines.append("| " + " | ".join(cell(x) for x in [
                r["id"], r["input"], r["expected"], r["reply"], r["type"], r["guard"] or "-", r["sources"] or "-",
                auto, r["seconds"], ""]) + " |")
        lines.append("")
    Path(f"{base}.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"\nบันทึกผลแล้วที่:\n  {base}.md\n  {base}.csv")
    print("อย่าลืมอ่านคำตอบจริงแล้วกรอกคอลัมน์ 'ผลที่ผู้ทดสอบยืนยัน' ด้วยตนเอง")
    return 0


if __name__ == "__main__":
    sys.exit(main())
