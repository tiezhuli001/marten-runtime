import unittest

from marten_runtime.runtime.llm_client import LLMRequest, OpenAIChatLLMClient, ToolExchange
from marten_runtime.runtime.token_estimator import (
    classify_serialized_payload_chars,
    estimate_payload_tokens,
    serialize_payload_stably,
)
from marten_runtime.tools.registry import ToolSnapshot


class UsageEstimatorTests(unittest.TestCase):
    def test_preflight_estimate_counts_tool_schema_and_history(self) -> None:
        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-4.1",
            profile_name="default",
            transport=lambda url, headers, body: {"choices": [{"message": {"content": "ok"}}]},
        )
        request_without_tools = LLMRequest(
            session_id="sess_estimator_plain",
            trace_id="trace_estimator_plain",
            message="继续执行",
            agent_id="main",
            app_id="main_agent",
            tokenizer_family="openai_o200k",
        )
        request_with_tools = request_without_tools.model_copy(
            update={
                "available_tools": ["time", "runtime"],
                "tool_snapshot": ToolSnapshot(
                    tool_snapshot_id="tool_estimator",
                    builtin_tools=["time", "runtime"],
                ),
            }
        )

        payload_without_tools = client._build_payload(request_without_tools)
        payload_with_tools = client._build_payload(request_with_tools)

        plain = estimate_payload_tokens(payload_without_tools, tokenizer_family="openai_o200k")
        with_tools = estimate_payload_tokens(payload_with_tools, tokenizer_family="openai_o200k")

        self.assertGreater(with_tools.input_tokens_estimate, plain.input_tokens_estimate)
        self.assertEqual(with_tools.estimator_kind, "tokenizer")

    def test_preflight_estimate_grows_for_tool_followup_payload(self) -> None:
        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-4.1",
            profile_name="default",
            transport=lambda url, headers, body: {"choices": [{"message": {"content": "ok"}}]},
        )
        first_turn = LLMRequest(
            session_id="sess_estimator_followup",
            trace_id="trace_estimator_followup",
            message="当前上下文状态怎么样",
            agent_id="main",
            app_id="main_agent",
            available_tools=["runtime"],
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_runtime", builtin_tools=["runtime"]),
            tokenizer_family="openai_o200k",
        )
        followup_turn = first_turn.model_copy(
            update={
                "tool_history": [
                    ToolExchange(
                        tool_name="runtime",
                        tool_payload={"action": "context_status"},
                        tool_result={"ok": True, "summary": "状态稳定"},
                    )
                ],
                "tool_result": {"ok": True, "summary": "状态稳定"},
                "requested_tool_name": "runtime",
                "requested_tool_payload": {"action": "context_status"},
            }
        )

        first_payload = client._build_payload(first_turn)
        followup_payload = client._build_payload(followup_turn)

        first_estimate = estimate_payload_tokens(first_payload, tokenizer_family="openai_o200k")
        followup_estimate = estimate_payload_tokens(followup_payload, tokenizer_family="openai_o200k")

        self.assertGreater(followup_estimate.input_tokens_estimate, first_estimate.input_tokens_estimate)

    def test_estimator_falls_back_to_rough_when_tokenizer_family_unknown(self) -> None:
        estimate = estimate_payload_tokens({"model": "x", "messages": [{"role": "user", "content": "你好 world"}]}, tokenizer_family="unknown")

        self.assertEqual(estimate.estimator_kind, "rough")
        self.assertTrue(estimate.degraded)
        self.assertGreater(estimate.input_tokens_estimate, 0)

    def test_rough_estimator_applies_script_aware_payload_formula(self) -> None:
        payload = {"text": "abc中文!", "items": [1]}

        estimate = estimate_payload_tokens(payload, tokenizer_family="rough")
        serialized = serialize_payload_stably(payload)
        buckets = classify_serialized_payload_chars(serialized)
        expected = -(
            -(
                buckets["ascii_text_chars"] / 4.0
                + buckets["cjk_chars"] / 1.2
                + buckets["other_non_ascii_chars"] / 2.0
                + buckets["json_structure_chars"] / 2.0
                + buckets["whitespace_chars"] / 6.0
            )
            // 1
        )

        self.assertEqual(estimate.input_tokens_estimate, int(expected))

    def test_rough_estimator_uses_stable_payload_serialization(self) -> None:
        left = {"b": 2, "a": "中"}
        right = {"a": "中", "b": 2}

        self.assertEqual(serialize_payload_stably(left), serialize_payload_stably(right))
        self.assertEqual(
            estimate_payload_tokens(left, tokenizer_family="rough").input_tokens_estimate,
            estimate_payload_tokens(right, tokenizer_family="rough").input_tokens_estimate,
        )

    def test_rough_estimator_bucket_classification_matches_unicode_ranges(self) -> None:
        buckets = classify_serialized_payload_chars("A中あア한🙂{}[]:,\" \n\t")

        self.assertEqual(buckets["ascii_text_chars"], 1)
        self.assertEqual(buckets["cjk_chars"], 4)
        self.assertEqual(buckets["other_non_ascii_chars"], 1)
        self.assertEqual(buckets["json_structure_chars"], 7)
        self.assertEqual(buckets["whitespace_chars"], 3)


    def test_bucket_classification_detects_escaped_unicode_sequences(self) -> None:
        buckets = classify_serialized_payload_chars(r'prefix\u6570\u636e-suffix')

        self.assertEqual(buckets["escaped_unicode_sequences"], 2)
        self.assertEqual(buckets["ascii_text_chars"], len('prefix-suffix'))

    def test_preflight_estimate_boosts_escaped_unicode_tool_payloads(self) -> None:
        client = OpenAIChatLLMClient(
            api_key="secret",
            model="gpt-4.1",
            profile_name="default",
            transport=lambda url, headers, body: {"choices": [{"message": {"content": "ok"}}]},
        )
        followup_turn = LLMRequest(
            session_id="sess_estimator_escaped_tool",
            trace_id="trace_estimator_escaped_tool",
            message="拿到结果后只回复 mcp-ok。",
            agent_id="main",
            app_id="main_agent",
            tokenizer_family="openai_o200k",
            available_tools=["mcp"],
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_estimator_escaped", builtin_tools=["mcp"]),
            tool_history=[
                ToolExchange(
                    tool_name="mcp",
                    tool_payload={"action": "call"},
                    tool_result={"result_text": "HEAVY-MCP:" + ("数据块-" * 1200), "ok": True},
                )
            ],
            tool_result={"result_text": "HEAVY-MCP:" + ("数据块-" * 1200), "ok": True},
            requested_tool_name="mcp",
            requested_tool_payload={"action": "call"},
        )

        payload = client._build_payload(followup_turn)
        estimate = estimate_payload_tokens(payload, tokenizer_family="openai_o200k")
        serialized = serialize_payload_stably(payload)
        buckets = classify_serialized_payload_chars(serialized)

        self.assertGreater(buckets["escaped_unicode_sequences"], 3000)
        self.assertGreater(estimate.input_tokens_estimate, 10000)


if __name__ == "__main__":
    unittest.main()
