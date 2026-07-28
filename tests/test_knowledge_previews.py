from __future__ import annotations

import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from marten_runtime.knowledge.embeddings import FakeEmbeddingAdapter
from marten_runtime.knowledge.previews import KnowledgePreviewStore
from tests.http_app_support import build_test_app


TOKEN = "operator-test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
FORM = {
    "title": "Reviewed classic",
    "license": "Public Domain",
    "provenance": "fixed source",
    "calculation_scope": "theory_interpretation",
    "review_status": "reviewed",
    "corpus_type": "theory",
    "content_type": "classical_excerpt_with_marten_commentary",
    "work": "经典",
    "chapter": "第一章",
    "edition_or_source": "fixed revision",
    "source_url": "https://example.test/classic?oldid=1",
    "verification_status": "verified",
}


class KnowledgePreviewTests(unittest.TestCase):
    def _app(self):
        app = build_test_app(env_overrides={"KNOWLEDGE_OPERATOR_TOKEN": TOKEN})
        service = app.state.runtime.knowledge_service
        service.embedding_adapter = FakeEmbeddingAdapter(
            dimension=service.config.embedding.dimension,
            model_id=service.config.embedding.model,
        )
        return app

    def test_preview_has_no_database_side_effect_and_publish_is_idempotent(self) -> None:
        app = self._app()
        client = TestClient(app)
        response = client.post(
            "/knowledge/namespaces/bazi-theory/previews",
            headers=AUTH,
            data=FORM,
            files={"file": ("classic.md", "# 原文\n\n天地之间。".encode(), "text/markdown")},
        )

        self.assertEqual(response.status_code, 201, response.text)
        preview = response.json()
        self.assertEqual(preview["status"], "ready")
        self.assertGreater(preview["chunk_count"], 0)
        self.assertEqual(preview["index_profile"]["chunking"]["target_chars"], 1000)
        self.assertEqual(preview["index_profile"]["embedding"]["profile_id"], "default")
        self.assertEqual(len(preview["chunks"]), preview["chunk_count"])
        self.assertEqual(app.state.runtime.knowledge_service.stats(namespace="bazi-theory")["source_count"], 0)
        self.assertEqual(
            app.state.runtime.knowledge_service.store.list_ingest_jobs(),
            [],
        )

        publish = client.post(
            f"/knowledge/namespaces/bazi-theory/previews/{preview['preview_id']}/publish",
            headers=AUTH,
        )
        repeated = client.post(
            f"/knowledge/namespaces/bazi-theory/previews/{preview['preview_id']}/publish",
            headers=AUTH,
        )

        self.assertEqual(publish.status_code, 202, publish.text)
        self.assertEqual(repeated.status_code, 202, repeated.text)
        self.assertEqual(publish.json()["job_id"], repeated.json()["job_id"])
        final = self._wait(app, publish.json()["job_id"])
        self.assertEqual(final["status"], "completed")
        completed_repeat = client.post(
            f"/knowledge/namespaces/bazi-theory/previews/{preview['preview_id']}/publish",
            headers=AUTH,
        )
        self.assertEqual(completed_repeat.status_code, 202, completed_repeat.text)
        self.assertEqual(completed_repeat.json()["job_id"], publish.json()["job_id"])
        self.assertEqual(app.state.runtime.knowledge_service.stats(namespace="bazi-theory")["source_count"], 1)
        source = app.state.runtime.knowledge_service.store.get_source(
            "bazi-theory", preview["source_id"]
        )
        self.assertEqual(source.metadata["work"], "经典")

    def test_preview_uses_upload_chunk_profile_and_rejects_invalid_bounds(self) -> None:
        app = self._app()
        client = TestClient(app)
        content = ("甲木生于春季，宜察月令。" * 80).encode()

        small = client.post(
            "/knowledge/namespaces/bazi-theory/previews",
            headers=AUTH,
            data={**FORM, "target_chars": "100", "overlap_chars": "10", "max_chars": "120"},
            files={"file": ("classic.md", content, "text/markdown")},
        )
        large = client.post(
            "/knowledge/namespaces/bazi-theory/previews",
            headers=AUTH,
            data={**FORM, "target_chars": "400", "overlap_chars": "20", "max_chars": "450"},
            files={"file": ("classic.md", content, "text/markdown")},
        )
        invalid = client.post(
            "/knowledge/namespaces/bazi-theory/previews",
            headers=AUTH,
            data={**FORM, "target_chars": "100", "overlap_chars": "100", "max_chars": "120"},
            files={"file": ("classic.md", content, "text/markdown")},
        )

        self.assertEqual(small.status_code, 201, small.text)
        self.assertEqual(large.status_code, 201, large.text)
        self.assertGreater(small.json()["chunk_count"], large.json()["chunk_count"])
        self.assertEqual(small.json()["index_profile"]["chunking"]["overlap_chars"], 10)
        self.assertEqual(invalid.status_code, 422, invalid.text)
        self.assertEqual(invalid.json()["error"]["code"], "KNOWLEDGE_CHUNKING_PROFILE_INVALID")

    def test_publish_rejects_tampered_preview_content(self) -> None:
        app = self._app()
        client = TestClient(app)
        response = client.post(
            "/knowledge/namespaces/bazi-theory/previews",
            headers=AUTH,
            data=FORM,
            files={"file": ("classic.md", b"# Original\n\ntext", "text/markdown")},
        )
        preview_id = response.json()["preview_id"]
        path = app.state.runtime.knowledge_service.jobs.staging_root / preview_id / "source.md"
        path.write_text("tampered", encoding="utf-8")

        publish = client.post(
            f"/knowledge/namespaces/bazi-theory/previews/{preview_id}/publish",
            headers=AUTH,
        )

        self.assertEqual(publish.status_code, 409)
        self.assertEqual(publish.json()["error"]["code"], "KNOWLEDGE_PREVIEW_DIGEST_MISMATCH")

    def test_expired_preview_records_and_staging_are_removed_on_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            staging_root = Path(temp) / "uploads"
            preview_id = "kprv_123456789abc"
            staged_directory = staging_root / preview_id
            staged_directory.mkdir(parents=True)
            (staged_directory / "source.md").write_text("content", encoding="utf-8")
            with patch("marten_runtime.knowledge.previews.time.time", return_value=1_000):
                store = KnowledgePreviewStore(staging_root, ttl_seconds=60)
                store.record(
                    preview_id=preview_id,
                    namespace="bazi-theory",
                    staged_file_path=f"{preview_id}/source.md",
                    source={},
                    preview={},
                )

            with patch("marten_runtime.knowledge.previews.time.time", return_value=1_061):
                restarted = KnowledgePreviewStore(staging_root, ttl_seconds=60)

            self.assertEqual(restarted.cleanup_expired(), 0)
            self.assertFalse((restarted.records_root / preview_id).exists())
            self.assertFalse(staged_directory.exists())

    def _wait(self, app, job_id: str) -> dict[str, object]:  # noqa: ANN001
        result: dict[str, object] = {}
        for _ in range(100):
            result = app.state.runtime.knowledge_service.ingest_status(
                namespace="bazi-theory", job_id=job_id
            )
            if result.get("status") in {"completed", "failed", "cancelled"}:
                return result
            time.sleep(0.02)
        return result


if __name__ == "__main__":
    unittest.main()
