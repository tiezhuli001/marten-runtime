from __future__ import annotations

import shutil
from pathlib import Path
from textwrap import dedent


_EVAL_KNOWLEDGE_CONFIG = dedent(
    """
    [knowledge]
    db_path = "data/knowledge/knowledge.sqlite3"
    default_namespace = "personal"
    model_idle_ttl_seconds = 300
    file_encoding = "auto"

    [knowledge.chunking]
    target_chars = 1000
    overlap_chars = 150
    max_chars = 1600
    batch_size = 64

    [knowledge.embedding]
    enabled = true
    provider = "fake"
    model = "fake-embedding"
    local_path = "data/models/fake/embedding"
    dimension = 8
    allow_remote_download = false
    use_fp16 = false

    [knowledge.reranker]
    enabled = true
    provider = "fake"
    model = "fake-reranker"
    local_path = "data/models/fake/reranker"
    allow_remote_download = false
    use_fp16 = false
    top_n = 10

    [knowledge.vector_store]
    backend = "json_cosine"
    enabled = true

    [knowledge.search]
    default_top_k = 5
    candidate_pool = 30
    fts_weight = 0.35
    vector_weight = 0.55
    metadata_weight = 0.10
    reranker_weight = 0.70
    """
).strip() + "\n"


def copy_repo_scaffold(
    source_repo_root: Path,
    workspace_root: Path,
    *,
    include_mcp: bool,
) -> None:
    for name in ("config", "agents", "skills"):
        source = source_repo_root / name
        if source.exists():
            shutil.copytree(source, workspace_root / name)
    if include_mcp:
        for name in ("mcps.json", "mcps.example.json"):
            source = source_repo_root / name
            if source.exists():
                shutil.copy2(source, workspace_root / name)
    (workspace_root / "data").mkdir(parents=True, exist_ok=True)
    models_source = source_repo_root / "data" / "models"
    if models_source.exists():
        (workspace_root / "data" / "models").symlink_to(models_source.resolve(), target_is_directory=True)
    fixtures_source = source_repo_root / "evals" / "fixtures"
    if fixtures_source.exists():
        fixtures_target = workspace_root / "evals" / "fixtures"
        fixtures_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(fixtures_source, fixtures_target)
    config_target = workspace_root / "config"
    config_target.mkdir(parents=True, exist_ok=True)
    (config_target / "knowledge.toml").write_text(_EVAL_KNOWLEDGE_CONFIG, encoding="utf-8")
