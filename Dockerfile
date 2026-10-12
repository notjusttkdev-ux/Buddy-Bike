FROM python:3.12-slim

# ติดตั้ง uv เพื่อให้ได้ dependency ชุดเดียวกับ uv.lock ทุกครั้ง
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app/ ./app/
COPY prompts/ ./prompts/
COPY knowledge/ ./knowledge/
COPY static/ ./static/
COPY blocklist.txt run.py ./
RUN mkdir -p data uploads

# Render กำหนดพอร์ตผ่านตัวแปร PORT ต้อง bind กับ 0.0.0.0:$PORT (ถ้าไม่มี PORT จะใช้ 8000)
CMD ["sh", "-c", "uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
