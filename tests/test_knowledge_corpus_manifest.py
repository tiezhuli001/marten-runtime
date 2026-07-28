from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from marten_runtime.knowledge.config import load_knowledge_config
from marten_runtime.knowledge.corpus import load_corpus_manifest, plan_corpus_release, publish_corpus_release
from marten_runtime.knowledge.models import KnowledgeSource
from marten_runtime.knowledge.service import KnowledgeService
from marten_runtime.knowledge.sqlite_store import SQLiteKnowledgeStore


class KnowledgeCorpusManifestTests(unittest.TestCase):
    def test_load_validates_digest_metadata_and_resolved_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "sources" / "classic.md"
            source.parent.mkdir()
            source.write_text("# 原文\n\n天地之间。", encoding="utf-8")
            manifest = self._write_manifest(root, source)

            loaded = load_corpus_manifest(manifest)

            self.assertEqual(loaded.manifest.release_id, "bazi-theory-v1")
            self.assertEqual(loaded.manifest.namespace, "bazi-theory")
            self.assertEqual(loaded.sources[0].path, source.resolve())
            self.assertIn("天地之间", loaded.sources[0].text)
            self.assertEqual(
                loaded.source_payloads()[0]["metadata"]["corpus_release_id"],
                "bazi-theory-v1",
            )

    def test_load_rejects_digest_mismatch_path_escape_and_unreviewed_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "classic.md"
            source.write_text("正文", encoding="utf-8")
            manifest = self._write_manifest(root, source, digest="0" * 64)
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                load_corpus_manifest(manifest)

            manifest.write_text(
                manifest.read_text(encoding="utf-8").replace('file = "classic.md"', 'file = "../classic.md"'),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "escapes manifest directory"):
                load_corpus_manifest(manifest)

            manifest = self._write_manifest(root, source)
            manifest.write_text(
                manifest.read_text(encoding="utf-8").replace('review_status = "reviewed"', 'review_status = "draft"'),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "review_status must be reviewed"):
                load_corpus_manifest(manifest)

    def test_production_approval_requires_named_governance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "classic.md"
            source.write_text("正文", encoding="utf-8")
            manifest = self._write_manifest(root, source)
            manifest.write_text(
                manifest.read_text(encoding="utf-8")
                + '''\n[governance]\ncorpus_owner = "unassigned"\nreviewer = "Reviewer"\nrelease_approver = "Approver"\napproval_status = "production_approved"\n''',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "requires named responsibility"):
                load_corpus_manifest(manifest)

    def test_classical_evidence_requires_citation_metadata_regardless_of_content_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "classic.md"
            source.write_text("正文", encoding="utf-8")
            manifest = self._write_manifest(root, source)
            text = manifest.read_text(encoding="utf-8")
            text = text.replace(
                'content_type = "classical_excerpt_with_marten_commentary"',
                'content_type = "theory_document"',
            ).replace('chapter = "第一章"\n', "")
            manifest.write_text(text, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "classical metadata.*chapter"):
                load_corpus_manifest(manifest)

    def test_plan_reports_create_update_unchanged_and_drift_without_deleting(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "classic.md"
            source.write_text("正文", encoding="utf-8")
            loaded = load_corpus_manifest(self._write_manifest(root, source))
            store = SQLiteKnowledgeStore(root / "knowledge.sqlite3")

            created = plan_corpus_release(loaded, store)
            self.assertEqual(created["counts"], {"create": 1, "update": 0, "unchanged": 0, "drift": 0})

            payload = loaded.source_payloads()[0]
            current = KnowledgeSource.new(
                namespace="bazi-theory",
                source_id=str(payload["source_id"]),
                title=str(payload["title"]),
                kind=str(payload["kind"]),
                uri=str(payload["uri"]),
                version=str(payload["version"]),
                metadata=dict(payload["metadata"]),
            )
            store.upsert_source(current)
            store.upsert_source(
                KnowledgeSource.new(
                    namespace="bazi-theory",
                    source_id="ksrc_drift",
                    title="Drift",
                    kind="text",
                    uri="local://drift",
                    version="v1",
                )
            )
            unchanged = plan_corpus_release(loaded, store)
            self.assertEqual(unchanged["counts"], {"create": 0, "update": 0, "unchanged": 1, "drift": 1})
            self.assertEqual(unchanged["drift"][0]["source_id"], "ksrc_drift")

            store.upsert_source(current.model_copy(update={"version": "old"}))
            updated = plan_corpus_release(loaded, store)
            self.assertEqual(updated["counts"]["update"], 1)

    def test_publish_is_idempotent_and_repairs_missing_embeddings(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "classic.md"
            source.write_text("# 古籍原文\n\n天地之间。\n\n# Marten 释义\n\n用于测试。", encoding="utf-8")
            loaded = load_corpus_manifest(self._write_manifest(root, source))
            service = KnowledgeService(self._config(root))

            first = publish_corpus_release(loaded, service)
            first_chunks = [chunk.model_dump(mode="json") for chunk in service.store.list_chunks("bazi-theory")]
            first_source = service.store.get_source("bazi-theory", "ksrc_classic_v1")

            second = publish_corpus_release(loaded, service)
            second_chunks = [chunk.model_dump(mode="json") for chunk in service.store.list_chunks("bazi-theory")]
            second_source = service.store.get_source("bazi-theory", "ksrc_classic_v1")

            self.assertEqual(first["before"]["counts"]["create"], 1)
            self.assertEqual(first["after"]["counts"]["unchanged"], 1)
            self.assertEqual(second["before"]["counts"]["unchanged"], 1)
            self.assertEqual(second["results"][0]["action"], "unchanged")
            self.assertEqual(first_chunks, second_chunks)
            self.assertEqual(first_source, second_source)
            self.assertEqual(first_source.metadata["corpus_release_id"], "bazi-theory-v1")

            service.store.clear_embeddings("bazi-theory")
            repaired = publish_corpus_release(loaded, service)

            self.assertEqual(repaired["before"]["counts"]["unchanged"], 1)
            self.assertEqual(repaired["results"][0]["action"], "reindex")
            self.assertEqual(repaired["results"][0]["embedding_status"], "embedded")
            self.assertEqual(
                len(service.store.list_embeddings("bazi-theory", service.embedding_config_hash)),
                len(service.store.list_chunks("bazi-theory")),
            )

    def test_plan_and_publish_apply_metadata_only_manifest_updates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "classic.md"
            source.write_text("# 古籍原文\n\n天地之间。", encoding="utf-8")
            manifest = self._write_manifest(root, source)
            service = KnowledgeService(self._config(root))
            publish_corpus_release(load_corpus_manifest(manifest), service)

            manifest.write_text(
                manifest.read_text(encoding="utf-8").replace(
                    'provenance = "fixed public source"',
                    'provenance = "corrected fixed public source"',
                ),
                encoding="utf-8",
            )
            updated = load_corpus_manifest(manifest)

            plan = plan_corpus_release(updated, service.store)
            published = publish_corpus_release(updated, service)

            self.assertEqual(plan["counts"]["update"], 1)
            self.assertEqual(published["results"][0]["action"], "update")
            stored = service.store.get_source("bazi-theory", "ksrc_classic_v1")
            self.assertEqual(stored.metadata["provenance"], "corrected fixed public source")

    def _write_manifest(self, root: Path, source: Path, *, digest: str | None = None) -> Path:
        resolved_digest = digest or hashlib.sha256(source.read_bytes()).hexdigest()
        relative = source.relative_to(root).as_posix()
        manifest = root / "manifest.toml"
        manifest.write_text(
            f'''schema_version = "knowledge.corpus.v1"
release_id = "bazi-theory-v1"
namespace = "bazi-theory"
description = "test"

[[sources]]
source_id = "ksrc_classic_v1"
file = "{relative}"
title = "经典"
kind = "markdown"
uri = "https://example.test/classic?oldid=1"
version = "oldid-1"
sha256 = "{resolved_digest}"

[sources.metadata]
corpus_type = "theory"
review_status = "reviewed"
license = "Public Domain"
provenance = "fixed public source"
calculation_scope = "theory_interpretation"
content_type = "classical_excerpt_with_marten_commentary"
evidence_kind = "classical_original"
work = "经典"
chapter = "第一章"
edition_or_source = "fixed revision"
source_url = "https://example.test/classic?oldid=1"
verification_status = "verified"
''',
            encoding="utf-8",
        )
        return manifest

    def _config(self, root: Path):  # noqa: ANN202
        return load_knowledge_config.from_text(
            f'''
[knowledge]
db_path = "{root / 'knowledge.sqlite3'}"
repo_root = "{root}"
default_namespace = "personal"
model_idle_ttl_seconds = 300

[knowledge.chunking]
target_chars = 80
overlap_chars = 10
max_chars = 120
batch_size = 4

[knowledge.embedding]
enabled = true
provider = "fake"
model = "fake-embedding"
local_path = "{root / 'models' / 'embedding'}"
dimension = 8
allow_remote_download = false
use_fp16 = false

[knowledge.reranker]
enabled = true
provider = "fake"
model = "fake-reranker"
local_path = "{root / 'models' / 'reranker'}"
allow_remote_download = false
use_fp16 = false
top_n = 10

[knowledge.vector_store]
enabled = true
backend = "json_cosine"

[knowledge.search]
default_top_k = 5
candidate_pool = 20
fts_weight = 1.0
vector_weight = 1.0
metadata_weight = 0.2
reranker_weight = 2.0
'''
        ).knowledge


if __name__ == "__main__":
    unittest.main()
