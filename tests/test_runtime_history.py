import unittest

from marten_runtime.runtime.history import InMemoryRunHistory


class RuntimeHistoryLangfuseRefTests(unittest.TestCase):
    def test_run_record_serializes_langfuse_refs_when_present(self) -> None:
        history = InMemoryRunHistory()
        record = history.start(
            session_id="sess_1",
            trace_id="trace_1",
            config_snapshot_id="cfg_1",
            bootstrap_manifest_id="boot_1",
        )

        history.set_external_observability_refs(
            record.run_id,
            langfuse_trace_id="lf-trace-1",
            langfuse_url="https://langfuse.example/trace/lf-trace-1",
        )

        dumped = history.get(record.run_id).model_dump(mode="json")

        self.assertEqual(
            dumped["external_observability"]["langfuse_trace_id"], "lf-trace-1"
        )
        self.assertEqual(
            dumped["external_observability"]["langfuse_url"],
            "https://langfuse.example/trace/lf-trace-1",
        )

    def test_run_record_keeps_empty_shape_when_langfuse_refs_are_missing(self) -> None:
        history = InMemoryRunHistory()
        record = history.start(
            session_id="sess_1",
            trace_id="trace_1",
            config_snapshot_id="cfg_1",
            bootstrap_manifest_id="boot_1",
        )

        dumped = history.get(record.run_id).model_dump(mode="json")

        self.assertEqual(
            dumped["external_observability"],
            {"langfuse_trace_id": None, "langfuse_url": None},
        )

    def test_run_record_records_finalization_assessment_for_accepted_run(self) -> None:
        history = InMemoryRunHistory()
        record = history.start(
            session_id="sess_finalization_accepted",
            trace_id="trace_finalization_accepted",
            config_snapshot_id="cfg_1",
            bootstrap_manifest_id="boot_1",
        )

        history.set_finalization_state(
            record.run_id,
            assessment="accepted",
            request_kind="interactive",
            required_evidence_count=3,
        )

        dumped = history.get(record.run_id).model_dump(mode="json")

        self.assertEqual(dumped["finalization"]["assessment"], "accepted")
        self.assertEqual(dumped["finalization"]["request_kind"], "interactive")
        self.assertEqual(dumped["finalization"]["required_evidence_count"], 3)
        self.assertEqual(dumped["finalization"]["missing_evidence_items"], [])
        self.assertFalse(dumped["finalization"]["retry_triggered"])

    def test_run_record_records_missing_evidence_and_retry_trigger_for_degraded_run(self) -> None:
        history = InMemoryRunHistory()
        record = history.start(
            session_id="sess_finalization_retry",
            trace_id="trace_finalization_retry",
            config_snapshot_id="cfg_1",
            bootstrap_manifest_id="boot_1",
        )

        history.set_finalization_state(
            record.run_id,
            assessment="retryable_degraded",
            request_kind="finalization_retry",
            required_evidence_count=4,
            missing_evidence_items=[
                "当前上下文使用详情：预计占用 1234/184000 tokens。",
                "本次请求共发生 4 次模型请求和 3 次工具调用，属于多次模型/工具往返。",
            ],
            retry_triggered=True,
            invalid_final_text="x" * 500,
        )

        dumped = history.get(record.run_id).model_dump(mode="json")

        self.assertEqual(dumped["finalization"]["assessment"], "retryable_degraded")
        self.assertEqual(dumped["finalization"]["request_kind"], "finalization_retry")
        self.assertEqual(dumped["finalization"]["required_evidence_count"], 4)
        self.assertEqual(len(dumped["finalization"]["missing_evidence_items"]), 2)
        self.assertTrue(dumped["finalization"]["retry_triggered"])
        self.assertLessEqual(len(dumped["finalization"]["invalid_final_text"]), 280)

    def test_run_record_records_fragment_recovery_state(self) -> None:
        history = InMemoryRunHistory()
        record = history.start(
            session_id="sess_finalization_recovered",
            trace_id="trace_finalization_recovered",
            config_snapshot_id="cfg_1",
            bootstrap_manifest_id="boot_1",
        )

        history.set_finalization_state(
            record.run_id,
            assessment="retryable_degraded",
            request_kind="finalization_retry",
            required_evidence_count=2,
            recovered_from_fragments=True,
        )

        dumped = history.get(record.run_id).model_dump(mode="json")

        self.assertTrue(dumped["finalization"]["recovered_from_fragments"])


if __name__ == "__main__":
    unittest.main()
