import unittest
from unittest.mock import Mock

from fastapi.testclient import TestClient

from marten_runtime.knowledge.embeddings import FakeEmbeddingAdapter
from marten_runtime.knowledge.models import KnowledgeSource
from marten_runtime.interfaces.http.runtime_diagnostics import serialize_runtime_diagnostics
from tests.http_app_support import build_test_app


TOKEN = "operator-test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


class KnowledgeOperatorHTTPTests(unittest.TestCase):
    def _app(self, *, configured: bool = True):
        app = build_test_app(
            env_overrides={"KNOWLEDGE_OPERATOR_TOKEN": TOKEN} if configured else None
        )
        service = app.state.runtime.knowledge_service
        service.embedding_adapter = FakeEmbeddingAdapter(
            dimension=service.config.embedding.dimension,
            model_id=service.config.embedding.model,
        )
        return app

    def test_router_is_absent_when_operator_token_is_missing(self) -> None:
        app = self._app(configured=False)

        response = TestClient(app).get("/knowledge/namespaces")

        self.assertEqual(response.status_code, 404)

    def test_all_authentication_failures_use_fixed_envelope_before_service_calls(self) -> None:
        app = self._app()
        service = app.state.runtime.knowledge_service
        service.store.list_namespace_summaries = Mock(side_effect=AssertionError("service called"))
        client = TestClient(app)

        for headers in ({}, {"Authorization": TOKEN}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer wrong"}):
            with self.subTest(headers=headers):
                response = client.get("/knowledge/namespaces", headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["www-authenticate"], "Bearer")
                self.assertEqual(
                    response.json(),
                    {
                        "ok": False,
                        "error": {
                            "code": "KNOWLEDGE_OPERATOR_UNAUTHORIZED",
                            "message": "operator authorization failed",
                            "retryable": False,
                        },
                    },
                )
        service.store.list_namespace_summaries.assert_not_called()

    def test_queries_use_fixed_pagination_sorting_and_envelopes(self) -> None:
        app = self._app()
        service = app.state.runtime.knowledge_service
        first = service.ingest_text(
            namespace="bazi",
            source={"title": "Older", "kind": "text", "uri": "local://older", "text": "甲木生于春季"},
        )
        second = service.ingest_text(
            namespace="bazi",
            source={"title": "Newer", "kind": "text", "uri": "local://newer", "text": "乙木生于春季"},
        )
        job_id = service.jobs.create_job(namespace="bazi", source_title="Queued")
        client = TestClient(app)

        namespaces = client.get("/knowledge/namespaces", headers=AUTH)
        sources = client.get("/knowledge/namespaces/bazi/sources?page=1&page_size=1", headers=AUTH)
        chunks = client.get(
            f"/knowledge/namespaces/bazi/sources/{second['source_id']}/chunks",
            headers=AUTH,
        )
        jobs = client.get("/knowledge/namespaces/bazi/jobs", headers=AUTH)

        self.assertEqual(namespaces.status_code, 200)
        self.assertEqual(namespaces.json()["items"][0]["namespace"], "bazi")
        self.assertEqual(namespaces.json()["items"][0]["source_count"], 2)
        self.assertEqual(sources.status_code, 200)
        self.assertEqual(sources.json()["total"], 2)
        self.assertEqual(sources.json()["page_size"], 1)
        self.assertEqual(sources.json()["items"][0]["source_id"], second["source_id"])
        self.assertEqual(chunks.status_code, 200)
        self.assertEqual(chunks.json()["items"][0]["source_id"], second["source_id"])
        self.assertIn("text_preview", chunks.json()["items"][0])
        self.assertNotIn("text", chunks.json()["items"][0])
        self.assertEqual(jobs.status_code, 200)
        self.assertEqual(jobs.json()["items"][0]["job_id"], job_id)
        self.assertEqual(first["namespace"], "bazi")

    def test_invalid_pagination_and_missing_resources_use_fixed_errors(self) -> None:
        app = self._app()
        client = TestClient(app)

        invalid = client.get("/knowledge/namespaces/bazi/sources?page=0", headers=AUTH)
        missing_chunks = client.get(
            "/knowledge/namespaces/bazi/sources/missing/chunks",
            headers=AUTH,
        )
        missing_delete = client.delete(
            "/knowledge/namespaces/bazi/sources/missing",
            headers=AUTH,
        )

        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(invalid.json()["error"]["code"], "KNOWLEDGE_PAGINATION_INVALID")
        self.assertEqual(missing_chunks.status_code, 404)
        self.assertEqual(missing_chunks.json()["error"]["code"], "KNOWLEDGE_SOURCE_NOT_FOUND")
        self.assertEqual(missing_delete.status_code, 404)
        self.assertEqual(missing_delete.json()["error"]["code"], "KNOWLEDGE_SOURCE_NOT_FOUND")

    def test_delete_reindex_and_stats_reuse_knowledge_service(self) -> None:
        app = self._app()
        service = app.state.runtime.knowledge_service
        source = service.ingest_text(
            namespace="bazi",
            source={"title": "Theory", "kind": "text", "uri": "local://theory", "text": "甲木生于春季"},
        )
        client = TestClient(app)

        reindex = client.post("/knowledge/namespaces/bazi/reindex", headers=AUTH)
        stats = client.get("/knowledge/namespaces/bazi/stats", headers=AUTH)
        deleted = client.delete(
            f"/knowledge/namespaces/bazi/sources/{source['source_id']}",
            headers=AUTH,
        )

        self.assertEqual(reindex.status_code, 200)
        self.assertTrue(reindex.json()["ok"])
        self.assertEqual(stats.status_code, 200)
        self.assertEqual(stats.json()["source_count"], 1)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json()["deleted_source_id"], source["source_id"])

    def test_diagnostics_reports_operator_and_knowledge_state_without_secrets_or_paths(self) -> None:
        configured_app = self._app()
        missing_app = self._app(configured=False)
        request = Mock(base_url="http://127.0.0.1:8000/")

        configured = serialize_runtime_diagnostics(configured_app.state.runtime, request)["knowledge"]
        missing = serialize_runtime_diagnostics(missing_app.state.runtime, request)["knowledge"]

        self.assertEqual(configured["operator_api"], {"configured": True, "reason": None})
        self.assertEqual(missing["operator_api"], {"configured": False, "reason": "credential_missing"})
        self.assertIn("sqlite_vec", configured)
        self.assertIn("embedding_config_hash", configured)
        self.assertNotIn(TOKEN, str(configured))
        self.assertNotIn(str(configured_app.state.runtime.repo_root), str(configured))


if __name__ == "__main__":
    unittest.main()
