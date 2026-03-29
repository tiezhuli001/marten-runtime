import unittest

from marten_runtime.runtime.streaming import make_event


class StreamingTests(unittest.TestCase):
    def test_make_event_keeps_allowed_streaming_shape(self) -> None:
        event = make_event(
            session_id="sess_1",
            run_id="run_1",
            sequence=1,
            event_type="progress",
            payload={"text": "running"},
            trace_id="trace_stream",
        )

        self.assertEqual(event.event_type, "progress")
        self.assertEqual(event.trace_id, "trace_stream")
        self.assertEqual(event.payload["text"], "running")


if __name__ == "__main__":
    unittest.main()
