"""รายการคำต้องห้าม อ่านจากไฟล์ข้อความ (ดัดแปลงจาก Llama Guard Layer ของอาจารย์)

หนึ่งบรรทัดต่อหนึ่งคำ บรรทัดที่ขึ้นต้นด้วย # คือคอมเมนต์
รีโหลดอัตโนมัติเมื่อไฟล์ถูกแก้ ไม่ต้องรีสตาร์ตเซิร์ฟเวอร์

ส่วนที่เพิ่มจากต้นฉบับ: ลบช่องว่างและอักขระล่องหนออกก่อนเทียบ
เพื่อแก้ข้อจำกัดที่ผู้ใช้เลี่ยง blocklist ได้ด้วยการเว้นวรรคกลางคำ
"""

import logging
import os
import re
from pathlib import Path

log = logging.getLogger("buddybike.guard")
_SPACES = re.compile(r"[\s​‌‍﻿]+")


def squash(text: str) -> str:
    """ลบช่องว่างและอักขระล่องหน แล้วแปลงเป็นตัวพิมพ์เล็ก"""
    return _SPACES.sub("", text).casefold()


class Blocklist:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._mtime: float | None = None
        self._terms: list[str] = []

    def _reload_if_changed(self) -> None:
        try:
            mtime = os.stat(self.path).st_mtime
        except OSError:
            if self._mtime is not None or not self._terms:
                log.warning("อ่าน blocklist ไม่ได้: %s (ถือว่าว่าง)", self.path)
            self._mtime, self._terms = None, []
            return
        if mtime == self._mtime:
            return
        lines = self.path.read_text(encoding="utf-8-sig").splitlines()
        self._terms = [squash(ln) for ln in lines if ln.strip() and not ln.strip().startswith("#")]
        self._mtime = mtime
        log.info("โหลด blocklist %d คำ", len(self._terms))

    def matches(self, message: str) -> bool:
        self._reload_if_changed()
        text = squash(message)
        return any(term and term in text for term in self._terms)
