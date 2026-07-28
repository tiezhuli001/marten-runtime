import concurrent.futures
import asyncio
import time
import unittest
from unittest.mock import Mock

from fastapi.testclient import TestClient

from marten_runtime.knowledge.embeddings import FakeEmbeddingAdapter
from marten_runtime.interfaces.http.knowledge_routes import (
    MAX_UPLOAD_BYTES,
    MAX_UPLOAD_REQUEST_BYTES,
)
from tests.http_app_support import build_test_app


TOKEN = "operator-test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
FORM = {
    "title": "Reviewed theory",
    "license": "MIT",
    "provenance": "fixture",
    "calculation_scope": "four-pillars",
    "review_status": "reviewed",
    "corpus_type": "theory",
    "school": "test-fixture",
    "method": "calendar-fact-boundary",
}


class KnowledgeUploadTests(unittest.TestCase):
    def _app(self):
        app = build_test_app(env_overrides={"KNOWLEDGE_OPERATOR_TOKEN": TOKEN})
        service = app.state.runtime.knowledge_service
        service.embedding_adapter = FakeEmbeddingAdapter(
            dimension=service.config.embedding.dimension,
            model_id=service.config.embedding.model,
        )
        return app

    def _wait(self, service, job_id: str) -> dict[str, object]:  # noqa: ANN001
        result: dict[str, object] = {}
        for _ in range(100):
            result = service.ingest_status(namespace="bazi", job_id=job_id)
            if result.get("status") in {"completed", "failed", "cancelled"}:
                return result
            time.sleep(0.02)
        return result

    def test_upload_accepts_txt_md_and_supported_encodings_with_reviewed_metadata(self) -> None:
        cases = (
            ("theory.txt", "甲木生于春季".encode("utf-8")),
            ("theory.md", "# 乙木\n\n乙木生于春季".encode("utf-8-sig")),
            ("legacy.txt", "丙火生于夏季".encode("gb18030")),
        )
        for filename, content in cases:
            with self.subTest(filename=filename):
                app = self._app()
                client = TestClient(app)
                response = client.post(
                    "/knowledge/namespaces/bazi/uploads",
                    headers=AUTH,
                    data=FORM,
                    files={"file": (filename, content, "application/octet-stream")},
                )
                self.assertEqual(response.status_code, 202, response.text)
                body = response.json()
                self.assertTrue(body["ok"])
                final = self._wait(app.state.runtime.knowledge_service, body["job_id"])
                self.assertEqual(final["status"], "completed")
                source = app.state.runtime.knowledge_service.store.get_source("bazi", body["source_id"])
                self.assertEqual(source.metadata["review_status"], "reviewed")
                self.assertEqual(source.metadata["corpus_type"], "theory")
                self.assertEqual(source.metadata["school"], "test-fixture")
                self.assertEqual(source.metadata["method"], "calendar-fact-boundary")
                self.assertEqual(source.metadata["original_filename"], filename)
                self.assertIn(source.metadata["encoding"], {"utf-8", "utf-8-sig", "gb18030"})

    def test_upload_rejects_missing_metadata_review_state_extension_path_and_binary(self) -> None:
        app = self._app()
        client = TestClient(app)
        cases = (
            ({k: v for k, v in FORM.items() if k != "license"}, "theory.txt", b"text", "KNOWLEDGE_UPLOAD_METADATA_INVALID"),
            ({**FORM, "review_status": "draft"}, "theory.txt", b"text", "KNOWLEDGE_UPLOAD_REVIEW_REQUIRED"),
            (FORM, "theory.pdf", b"text", "KNOWLEDGE_UPLOAD_FORMAT_UNSUPPORTED"),
            (FORM, "../theory.txt", b"text", "KNOWLEDGE_UPLOAD_FILENAME_INVALID"),
            (FORM, "theory.txt", b"text\x00binary", "KNOWLEDGE_UPLOAD_ENCODING_INVALID"),
            (FORM, "empty.txt", b"   \n", "KNOWLEDGE_UPLOAD_ENCODING_INVALID"),
        )
        for form, filename, content, code in cases:
            with self.subTest(code=code):
                response = client.post(
                    "/knowledge/namespaces/bazi/uploads",
                    headers=AUTH,
                    data=form,
                    files={"file": (filename, content, "application/octet-stream")},
                )
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["error"]["code"], code)

    def test_upload_authentication_precedes_multipart_validation_and_size_checks(self) -> None:
        app = self._app()
        service = app.state.runtime.knowledge_service
        service.ingest_file = Mock(side_effect=AssertionError("service called"))
        response = TestClient(app).post(
            "/knowledge/namespaces/bazi/uploads",
            headers={"Authorization": "Bearer wrong", "Content-Length": str(MAX_UPLOAD_BYTES + 100_000)},
            content=b"malformed multipart",
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "KNOWLEDGE_OPERATOR_UNAUTHORIZED")
        service.ingest_file.assert_not_called()

    def test_upload_accepts_exact_limit_and_rejects_actual_or_declared_overflow(self) -> None:
        app = self._app()
        service = app.state.runtime.knowledge_service
        original_ingest = service.ingest_file
        service.ingest_file = Mock(
            return_value={
                "ok": True,
                "action": "ingest_file",
                "namespace": "bazi",
                "job_id": "job-size",
                "status": "queued",
            }
        )
        self.addCleanup(setattr, service, "ingest_file", original_ingest)
        client = TestClient(app)

        exact = client.post(
            "/knowledge/namespaces/bazi/uploads",
            headers=AUTH,
            data=FORM,
            files={"file": ("exact.txt", b"a" * MAX_UPLOAD_BYTES, "text/plain")},
        )
        overflow = client.post(
            "/knowledge/namespaces/bazi/uploads",
            headers=AUTH,
            data=FORM,
            files={"file": ("overflow.txt", b"a" * (MAX_UPLOAD_BYTES + 1), "text/plain")},
        )
        declared = client.post(
            "/knowledge/namespaces/bazi/uploads",
            headers={**AUTH, "Content-Length": str(MAX_UPLOAD_BYTES + 100_000)},
            data=FORM,
            files={"file": ("small.txt", b"small", "text/plain")},
        )

        self.assertEqual(exact.status_code, 202, exact.text)
        self.assertEqual(overflow.status_code, 413)
        self.assertEqual(overflow.json()["error"]["code"], "KNOWLEDGE_UPLOAD_TOO_LARGE")
        self.assertEqual(declared.status_code, 413)
        self.assertEqual(declared.json()["error"]["code"], "KNOWLEDGE_UPLOAD_TOO_LARGE")
        upload_root = app.state.runtime.repo_root / "data" / "knowledge" / "uploads"
        self.assertEqual([path for path in upload_root.iterdir() if path.name != exact.json()["upload_id"]], [])

    def test_concurrent_duplicate_uploads_use_one_source_and_distinct_jobs(self) -> None:
        app = self._app()
        content = "甲木生于春季，宜结合月令分析。".encode("utf-8")

        def upload() -> dict[str, object]:
            response = TestClient(app).post(
                "/knowledge/namespaces/bazi/uploads",
                headers=AUTH,
                data=FORM,
                files={"file": ("same.md", content, "text/markdown")},
            )
            self.assertEqual(response.status_code, 202, response.text)
            return response.json()

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: upload(), range(2)))

        self.assertEqual(len({item["source_id"] for item in responses}), 1)
        self.assertEqual(len({item["job_id"] for item in responses}), 2)
        for item in responses:
            self.assertEqual(
                self._wait(app.state.runtime.knowledge_service, str(item["job_id"]))["status"],
                "completed",
            )
        self.assertEqual(app.state.runtime.knowledge_service.stats(namespace="bazi")["source_count"], 1)

    def test_same_explicit_version_without_uri_uses_content_identity(self) -> None:
        app = self._app()
        client = TestClient(app)
        responses = []
        for filename, content in (
            ("first.md", "甲木生于春季。".encode()),
            ("second.md", "丙火生于夏季。".encode()),
        ):
            response = client.post(
                "/knowledge/namespaces/bazi/uploads",
                headers=AUTH,
                data={**FORM, "version": "v1"},
                files={"file": (filename, content, "text/markdown")},
            )
            self.assertEqual(response.status_code, 202, response.text)
            responses.append(response.json())

        self.assertEqual(len({item["source_id"] for item in responses}), 2)
        for item in responses:
            self.assertEqual(
                self._wait(app.state.runtime.knowledge_service, item["job_id"])["status"],
                "completed",
            )
        self.assertEqual(
            app.state.runtime.knowledge_service.stats(namespace="bazi")["source_count"],
            2,
        )

    def test_chunked_multipart_limit_stops_consuming_request_body(self) -> None:
        app = self._app()
        chunk_size = 256 * 1024
        prefix = (
            b"--test-boundary\r\n"
            b'Content-Disposition: form-data; name="file"; filename="large.txt"\r\n'
            b"Content-Type: text/plain\r\n\r\n"
        )
        suffix = b"\r\n--test-boundary--\r\n"
        body = prefix + (b"x" * (MAX_UPLOAD_REQUEST_BYTES + (4 * chunk_size))) + suffix
        body_size = len(body)
        consumed = 0
        sent: list[dict[str, object]] = []

        async def receive() -> dict[str, object]:
            nonlocal consumed
            remaining = body_size - consumed
            size = min(chunk_size, remaining)
            start = consumed
            consumed += size
            return {
                "type": "http.request",
                "body": body[start:consumed],
                "more_body": consumed < body_size,
            }

        async def send(message: dict[str, object]) -> None:
            sent.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/knowledge/namespaces/bazi/uploads",
            "raw_path": b"/knowledge/namespaces/bazi/uploads",
            "query_string": b"",
            "headers": [
                (b"authorization", f"Bearer {TOKEN}".encode()),
                (b"content-type", b"multipart/form-data; boundary=test-boundary"),
            ],
            "client": ("127.0.0.1", 1234),
            "server": ("testserver", 80),
        }

        asyncio.run(app(scope, receive, send))

        start = next(message for message in sent if message["type"] == "http.response.start")
        self.assertEqual(start["status"], 413)
        self.assertLess(consumed, body_size)
        self.assertLessEqual(consumed, MAX_UPLOAD_REQUEST_BYTES + chunk_size)


if __name__ == "__main__":
    unittest.main()
