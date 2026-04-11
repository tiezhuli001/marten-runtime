import unittest
from datetime import datetime, timezone

from marten_runtime.interfaces.http.channel_event_serialization import (
    history_visible_text,
    serialize_event_for_channel,
)
from marten_runtime.runtime.events import OutboundEvent
from marten_runtime.runtime.history import InMemoryRunHistory


class HTTPEventSerializationTests(unittest.TestCase):
    def test_history_visible_text_strips_feishu_protocol_tail(self) -> None:
        text = (
            "处理完成\n\n```feishu_card\n"
            '{"header":{"title":"完成"},"elements":[{"tag":"markdown","content":"hello"}]}\n'
            "```"
        )

        self.assertEqual(history_visible_text(text), "处理完成")

    def test_serialize_event_for_channel_renders_feishu_card_and_visible_text(self) -> None:
        history = InMemoryRunHistory()
        run = history.start(
            session_id="sess_test",
            trace_id="trace_test",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        history.finish(run.run_id, delivery_status="final")
        event = OutboundEvent(
            session_id="sess_test",
            run_id=run.run_id,
            event_id="evt_test",
            event_type="final",
            sequence=2,
            trace_id="trace_test",
            payload={
                "text": (
                    "处理完成\n\n```feishu_card\n"
                    '{"header":{"title":"完成"},"elements":[{"tag":"markdown","content":"hello"}]}\n'
                    "```"
                )
            },
            created_at=datetime.now(timezone.utc),
        )

        item = serialize_event_for_channel(
            event,
            channel_id="feishu",
            run_history=history,
        )

        self.assertEqual(item["payload"]["text"], "处理完成")
        self.assertIn("card", item["payload"])
        self.assertIn("header", item["payload"]["card"])


if __name__ == "__main__":
    unittest.main()
