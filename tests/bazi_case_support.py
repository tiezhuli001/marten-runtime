from __future__ import annotations

import tempfile
from pathlib import Path

from marten_runtime.bazi_cases.service import BaziCaseService
from marten_runtime.bazi_cases.sqlite_store import SQLiteBaziCaseStore
from marten_runtime.knowledge.config import load_knowledge_config
from marten_runtime.knowledge.service import KnowledgeService


def build_case_service() -> tuple[BaziCaseService, tempfile.TemporaryDirectory]:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    config = load_knowledge_config.from_text(
        f'''
[knowledge]
db_path = "{root / 'knowledge.sqlite3'}"
repo_root = "{root}"
default_namespace = "personal"
model_idle_ttl_seconds = 0

[knowledge.chunking]
target_chars = 500
overlap_chars = 50
max_chars = 800
batch_size = 8

[knowledge.embedding]
enabled = true
provider = "fake"
model = "fake-case-embedding"
local_path = "{root / 'models' / 'embedding'}"
dimension = 16
allow_remote_download = false
use_fp16 = false

[knowledge.reranker]
enabled = true
provider = "fake"
model = "fake-case-reranker"
local_path = "{root / 'models' / 'reranker'}"
allow_remote_download = false
use_fp16 = false
top_n = 20

[knowledge.vector_store]
enabled = true
backend = "json_cosine"

[knowledge.search]
default_top_k = 5
candidate_pool = 30
fts_weight = 0.35
vector_weight = 0.55
metadata_weight = 0.10
reranker_weight = 0.70
'''
    ).knowledge
    knowledge = KnowledgeService(config)
    return BaziCaseService(SQLiteBaziCaseStore(root / "cases.sqlite3"), knowledge), tmp


def bazi_result(pillars: list[str], *, fingerprint_char: str = "a") -> dict[str, object]:
    return {
        "ok": True,
        "inputFingerprint": "sha256:" + fingerprint_char * 64,
        "engine": {"name": "mock-bazi", "version": "1"},
        "resultSchemaVersion": "bazi.chart.v1",
        "timeBasis": {
            "requested": "clock",
            "timezone": "Asia/Shanghai",
            "effectiveBirthDateTime": "1990-01-01T12:00:00",
        },
        "result": {"四柱": pillars},
    }
