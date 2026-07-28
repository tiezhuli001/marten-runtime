from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from marten_runtime.knowledge.sqlite_store import SQLiteKnowledgeStore


_NAMESPACE_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SOURCE_ID_PATTERN = re.compile(r"^ksrc_[A-Za-z0-9_-]{1,120}$")
_SHA256_PATTERN = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")
_ALLOWED_SUFFIXES = frozenset({".md", ".txt"})
_GOVERNANCE_STATUSES = frozenset({"draft", "reviewed_baseline", "production_approved"})
_EVIDENCE_KINDS = frozenset(
    {
        "classical_original",
        "historical_commentary",
        "modern_commentary",
        "marten_interpretation",
        "course_notes",
        "case_record",
    }
)
_CLASSICAL_REQUIRED_METADATA = frozenset(
    {
        "work",
        "chapter",
        "edition_or_source",
        "source_url",
        "verification_status",
    }
)


class KnowledgeCorpusSourceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    file: str
    title: str
    kind: str
    uri: str
    version: str
    sha256: str
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract(self) -> "KnowledgeCorpusSourceSpec":
        if not _SOURCE_ID_PATTERN.fullmatch(self.source_id):
            raise ValueError("source_id is invalid")
        if not self.title.strip() or not self.uri.strip() or not self.version.strip():
            raise ValueError("title, uri and version are required")
        if self.kind not in {"markdown", "text"}:
            raise ValueError("kind must be markdown or text")
        if not _SHA256_PATTERN.fullmatch(self.sha256):
            raise ValueError("sha256 must be a 64-character lowercase digest")
        required = {
            "corpus_type",
            "review_status",
            "license",
            "provenance",
            "calculation_scope",
            "content_type",
            "evidence_kind",
        }
        missing = sorted(required - self.metadata.keys())
        if missing:
            raise ValueError(f"metadata is missing required fields: {', '.join(missing)}")
        if str(self.metadata.get("review_status") or "") != "reviewed":
            raise ValueError("review_status must be reviewed")
        if str(self.metadata.get("corpus_type") or "") != "theory":
            raise ValueError("phase-one corpus_type must be theory")
        evidence_kind = str(self.metadata.get("evidence_kind") or "")
        if evidence_kind not in _EVIDENCE_KINDS:
            raise ValueError("evidence_kind is invalid")
        if evidence_kind in {"classical_original", "historical_commentary"}:
            missing_classical = sorted(_CLASSICAL_REQUIRED_METADATA - self.metadata.keys())
            if missing_classical:
                raise ValueError(
                    "classical metadata is missing required fields: "
                    + ", ".join(missing_classical)
                )
        return self

    @property
    def normalized_sha256(self) -> str:
        match = _SHA256_PATTERN.fullmatch(self.sha256)
        assert match is not None
        return match.group(1)


class KnowledgeCorpusManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    release_id: str
    namespace: str
    description: str = ""
    release_metadata: dict[str, object] = Field(default_factory=dict)
    governance: dict[str, str] = Field(default_factory=dict)
    sources: list[KnowledgeCorpusSourceSpec]

    @model_validator(mode="after")
    def validate_contract(self) -> "KnowledgeCorpusManifest":
        if self.schema_version != "knowledge.corpus.v1":
            raise ValueError("schema_version must be knowledge.corpus.v1")
        if not self.release_id.strip():
            raise ValueError("release_id is required")
        if not _NAMESPACE_PATTERN.fullmatch(self.namespace):
            raise ValueError("namespace is invalid")
        if not self.sources:
            raise ValueError("sources must not be empty")
        source_ids = [source.source_id for source in self.sources]
        identities = [(source.uri, source.version) for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source_id values must be unique")
        if len(identities) != len(set(identities)):
            raise ValueError("uri + version identities must be unique")
        if self.governance:
            required_governance = {
                "corpus_owner",
                "reviewer",
                "release_approver",
                "approval_status",
            }
            missing_governance = sorted(required_governance - self.governance.keys())
            if missing_governance:
                raise ValueError(
                    "governance is missing required fields: " + ", ".join(missing_governance)
                )
            approval_status = str(self.governance.get("approval_status") or "").strip()
            if approval_status not in _GOVERNANCE_STATUSES:
                raise ValueError("governance approval_status is invalid")
            if approval_status == "production_approved":
                assigned = (
                    str(self.governance.get(name) or "").strip().lower()
                    for name in ("corpus_owner", "reviewer", "release_approver")
                )
                if any(value in {"", "unassigned", "pending", "tbd"} for value in assigned):
                    raise ValueError("production-approved governance requires named responsibility")
        return self


@dataclass(frozen=True)
class LoadedKnowledgeCorpusSource:
    spec: KnowledgeCorpusSourceSpec
    path: Path
    text: str
    content_bytes: int

    def source_payload(self) -> dict[str, object]:
        return {
            "source_id": self.spec.source_id,
            "title": self.spec.title,
            "kind": self.spec.kind,
            "uri": self.spec.uri,
            "version": self.spec.version,
            "metadata": {
                **self.spec.metadata,
                "content_sha256": self.spec.normalized_sha256,
                "content_bytes": self.content_bytes,
                "corpus_release_id": "",
            },
            "text": self.text,
        }


@dataclass(frozen=True)
class LoadedKnowledgeCorpus:
    manifest_path: Path
    manifest: KnowledgeCorpusManifest
    sources: tuple[LoadedKnowledgeCorpusSource, ...]
    manifest_sha256: str

    def source_payloads(self) -> list[dict[str, object]]:
        payloads: list[dict[str, object]] = []
        for source in self.sources:
            payload = source.source_payload()
            metadata = dict(payload["metadata"])
            metadata["corpus_release_id"] = self.manifest.release_id
            payload["metadata"] = metadata
            payloads.append(payload)
        return payloads


def load_corpus_manifest(path: str | Path) -> LoadedKnowledgeCorpus:
    manifest_path = Path(path).resolve()
    raw = manifest_path.read_bytes()
    manifest = KnowledgeCorpusManifest(**tomllib.loads(raw.decode("utf-8")))
    sources: list[LoadedKnowledgeCorpusSource] = []
    root = manifest_path.parent.resolve()
    for source in manifest.sources:
        relative = Path(source.file)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"source file escapes manifest directory: {source.file}")
        resolved = (root / relative).resolve()
        if root not in resolved.parents:
            raise ValueError(f"source file escapes manifest directory: {source.file}")
        if resolved.suffix.lower() not in _ALLOWED_SUFFIXES:
            raise ValueError(f"source file type is unsupported: {source.file}")
        content = resolved.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if digest != source.normalized_sha256:
            raise ValueError(
                f"source digest mismatch for {source.source_id}: expected {source.normalized_sha256}, got {digest}"
            )
        text = content.decode("utf-8-sig")
        if not text.strip():
            raise ValueError(f"source text is empty: {source.source_id}")
        sources.append(
            LoadedKnowledgeCorpusSource(
                spec=source,
                path=resolved,
                text=text,
                content_bytes=len(content),
            )
        )
    return LoadedKnowledgeCorpus(
        manifest_path=manifest_path,
        manifest=manifest,
        sources=tuple(sources),
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
    )


def plan_corpus_release(
    corpus: LoadedKnowledgeCorpus,
    store: SQLiteKnowledgeStore,
) -> dict[str, object]:
    items: list[dict[str, object]] = []
    expected_source_ids = {source.spec.source_id for source in corpus.sources}
    for source in corpus.sources:
        current = store.get_source(corpus.manifest.namespace, source.spec.source_id)
        if current is None:
            action = "create"
        else:
            expected_metadata = {
                **source.spec.metadata,
                "content_sha256": source.spec.normalized_sha256,
                "content_bytes": source.content_bytes,
                "corpus_release_id": corpus.manifest.release_id,
            }
            action = "unchanged" if (
                current.title == source.spec.title
                and current.kind == source.spec.kind
                and current.uri == source.spec.uri
                and current.version == source.spec.version
                and current.metadata == expected_metadata
            ) else "update"
        items.append(
            {
                "source_id": source.spec.source_id,
                "title": source.spec.title,
                "action": action,
                "sha256": source.spec.normalized_sha256,
            }
        )
    existing, _ = store.list_source_summaries(
        corpus.manifest.namespace,
        page=1,
        page_size=max(1, store.count_sources(corpus.manifest.namespace)),
    )
    drift = [
        {
            "source_id": str(item.get("source_id") or ""),
            "title": str(item.get("title") or ""),
            "uri": str(item.get("uri") or ""),
            "version": str(item.get("version") or ""),
            "action": "drift",
        }
        for item in existing
        if str(item.get("source_id") or "") not in expected_source_ids
    ]
    counts = {
        action: sum(1 for item in items if item["action"] == action)
        for action in ("create", "update", "unchanged")
    }
    return {
        "ok": True,
        "schema_version": corpus.manifest.schema_version,
        "release_id": corpus.manifest.release_id,
        "namespace": corpus.manifest.namespace,
        "manifest_sha256": corpus.manifest_sha256,
        "source_count": len(items),
        "counts": {**counts, "drift": len(drift)},
        "items": items,
        "drift": drift,
    }


