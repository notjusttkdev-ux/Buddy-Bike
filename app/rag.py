"""RAG ส่วนค้นคืน (Retrieval) ของร้าน Buddy Bike

ขั้นตอน (ตรงกับแผนภาพ RAG ใน Week 9)
  ช่วงเตรียมข้อมูล:  อ่านไฟล์ .md -> ตัดเป็น chunk ตามหัวข้อ "## " -> ตัดคำ -> แปลงเป็นเวกเตอร์ TF-IDF
  ช่วงตอบคำถาม:      ตัดคำคำถาม -> แปลงเป็นเวกเตอร์ -> วัด cosine similarity -> คืน chunk ที่ใกล้ที่สุด

เวกเตอร์ใช้ TF-IDF ตามสูตรใน Week 2:  TF-IDF = TF x log((N+1)/(DF+1))
ข้อดีคือไม่ต้องเรียก embedding API ผลลัพธ์เหมือนเดิมทุกครั้ง และตรวจสอบย้อนกลับได้
"""

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pythainlp.tokenize import word_tokenize

_KEEP = re.compile(r"[0-9A-Za-z฀-๿]")


@dataclass
class Chunk:
    id: str          # เช่น FAQ-07, BIKE-11, POL-03
    title: str
    text: str
    source: str      # ชื่อไฟล์ต้นทาง


def load_chunks(knowledge_dir: Path) -> list[Chunk]:
    """อ่านทุกไฟล์ .md แล้วตัดเป็น chunk ตามหัวข้อระดับ 2 (หนึ่งหัวข้อ = หนึ่งเรื่อง)"""
    chunks: list[Chunk] = []
    for path in sorted(knowledge_dir.glob("*.md")):
        parts = re.split(r"^## +", path.read_text(encoding="utf-8"), flags=re.MULTILINE)
        for part in parts[1:]:                      # parts[0] คือส่วนหัวไฟล์ ไม่ใช้
            heading, _, body = part.partition("\n")
            chunk_id, _, title = heading.strip().partition(" ")
            chunks.append(Chunk(chunk_id, title.strip(), body.strip(), path.name))
    return chunks


def tokenize(text: str) -> list[str]:
    """ตัดคำไทยด้วย PyThaiNLP (Week 2) และเพิ่ม trigram ของตัวอักษร

    trigram ช่วยกรณีที่ตัวตัดคำตัดไม่ตรงกัน เช่น 'วางมัดจำ' กับ 'มัดจำ'
    """
    text = text.lower()
    words = [w for w in word_tokenize(text, engine="newmm", keep_whitespace=False) if _KEEP.search(w)]
    compact = "".join(ch for ch in text if _KEEP.match(ch))
    trigrams = ["#" + compact[i : i + 3] for i in range(len(compact) - 2)]
    return words + trigrams


class KnowledgeBase:
    def __init__(self, knowledge_dir: Path):
        self.chunks = load_chunks(knowledge_dir)
        if not self.chunks:
            raise RuntimeError(f"ไม่พบคลังความรู้ใน {knowledge_dir}")

        # หัวข้อถูกนับซ้ำ 2 ครั้ง เพื่อให้คำในหัวข้อมีน้ำหนักมากกว่าเนื้อหา
        docs = [tokenize(f"{c.title} {c.title} {c.text}") for c in self.chunks]
        n = len(docs)
        df = Counter(term for doc in docs for term in set(doc))
        self.idf = {term: math.log((n + 1) / (count + 1)) for term, count in df.items()}
        self.vectors = [self._vectorize(doc) for doc in docs]
        self.full_text = "\n".join(f"{c.title}\n{c.text}" for c in self.chunks)

    def _vectorize(self, tokens: list[str]) -> dict[str, float]:
        if not tokens:
            return {}
        tf = Counter(tokens)
        vec = {t: (c / len(tokens)) * self.idf.get(t, 0.0) for t, c in tf.items()}
        norm = math.sqrt(sum(v * v for v in vec.values()))
        return {t: v / norm for t, v in vec.items()} if norm else {}

    def search(self, query: str, top_k: int = 4, min_score: float = 0.0) -> list[dict]:
        """คืน chunk ที่ใกล้คำถามที่สุด เรียงจากคะแนนมากไปน้อย"""
        q = self._vectorize(tokenize(query))
        scored = []
        for chunk, vec in zip(self.chunks, self.vectors):
            score = sum(w * vec.get(t, 0.0) for t, w in q.items())   # cosine (เวกเตอร์ถูก normalize แล้ว)
            if score >= min_score and score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            {"id": c.id, "title": c.title, "text": c.text, "source": c.source, "score": round(s, 4)}
            for s, c in scored[:top_k]
        ]


def format_context(results: list[dict]) -> str:
    """จัดรูป chunk ที่ค้นได้ให้เป็นข้อความสำหรับแนบเข้า prompt (ขั้น Augmentation)"""
    if not results:
        return "(ไม่พบข้อมูลที่เกี่ยวข้องในคลังความรู้ของร้าน)"
    return "\n\n".join(f"[{r['id']}] {r['title']}\n{r['text']}" for r in results)
