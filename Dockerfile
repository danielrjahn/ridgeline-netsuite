FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app ./app
COPY smoke.py ./

ENV MINISUITE_DB=/data/minisuite.sqlite \
    MINISUITE_TOKEN=demo-token-ridgeline \
    PORT=8000

EXPOSE 8000

# Seed on every start (idempotent). The SQLite file lives in /data so a mounted
# volume persists it across deploys.
CMD ["sh", "-c", "mkdir -p /data && python -m app.seed && uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
