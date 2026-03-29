import unittest

from fastapi.testclient import TestClient

from tests.http_app_support import build_test_app


class HealthHttpTests(unittest.TestCase):
    def test_healthz(self) -> None:
        with TestClient(build_test_app()) as client:
            response = client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_readyz(self) -> None:
        with TestClient(build_test_app()) as client:
            response = client.get("/readyz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready"})


if __name__ == "__main__":
    unittest.main()
