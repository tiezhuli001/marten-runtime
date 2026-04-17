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


if __name__ == "__main__":
    unittest.main()
