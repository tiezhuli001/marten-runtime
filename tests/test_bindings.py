import tempfile
import textwrap
import unittest
from pathlib import Path

from marten_runtime.agents.bindings import AgentBindingRegistry
from marten_runtime.config.bindings_loader import load_agent_bindings
from marten_runtime.gateway.models import InboundEnvelope


def make_envelope(
    *,
    channel_id: str = "feishu",
    conversation_id: str = "chat-1",
    user_id: str = "user-1",
    body: str = "hello @bot",
) -> InboundEnvelope:
    from datetime import datetime, timezone

    return InboundEnvelope(
        channel_id=channel_id,
        user_id=user_id,
        conversation_id=conversation_id,
        message_id="msg-1",
        body=body,
        received_at=datetime.now(timezone.utc),
        dedupe_key="dedupe_1234",
        trace_id="trace_1234",
    )


class BindingTests(unittest.TestCase):
    def test_loader_reads_binding_rules_from_toml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bindings.toml"
            path.write_text(
                textwrap.dedent(
                    """
                    [[bindings]]
                    agent_id = "ops"
                    channel_id = "feishu"
                    conversation_id = "chat-ops"
                    mention_required = true

                    [[bindings]]
                    agent_id = "main"
                    channel_id = "http"
                    default = true
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            rules = load_agent_bindings(str(path))

            self.assertEqual(len(rules), 2)
            self.assertEqual(rules[0].agent_id, "ops")
            self.assertTrue(rules[0].mention_required)
            self.assertTrue(rules[1].default)

    def test_registry_prefers_exact_conversation_binding_over_user_and_channel_default(self) -> None:
        registry = AgentBindingRegistry(
            load_agent_bindings_from_payload(
                [
                    {
                        "agent_id": "support",
                        "channel_id": "feishu",
                        "conversation_id": "chat-1",
                    },
                    {
                        "agent_id": "ops",
                        "channel_id": "feishu",
                        "user_id": "user-1",
                    },
                    {
                        "agent_id": "main",
                        "channel_id": "feishu",
                        "default": True,
                    },
                ]
            )
        )

        matched = registry.match(make_envelope())

        self.assertIsNotNone(matched)
        self.assertEqual(matched.agent_id, "support")

    def test_registry_matches_user_binding_when_conversation_binding_missing(self) -> None:
        registry = AgentBindingRegistry(
            load_agent_bindings_from_payload(
                [
                    {
                        "agent_id": "ops",
                        "channel_id": "feishu",
                        "user_id": "user-1",
                    },
                    {
                        "agent_id": "main",
                        "channel_id": "feishu",
                        "default": True,
                    },
                ]
            )
        )

        matched = registry.match(make_envelope(conversation_id="chat-2"))

        self.assertIsNotNone(matched)
        self.assertEqual(matched.agent_id, "ops")

    def test_registry_ignores_mention_required_binding_when_message_has_no_mention(self) -> None:
        registry = AgentBindingRegistry(
            load_agent_bindings_from_payload(
                [
                    {
                        "agent_id": "ops",
                        "channel_id": "feishu",
                        "conversation_id": "chat-1",
                        "mention_required": True,
                    },
                    {
                        "agent_id": "main",
                        "channel_id": "feishu",
                        "default": True,
                    },
                ]
            )
        )

        matched = registry.match(make_envelope(body="hello there"))

        self.assertIsNotNone(matched)
        self.assertEqual(matched.agent_id, "main")

    def test_registry_returns_channel_default_when_no_exact_rule_matches(self) -> None:
        registry = AgentBindingRegistry(
            load_agent_bindings_from_payload(
                [{"agent_id": "main", "channel_id": "feishu", "default": True}]
            )
        )

        matched = registry.match(make_envelope(conversation_id="chat-9", user_id="user-9"))

        self.assertIsNotNone(matched)
        self.assertEqual(matched.agent_id, "main")


def load_agent_bindings_from_payload(items: list[dict[str, object]]):
    from marten_runtime.agents.bindings import AgentBinding

    return [AgentBinding(**item) for item in items]


if __name__ == "__main__":
    unittest.main()
