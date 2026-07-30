from __future__ import annotations

import json
import unittest
from pathlib import Path

from marten_runtime.bazi_cases.service import owner_key_from_context
from marten_runtime.evals.bazi_case_library import evaluate_private_case_retrieval
from tests.bazi_case_support import build_case_service


class BaziCaseRetrievalEvalTests(unittest.TestCase):
    def test_mock_cases_improve_verified_event_recall_without_fact_conflicts(self) -> None:
        service, tmp = build_case_service()
        self.addCleanup(tmp.cleanup)
        owner = owner_key_from_context({"channel_id": "eval", "user_id": "fixture-user"})
        fixtures = json.loads(
            (Path(__file__).parents[2] / "evals" / "cases" / "bazi_case_library" / "private_cases_v1.json").read_text(encoding="utf-8")
        )
        report = evaluate_private_case_retrieval(service, owner_key=owner, cases=fixtures)
        metrics = report["metrics"]
        self.assertGreaterEqual(report["fixture_count"], 30)
        self.assertEqual(metrics["exact_recall_at_1"], 1.0)
        self.assertGreaterEqual(metrics["near_recall_at_3"], 0.85)
        self.assertGreaterEqual(metrics["with_cases_verified_event_recall_at_3"], 0.80)
        self.assertGreaterEqual(metrics["verified_event_recall_lift"], 0.20)
        self.assertEqual(metrics["result_contract_completeness"], 1.0)
        self.assertEqual(metrics["builtin_fact_conflicts"], 0)
        self.assertEqual(metrics["owner_leakage"], 0)
        self.assertEqual(metrics["prediction_as_event"], 0)


if __name__ == "__main__":
    unittest.main()
