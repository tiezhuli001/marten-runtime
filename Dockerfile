FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    SERVER_HOST=0.0.0.0 \
    SERVER_PORT=8000

WORKDIR /app

COPY requirements.txt pyproject.toml README.md LICENSE ./
COPY src ./src
COPY apps ./apps
COPY config ./config
COPY skills ./skills
COPY mcps.example.json ./mcps.example.json

RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir .

RUN mkdir -p /app/data \
    && cp /app/mcps.example.json /app/mcps.json

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import json, urllib.request; payload = json.load(urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)); raise SystemExit(0 if payload.get('status') == 'ok' else 1)"

CMD ["python", "-m", "marten_runtime.interfaces.http.serve"]
