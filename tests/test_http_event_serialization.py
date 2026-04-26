import unittest
from datetime import datetime, timezone

from marten_runtime.channels.output_normalization import (
    TerminalOutputNormalization,
    normalize_terminal_output,
)
from marten_runtime.interfaces.http.channel_event_serialization import (
    history_durable_text,
    history_visible_text,
    serialize_event_for_channel,
)
from marten_runtime.runtime.events import OutboundEvent
from marten_runtime.runtime.history import InMemoryRunHistory


class HTTPEventSerializationTests(unittest.TestCase):
    def test_terminal_output_normalization_contract_supports_distinct_durable_and_visible_text(
        self,
    ) -> None:
        item = TerminalOutputNormalization(
            durable_text="完整持久化文本",
            visible_text="紧凑展示文本",
            channel_payload={"schema": "2.0"},
        )

        self.assertEqual(item.durable_text, "完整持久化文本")
        self.assertEqual(item.visible_text, "紧凑展示文本")
        self.assertEqual(item.channel_payload, {"schema": "2.0"})

    def test_history_visible_text_strips_feishu_protocol_tail(self) -> None:
        text = (
            "处理完成\n\n```feishu_card\n"
            '{"header":{"title":"完成"},"elements":[{"tag":"markdown","content":"hello"}]}\n'
            "```"
        )

        self.assertEqual(history_visible_text(text), "处理完成")

    def test_history_durable_text_preserves_feishu_card_detail(self) -> None:
        text = (
            "处理完成。\n\n```feishu_card\n"
            '{"title":"结果","summary":"共 2 项","sections":[{"items":["builtin 正常","mcp 正常"]}]}\n'
            "```"
        )

        self.assertEqual(
            history_durable_text(text),
            "处理完成。\n\n共 2 项\n\n- builtin 正常\n- mcp 正常",
        )

    def test_normalize_terminal_output_for_feishu_can_split_durable_and_visible_text(
        self,
    ) -> None:
        normalized = normalize_terminal_output(
            raw_text=(
                "处理完成。\n\n```feishu_card\n"
                '{"title":"结果","summary":"共 2 项","sections":[{"title":"详情","items":["builtin 正常","mcp 正常"]}]}\n'
                "```"
            ),
            channel_id="feishu",
            event_type="final",
        )

        self.assertEqual(normalized.visible_text, "处理完成。")
        self.assertEqual(
            normalized.durable_text,
            "处理完成。\n\n共 2 项\n\n详情\n- builtin 正常\n- mcp 正常",
        )

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

    def test_serialize_event_for_channel_uses_precomputed_terminal_output_when_provided(self) -> None:
        event = OutboundEvent(
            session_id="sess_test",
            run_id="run_test",
            event_id="evt_test",
            event_type="final",
            sequence=2,
            trace_id="trace_test",
            payload={"text": "原始协议文本"},
            created_at=datetime.now(timezone.utc),
        )

        item = serialize_event_for_channel(
            event,
            channel_id="feishu",
            run_history=None,
            normalized_terminal_output=TerminalOutputNormalization(
                durable_text="完整处理完成",
                visible_text="处理完成",
                channel_payload={"schema": "2.0", "header": {"title": {"content": "结果"}}},
            ),
        )

        self.assertEqual(item["payload"]["text"], "完整处理完成")
        self.assertEqual(item["payload"]["card"]["schema"], "2.0")
        self.assertEqual(item["payload"]["card"]["header"]["title"]["content"], "结果")


if __name__ == "__main__":
    unittest.main()
