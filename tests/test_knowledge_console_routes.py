from __future__ import annotations

import re
import time
import unittest
from unittest.mock import Mock

from fastapi.testclient import TestClient

from marten_runtime.knowledge.embeddings import FakeEmbeddingAdapter
from tests.http_app_support import build_test_app


TOKEN = "operator-test-token"
ENCODED_SOURCE_URL = "https://example.test/%E7%A9%B7%E9%80%9A%E5%AE%9D%E9%89%B4?oldid=1"


class KnowledgeConsoleRouteTests(unittest.TestCase):
    def _client(self):  # noqa: ANN202
        app = build_test_app(env_overrides={"KNOWLEDGE_OPERATOR_TOKEN": TOKEN})
        service = app.state.runtime.knowledge_service
        service.embedding_adapter = FakeEmbeddingAdapter(
            dimension=service.config.embedding.dimension,
            model_id=service.config.embedding.model,
        )
        client = TestClient(app)
        login = client.post(
            "/knowledge/console/login",
            data={"token": TOKEN},
            follow_redirects=False,
        )
        self.assertEqual(login.status_code, 303)
        home = client.get("/knowledge/console?namespace=bazi-theory")
        self.assertEqual(home.status_code, 200, home.text)
        csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', home.text)
        self.assertIsNotNone(csrf_match)
        return app, client, str(csrf_match.group(1))

    def test_console_classic_preview_publish_search_reindex_and_delete(self) -> None:
        app, client, csrf = self._client()
        service = app.state.runtime.knowledge_service
        production_dashboard = client.get("/knowledge/console?namespace=bazi-theory")
        self.assertIn("经典书籍正式库", production_dashboard.text)
        self.assertNotIn("导入草稿", production_dashboard.text)
        dashboard = client.get("/knowledge/console?namespace=bazi-theory-sandbox")
        self.assertIn("经典书籍草稿箱", dashboard.text)
        self.assertIn("导入草稿", dashboard.text)
        self.assertIn("导入任务", dashboard.text)
        self.assertIn("标题（可选）", dashboard.text)
        self.assertIn("分段与向量设置", dashboard.text)
        self.assertIn("Embedding profile", dashboard.text)
        self.assertIn("证据类型", dashboard.text)
        self.assertIn("本次检索参数", dashboard.text)
        self.assertNotIn("<label>License</label>", dashboard.text)
        self.assertNotIn("<label>篇章</label>", dashboard.text)
        preview = client.post(
            "/knowledge/console/namespaces/bazi-theory-sandbox/previews",
            data={
                "csrf_token": csrf,
                "title": "穷通宝鉴摘录",
                "source_url": ENCODED_SOURCE_URL,
                "target_chars": "100",
                "overlap_chars": "10",
                "max_chars": "140",
                "embedding_profile_id": "default",
                "evidence_kind": "classical_original",
            },
            files={"file": ("qiongtong.md", "# 甲木\n\n甲木生于春季，宜察月令。".encode(), "text/markdown")},
        )
        self.assertEqual(preview.status_code, 201, preview.text)
        self.assertIn("内容预览", preview.text)
        self.assertIn("https://example.test/穷通宝鉴?oldid=1", preview.text)
        self.assertIn("保存到草稿箱", preview.text)
        self.assertIn("target 100", preview.text)
        self.assertIn("全部 Chunks", preview.text)
        self.assertEqual(service.stats(namespace="bazi-theory-sandbox")["source_count"], 0)
        preview_id = re.search(r"kprv_[0-9a-f]{12}", preview.text)
        source_id = re.search(r"ksrc_[0-9a-f]{20}", preview.text)
        self.assertIsNotNone(preview_id)
        self.assertIsNotNone(source_id)

        published = client.post(
            f"/knowledge/console/namespaces/bazi-theory-sandbox/previews/{preview_id.group(0)}/publish",
            data={"csrf_token": csrf},
        )
        self.assertEqual(published.status_code, 202, published.text)
        job_match = re.search(r"kjob_[0-9a-f]{12}", published.text)
        self.assertIsNotNone(job_match)
        final = self._wait(service, "bazi-theory-sandbox", str(job_match.group(0)))
        self.assertEqual(final["status"], "completed")
        stored_source = service.store.get_source("bazi-theory-sandbox", str(source_id.group(0)))
        self.assertIsNotNone(stored_source)
        self.assertEqual(stored_source.uri, ENCODED_SOURCE_URL)
        self.assertEqual(stored_source.metadata["license"], "not-recorded")
        self.assertEqual(stored_source.metadata["provenance"], ENCODED_SOURCE_URL)
        self.assertEqual(stored_source.metadata["review_status"], "draft")
        self.assertEqual(stored_source.metadata["evidence_kind"], "classical_original")
        self.assertEqual(stored_source.metadata["index_profile"]["chunking"]["target_chars"], 100)

        home = client.get("/knowledge/console?namespace=bazi-theory-sandbox")
        self.assertEqual(home.status_code, 200)
        self.assertIn("穷通宝鉴摘录", home.text)
        self.assertIn(str(job_match.group(0)), home.text)

        draft_detail_path = f"/knowledge/console/namespaces/bazi-theory-sandbox/sources/{source_id.group(0)}"
        draft_detail = client.get(draft_detail_path)
        self.assertEqual(draft_detail.status_code, 200, draft_detail.text)
        self.assertIn("审核通过并发布", draft_detail.text)
        approved = client.post(
            f"{draft_detail_path}/approve",
            data={"csrf_token": csrf},
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertIn("审核通过并已发布", approved.text)
        self.assertIsNone(service.store.get_source("bazi-theory-sandbox", str(source_id.group(0))))
        approved_source = service.store.get_source("bazi-theory", str(source_id.group(0)))
        self.assertIsNotNone(approved_source)
        self.assertEqual(approved_source.metadata["review_status"], "reviewed")
        self.assertEqual(approved_source.metadata["approval_status"], "approved")
        self.assertEqual(approved_source.metadata["approved_from_namespace"], "bazi-theory-sandbox")
        self.assertEqual(approved_source.metadata["evidence_kind"], "classical_original")

        search = client.post(
            "/knowledge/console/namespaces/bazi-theory/search",
            data={"csrf_token": csrf, "query": "甲木春季月令"},
        )
        self.assertEqual(search.status_code, 200, search.text)
        self.assertIn("检索试查", search.text)
        self.assertIn("穷通宝鉴摘录", search.text)
        self.assertIn("score", search.text.lower())
        self.assertIn("Embedding", search.text)
        self.assertIn("AI 解释", search.text)
        tuned_search = client.post(
            "/knowledge/console/namespaces/bazi-theory/search",
            data={
                "csrf_token": csrf,
                "query": "甲木春季月令",
                "top_k": "2",
                "candidate_pool": "4",
                "fts_weight": "1",
                "vector_weight": "2",
                "metadata_weight": "0",
                "reranker_weight": "1",
            },
        )
        self.assertEqual(tuned_search.status_code, 200, tuned_search.text)

        detail_path = f"/knowledge/console/namespaces/bazi-theory/sources/{source_id.group(0)}"
        detail = client.get(detail_path)
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertIn("甲木生于春季", detail.text)
        self.assertIn("https://example.test/穷通宝鉴?oldid=1", detail.text)
        self.assertNotIn("%E7%A9%B7%E9%80%9A", detail.text.split("<pre>", maxsplit=1)[0])

        reindex = client.post(
            f"{detail_path}/reindex",
            data={"csrf_token": csrf},
        )
        self.assertEqual(reindex.status_code, 200, reindex.text)
        self.assertIn("Source reindex 已完成", reindex.text)

        rejected_delete = client.post(
            f"{detail_path}/delete",
            data={"csrf_token": csrf, "confirm_source_id": "wrong"},
        )
        self.assertEqual(rejected_delete.status_code, 409)
        deleted = client.post(
            f"{detail_path}/delete",
            data={"csrf_token": csrf, "confirm_source_id": source_id.group(0)},
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(service.stats(namespace="bazi-theory")["source_count"], 0)

    def test_invalid_namespace_cannot_reindex_default_namespace(self) -> None:
        app, client, csrf = self._client()
        service = app.state.runtime.knowledge_service
        service.reindex = Mock(side_effect=AssertionError("default namespace was mutated"))

        response = client.post(
            "/knowledge/console/namespaces/INVALID!/reindex",
            data={"csrf_token": csrf, "confirm": "reindex"},
        )

        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"]["code"], "KNOWLEDGE_NAMESPACE_INVALID")
        service.reindex.assert_not_called()

    def test_console_preview_defaults_title_and_source_metadata(self) -> None:
        _, client, csrf = self._client()

        preview = client.post(
            "/knowledge/console/namespaces/bazi-theory-sandbox/previews",
            data={"csrf_token": csrf},
            files={"file": ("ziping-notes.md", "# 用神\n\n月令为先。".encode(), "text/markdown")},
        )

        self.assertEqual(preview.status_code, 201, preview.text)
        self.assertIn("ziping-notes", preview.text)
        self.assertIn("console-upload:ziping-notes.md", preview.text)
        self.assertIn("sha256:", preview.text)
        self.assertIn("modern_commentary", preview.text)

    @staticmethod
    def _wait(service, namespace: str, job_id: str) -> dict[str, object]:  # noqa: ANN001
        result: dict[str, object] = {}
        for _ in range(100):
            result = service.ingest_status(namespace=namespace, job_id=job_id)
            if result.get("status") in {"completed", "failed", "cancelled"}:
                return result
            time.sleep(0.02)
        return result


if __name__ == "__main__":
    unittest.main()