def publish_corpus_release(
    corpus: LoadedKnowledgeCorpus,
    service,  # noqa: ANN001
) -> dict[str, object]:
    before = plan_corpus_release(corpus, service.store)
    planned_actions = {
        str(item.get("source_id") or ""): str(item.get("action") or "")
        for item in list(before.get("items") or [])
    }
    results: list[dict[str, object]] = []
    for payload in corpus.source_payloads():
        source_id = str(payload.get("source_id") or "")
        action = planned_actions.get(source_id, "create")
        if action == "unchanged":
            if service.config.embedding.enabled and not _source_embeddings_are_current(
                service,
                namespace=corpus.manifest.namespace,
                source_id=source_id,
            ):
                reindex = service.reindex(
                    namespace=corpus.manifest.namespace,
                    source_id=source_id,
                )
                if not reindex.get("ok"):
                    raise RuntimeError(
                        f"corpus reindex failed for {source_id}: "
                        f"{reindex.get('error_code') or reindex.get('message') or 'unknown error'}"
                    )
                results.append(
                    {
                        "source_id": source_id,
                        "title": str(payload.get("title") or ""),
                        "action": "reindex",
                        "chunk_count": int(reindex.get("chunk_count") or 0),
                        "embedding_status": str(reindex.get("embedding_status") or ""),
                    }
                )
                continue
            results.append(
                {
                    "source_id": source_id,
                    "title": str(payload.get("title") or ""),
                    "action": "unchanged",
                }
            )
            continue
        result = service.ingest_text(
            namespace=corpus.manifest.namespace,
            source=payload,
        )
        if not result.get("ok"):
            raise RuntimeError(
                f"corpus publish failed for {source_id}: "
                f"{result.get('error_code') or result.get('message') or 'unknown error'}"
            )
        embedding_status = str(result.get("embedding_status") or "")
        if service.config.embedding.enabled and embedding_status != "embedded":
            raise RuntimeError(
                f"corpus publish embedding failed for {source_id}: "
                f"embedding_status={embedding_status or 'unknown'}"
            )
        results.append(
            {
                "source_id": source_id,
                "title": str(payload.get("title") or ""),
                "action": action,
                "chunk_count": int(result.get("chunk_count") or 0),
                "embedding_status": embedding_status,
            }
        )
    after = plan_corpus_release(corpus, service.store)
    return {
        "ok": True,
        "action": "publish_corpus_release",
        "release_id": corpus.manifest.release_id,
        "namespace": corpus.manifest.namespace,
        "manifest_sha256": corpus.manifest_sha256,
        "before": before,
        "results": results,
        "after": after,
    }


def _source_embeddings_are_current(service, *, namespace: str, source_id: str) -> bool:  # noqa: ANN001
    chunk_ids = {chunk.chunk_id for chunk in service.store.list_chunks(namespace, source_id=source_id)}
    if not chunk_ids:
        return False
    embedded_ids = {
        record.chunk_id
        for record in service.store.list_embeddings(namespace, service.embedding_config_hash)
    }
    return chunk_ids <= embedded_ids


def corpus_report_json(corpus: LoadedKnowledgeCorpus) -> str:
    payload = {
        "schema_version": corpus.manifest.schema_version,
        "release_id": corpus.manifest.release_id,
        "namespace": corpus.manifest.namespace,
        "manifest_sha256": corpus.manifest_sha256,
        "release_metadata": dict(corpus.manifest.release_metadata),
        "governance": dict(corpus.manifest.governance),
        "source_count": len(corpus.sources),
        "sources": [
            {
                "source_id": source.spec.source_id,
                "title": source.spec.title,
                "uri": source.spec.uri,
                "version": source.spec.version,
                "sha256": source.spec.normalized_sha256,
                "content_bytes": source.content_bytes,
            }
            for source in corpus.sources
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
