ARG NODE_IMAGE=node:22-bookworm-slim@sha256:6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3
ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b

FROM ${NODE_IMAGE} AS taibu-bridge-builder

WORKDIR /bridge
COPY third_party/taibu_bridge ./
COPY tests/fixtures/bazi /tests/fixtures/bazi
RUN npm ci --omit=dev \
    && npm run verify:upstream \
    && npm run prepare:engine \
    && npm run verify:upstream \
    && npm test \
    && mkdir -p /artifacts/sbom \
    && npm sbom --omit=dev --sbom-format cyclonedx > /artifacts/sbom/taibu-bridge.cdx.json \
    && node scripts/annotate-sbom.mjs /artifacts/sbom/taibu-bridge.cdx.json

FROM ${PYTHON_IMAGE} AS runtime

LABEL org.opencontainers.image.title="marten-runtime" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.description="Marten agent runtime with bundled Taibu Bazi bridge"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    SERVER_HOST=0.0.0.0 \
    SERVER_PORT=8000 \
    TZ=UTC

WORKDIR /app

COPY requirements.txt pyproject.toml README.md LICENSE ./
COPY src ./src
COPY agents ./agents
COPY config ./config
COPY skills ./skills
COPY mcps.example.json ./mcps.example.json
COPY third_party/THIRD_PARTY_LICENSES.md ./third_party/THIRD_PARTY_LICENSES.md
COPY --from=taibu-bridge-builder /usr/local/bin/node /usr/local/bin/node
COPY --from=taibu-bridge-builder /bridge ./third_party/taibu_bridge
COPY --from=taibu-bridge-builder /artifacts/sbom ./sbom

RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.12.0 \
    && pip install --no-cache-dir sqlite-vec==0.1.9 sentence-transformers==5.5.0 \
    && pip install --no-cache-dir . cyclonedx-bom \
    && cyclonedx-py environment --output-format JSON --output-file /app/sbom/python.cdx.json \
    && mkdir -p /app/data \
    && cp /app/mcps.example.json /app/mcps.json \
    && python -m marten_runtime.interfaces.http.container_self_check --json

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD python -c "import json, urllib.request; payload = json.load(urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)); raise SystemExit(0 if payload.get('status') == 'ok' else 1)"

CMD ["python", "-m", "marten_runtime.interfaces.http.container_entrypoint"]
