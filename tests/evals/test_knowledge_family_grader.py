import unittest

from marten_runtime.evals.family_graders.knowledge_retrieval import grade_knowledge_retrieval_case_result
from marten_runtime.evals.grader_registry import resolve_case_grader
from marten_runtime.evals.models import EvalCaseObservation, EvalCaseSpec, EvalTurnSpec


class KnowledgeFamilyGraderTests(unittest.TestCase):
    def test_registry_resolves_knowledge_retrieval_grader(self) -> None:
        case = _case("keyword_recall", {"keyword_recall": 100}, {"required_chunks": ["k1"]})

        self.assertEqual(resolve_case_grader(case).__name__, "grade_knowledge_retrieval_case_result")

    def test_grade_passes_keyword_recall_and_namespace_isolation(self) -> None:
        case = _case(
            "keyword_recall",
            {"keyword_recall": 50, "namespace_isolation": 50},
            {"required_chunks": ["k1"], "namespace": "fanqie"},
        )
        observation = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            final_text="引用 k1",
            tool_calls=[
                {"tool_name": "knowledge", "tool_payload": {"action": "search", "namespace": "fanqie"}, "tool_result": {"ok": True, "results": [{"chunk_id": "k1", "source_id": "s1"}]}}
            ],
        )

        result = grade_knowledge_retrieval_case_result(case, observation, "eval_1")

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.total_score, 100.0)

    def test_grade_detects_config_mismatch_reindex_hint(self) -> None:
        case = _case(
            "config_mismatch",
            {"config_mismatch": 100},
            {"expected_vector_status": "config_mismatch", "required_diagnostic_contains": ["knowledge.reindex --namespace fanqie"]},
        )
        observation = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            tool_calls=[
                {"tool_name": "knowledge", "tool_payload": {"action": "search", "namespace": "fanqie"}, "tool_result": {"ok": True, "vector_status": "config_mismatch", "degraded_reason": "Run knowledge.reindex --namespace fanqie"}}
            ],
        )

        result = grade_knowledge_retrieval_case_result(case, observation, "eval_1")

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.total_score, 100.0)

    def test_large_file_progress_requires_status_polling_and_completion(self) -> None:
        case = _case("large_file_progress", {"large_file_progress": 100}, {})
        observation = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            tool_calls=[
                {"tool_name": "knowledge", "tool_payload": {"action": "ingest_file", "namespace": "fanqie"}, "tool_result": {"ok": True, "action": "ingest_file", "job_id": "kjob_1", "status": "queued"}},
                {"tool_name": "knowledge", "tool_payload": {"action": "ingest_status", "namespace": "fanqie", "job_id": "kjob_1"}, "tool_result": {"ok": True, "status": "embedding", "chunks_total": 10, "chunks_embedded": 5, "percent": 50.0}},
                {"tool_name": "knowledge", "tool_payload": {"action": "ingest_status", "namespace": "fanqie", "job_id": "kjob_1"}, "tool_result": {"ok": True, "status": "completed", "chunks_total": 10, "chunks_embedded": 10, "percent": 100.0}},
            ],
        )

        result = grade_knowledge_retrieval_case_result(case, observation, "eval_1")

        self.assertEqual(result.status, "passed")
        self.assertEqual(result.total_score, 100.0)

    def test_large_file_progress_fails_when_only_start_response_exists(self) -> None:
        case = _case("large_file_progress", {"large_file_progress": 100}, {})
        observation = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            tool_calls=[
                {"tool_name": "knowledge", "tool_payload": {"action": "ingest_file", "namespace": "fanqie"}, "tool_result": {"ok": True, "action": "ingest_file", "job_id": "kjob_1", "status": "queued"}},
            ],
        )

        result = grade_knowledge_retrieval_case_result(case, observation, "eval_1")

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.total_score, 0.0)


def _case(case_id: str, weights: dict[str, int], grader_case: dict[str, object]) -> EvalCaseSpec:
    return EvalCaseSpec(
        case_id=case_id,
        suite_id="knowledge_retrieval",
        family="knowledge_retrieval",
        grader_id="knowledge_retrieval",
        description="knowledge eval",
        agent_id="main",
        profile_name="openai_gpt_5_4",
        turns=[EvalTurnSpec(role="user", content="搜索知识库")],
        component_weights=weights,
        gate_components=list(weights.keys()),
        grader_case=grader_case,
    )


if __name__ == "__main__":
    unittest.main()
