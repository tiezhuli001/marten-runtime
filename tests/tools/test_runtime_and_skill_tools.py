import os
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest import mock

from marten_runtime.runtime.history import CompactionDiagnostics, InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMReply, LLMRequest, ScriptedLLMClient
from marten_runtime.runtime.loop import RuntimeLoop
from marten_runtime.runtime.usage_models import NormalizedUsage
from marten_runtime.session.compaction_trigger import CompactionSettings
from marten_runtime.tools.builtins.runtime_tool import (
    render_runtime_context_status_text,
    run_runtime_tool,
)
from marten_runtime.tools.builtins.time_tool import (
    _detect_local_timezone_label,
    run_time_tool,
    render_time_tool_text,
)
from marten_runtime.tools.registry import ToolRegistry


class RuntimeAndSkillToolTests(unittest.TestCase):
    def _build_scripted_runtime_loop(
        self,
        replies: list[LLMReply] | None = None,
    ):
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(ScriptedLLMClient(list(replies or [])), ToolRegistry(), history)
        return runtime, history

    def _fixed_time_result(
        self,
        payload: dict[str, str],
        *,
        detected_timezone: str | None = None,
    ) -> dict:
        fixed_now = datetime(2026, 4, 1, 5, 47, 22, tzinfo=timezone.utc)
        if detected_timezone is None:
            with mock.patch(
                "marten_runtime.tools.builtins.time_tool.datetime"
            ) as mocked_datetime:
                mocked_datetime.now.return_value = fixed_now
                return run_time_tool(payload)

        with (
            mock.patch("marten_runtime.tools.builtins.time_tool.datetime") as mocked_datetime,
            mock.patch(
                "marten_runtime.tools.builtins.time_tool._detect_local_timezone_label",
                return_value=detected_timezone,
            ),
        ):
            mocked_datetime.now.return_value = fixed_now
            return run_time_tool(payload)

    def test_render_time_tool_text_formats_human_readable_time(self) -> None:
        text = render_time_tool_text(
            {
                "timezone": "Asia/Shanghai",
                "iso_time": "2026-04-08T10:29:00+08:00",
            }
        )

        self.assertEqual(text, "现在是北京时间 2026年4月8日 10:29")

    def test_runtime_tool_returns_compact_user_readable_context_status(self) -> None:
        runtime, history = self._build_scripted_runtime_loop()
        run = history.start(
            session_id="sess_runtime",
            trace_id="trace_runtime",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        history.set_compaction(
            run.run_id,
            CompactionDiagnostics(
                decision="proactive",
                advisory_threshold_tokens=300,
                proactive_threshold_tokens=500,
                used_compacted_context=True,
                compacted_context_id="compact_1",
            ),
        )
        result = run_runtime_tool(
            {"action": "context_status"},
            tool_context={
                "run_id": run.run_id,
                "model_profile": "minimax_m25",
                "current_request": LLMRequest(
                    session_id="sess_runtime",
                    trace_id="trace_runtime",
                    message="请告诉我当前上下文情况",
                    agent_id="main",
                    app_id="main_agent",
                    system_prompt="system",
                    working_context_text="working context",
                ),
                "compact_settings": CompactionSettings(
                    context_window_tokens=1000,
                    reserve_output_tokens=100,
                    compact_trigger_ratio=0.8,
                ),
            },
            runtime_loop=runtime,
            run_history=history,
            latest_checkpoint_available=True,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "context_status")
        self.assertEqual(result["model_profile"], "minimax_m25")
        self.assertEqual(result["context_window"], 1000)
        self.assertEqual(result["effective_window"], 900)
        self.assertEqual(result["latest_checkpoint"], "available")
        self.assertEqual(result["compaction_status"], "proactive-used")
        self.assertIn("tokens", result["summary"])
        self.assertNotIn("compacted_context_id", result)

    def test_runtime_tool_prefers_actual_usage_and_reports_estimate_source(
        self,
    ) -> None:
        runtime, history = self._build_scripted_runtime_loop()
        run = history.start(
            session_id="sess_runtime_usage",
            trace_id="trace_runtime_usage",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )

        result = run_runtime_tool(
            {"action": "context_status"},
            tool_context={
                "run_id": run.run_id,
                "model_profile": "minimax_m25",
                "current_request": LLMRequest(
                    session_id="sess_runtime_usage",
                    trace_id="trace_runtime_usage",
                    message="现在上下文用了多少",
                    agent_id="main",
                    app_id="main_agent",
                    system_prompt="system",
                    working_context_text="working context",
                ),
                "compact_settings": CompactionSettings(
                    context_window_tokens=1000,
                    reserve_output_tokens=100,
                    compact_trigger_ratio=0.8,
                ),
                "latest_actual_usage": {
                    "input_tokens": 321,
                    "output_tokens": 45,
                    "total_tokens": 366,
                    "provider_name": "openai",
                    "model_name": "gpt-4.1",
                    "captured_at": "2026-04-07T12:00:00+00:00",
                },
            },
            runtime_loop=runtime,
            run_history=history,
            latest_checkpoint_available=False,
        )

        self.assertEqual(result["effective_window"], 900)
        self.assertEqual(result["estimate_source"], "rough")
        self.assertIn("next_request_estimate", result)
        self.assertEqual(
            result["next_request_estimate"]["input_tokens_estimate"],
            result["estimated_usage"],
        )
        self.assertEqual(result["next_request_estimate"]["estimator_kind"], "rough")
        self.assertEqual(
            result["current_run"]["initial_input_tokens_estimate"],
            result["estimated_usage"],
        )
        self.assertEqual(
            result["current_run"]["peak_input_tokens_estimate"],
            result["estimated_usage"],
        )
        self.assertEqual(result["last_actual_usage"]["total_tokens"], 366)
        self.assertEqual(result["last_actual_usage"]["input_tokens"], 321)

    def test_runtime_tool_marks_rough_estimate_as_degraded_confidence(self) -> None:
        result = run_runtime_tool(
            {"action": "context_status"},
            tool_context={
                "current_request": LLMRequest(
                    session_id="sess_runtime_rough",
                    trace_id="trace_runtime_rough",
                    message="上下文状态怎么样",
                    agent_id="main",
                    app_id="main_agent",
                    system_prompt="system",
                    working_context_text="仅粗估",
                ),
                "compact_settings": CompactionSettings(
                    context_window_tokens=1000,
                    reserve_output_tokens=100,
                    compact_trigger_ratio=0.8,
                ),
            },
            runtime_loop=None,
            run_history=None,
            latest_checkpoint_available=False,
        )

        self.assertEqual(result["estimate_source"], "rough")
        self.assertTrue(result["next_request_estimate"]["degraded"])
        self.assertIn("rough", result["summary"].lower())

    def test_runtime_tool_explicitly_says_actual_peak_is_unavailable_when_no_model_call_happened(
        self,
    ) -> None:
        runtime, history = self._build_scripted_runtime_loop()
        run = history.start(
            session_id="sess_runtime_no_model_call",
            trace_id="trace_runtime_no_model_call",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        history.set_preflight_usage(
            run.run_id,
            input_tokens_estimate=3838,
            estimator_kind="tokenizer",
            peak_input_tokens_estimate=3838,
            peak_stage="initial_request",
        )

        result = run_runtime_tool(
            {"action": "context_status"},
            tool_context={
                "run_id": run.run_id,
                "session_id": run.session_id,
                "current_request": LLMRequest(
                    session_id=run.session_id,
                    trace_id=run.trace_id,
                    message="现在上下文窗口用多少了？",
                    agent_id="main",
                    app_id="main_agent",
                ),
            },
            runtime_loop=runtime,
            run_history=history,
            latest_checkpoint_available=False,
        )

        text = render_runtime_context_status_text(result)
        self.assertIn("当前上下文使用详情", text)
        self.assertIn("切换会话后会按目标会话重新计算", text)
        self.assertIn("压缩状态：稳定", text)

    def test_runtime_tool_uses_previous_run_actual_peak_for_direct_runtime_query(
        self,
    ) -> None:
        runtime, history = self._build_scripted_runtime_loop()
        previous_run = history.start(
            session_id="sess_runtime_prev_peak",
            trace_id="trace_runtime_prev_peak_prev",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        history.set_actual_usage(
            previous_run.run_id,
            NormalizedUsage(input_tokens=3845, output_tokens=417, total_tokens=4262),
            stage="llm_second",
        )
        history.finish(previous_run.run_id, delivery_status="final")

        current_run = history.start(
            session_id="sess_runtime_prev_peak",
            trace_id="trace_runtime_prev_peak_current",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        history.set_preflight_usage(
            current_run.run_id,
            input_tokens_estimate=4210,
            estimator_kind="tokenizer",
            peak_input_tokens_estimate=4210,
            peak_stage="initial_request",
        )

        result = run_runtime_tool(
            {"action": "context_status"},
            tool_context={
                "run_id": current_run.run_id,
                "session_id": current_run.session_id,
                "current_request": LLMRequest(
                    session_id=current_run.session_id,
                    trace_id=current_run.trace_id,
                    message="当前的上下文窗口是否需要压缩？",
                    agent_id="main",
                    app_id="main_agent",
                ),
            },
            runtime_loop=runtime,
            run_history=history,
            latest_checkpoint_available=False,
        )

        self.assertEqual(result["last_actual_usage"]["total_tokens"], 4262)
        self.assertEqual(result["last_completed_run"]["actual_peak_total_tokens"], 4262)
        self.assertEqual(
            result["last_completed_run"]["actual_peak_stage"], "llm_second"
        )
        text = render_runtime_context_status_text(result)
        self.assertIn("当前上下文使用详情", text)
        self.assertIn("当前会话下一次请求预计带入", text)
        self.assertIn("切换会话后会按目标会话重新计算", text)

    def test_runtime_tool_skips_intermediate_no_llm_runs_when_finding_last_actual_peak(
        self,
    ) -> None:
        runtime, history = self._build_scripted_runtime_loop()

        mcp_run = history.start(
            session_id="sess_runtime_last_non_null",
            trace_id="trace_runtime_last_non_null_mcp",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        history.set_actual_usage(
            mcp_run.run_id,
            NormalizedUsage(input_tokens=3530, output_tokens=509, total_tokens=4039),
            stage="llm_second",
        )
        history.finish(mcp_run.run_id, delivery_status="final")

        runtime_run = history.start(
            session_id="sess_runtime_last_non_null",
            trace_id="trace_runtime_last_non_null_runtime",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        history.set_preflight_usage(
            runtime_run.run_id,
            input_tokens_estimate=3973,
            estimator_kind="tokenizer",
            peak_input_tokens_estimate=3973,
            peak_stage="initial_request",
        )
        history.finish(runtime_run.run_id, delivery_status="final")

        current_run = history.start(
            session_id="sess_runtime_last_non_null",
            trace_id="trace_runtime_last_non_null_current",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        history.set_preflight_usage(
            current_run.run_id,
            input_tokens_estimate=4120,
            estimator_kind="tokenizer",
            peak_input_tokens_estimate=4120,
            peak_stage="initial_request",
        )

        result = run_runtime_tool(
            {"action": "context_status"},
            tool_context={
                "run_id": current_run.run_id,
                "session_id": current_run.session_id,
                "current_request": LLMRequest(
                    session_id=current_run.session_id,
                    trace_id=current_run.trace_id,
                    message="当前的上下文窗口是否需要压缩？",
                    agent_id="main",
                    app_id="main_agent",
                ),
            },
            runtime_loop=runtime,
            run_history=history,
            latest_checkpoint_available=False,
        )

        self.assertEqual(result["last_actual_usage"]["total_tokens"], 4039)
        self.assertEqual(result["last_completed_run"]["actual_peak_total_tokens"], 4039)

    def test_runtime_tool_reports_current_run_peak_estimate_when_followup_is_heavier(
        self,
    ) -> None:
        runtime, history = self._build_scripted_runtime_loop()
        run = history.start(
            session_id="sess_runtime_peak",
            trace_id="trace_runtime_peak",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        history.set_preflight_usage(
            run.run_id,
            input_tokens_estimate=220,
            estimator_kind="tokenizer",
            peak_input_tokens_estimate=960,
            peak_stage="tool_followup",
        )
        history.set_actual_usage(
            run.run_id,
            NormalizedUsage(input_tokens=910, output_tokens=70, total_tokens=980),
            stage="llm_second",
        )

        result = run_runtime_tool(
            {"action": "context_status"},
            tool_context={
                "run_id": run.run_id,
                "current_request": LLMRequest(
                    session_id="sess_runtime_peak",
                    trace_id="trace_runtime_peak",
                    message="现在上下文用了多少",
                    agent_id="main",
                    app_id="main_agent",
                    tokenizer_family="openai_o200k",
                ),
            },
            runtime_loop=runtime,
            run_history=history,
            latest_checkpoint_available=False,
        )

        self.assertEqual(result["current_run"]["initial_input_tokens_estimate"], 220)
        self.assertEqual(result["current_run"]["peak_input_tokens_estimate"], 960)
        self.assertEqual(result["current_run"]["peak_stage"], "tool_followup")
        self.assertEqual(result["current_run"]["actual_cumulative_input_tokens"], 910)
        self.assertEqual(result["current_run"]["actual_cumulative_output_tokens"], 70)
        self.assertEqual(result["current_run"]["actual_cumulative_total_tokens"], 980)
        self.assertEqual(result["current_run"]["actual_peak_total_tokens"], 980)
        self.assertEqual(result["current_run"]["actual_peak_stage"], "llm_second")

    def test_runtime_tool_summary_calls_out_tool_result_injection_as_peak_source(
        self,
    ) -> None:
        runtime, history = self._build_scripted_runtime_loop()
        run = history.start(
            session_id="sess_runtime_peak_summary",
            trace_id="trace_runtime_peak_summary",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        history.set_preflight_usage(
            run.run_id,
            input_tokens_estimate=220,
            estimator_kind="tokenizer",
            peak_input_tokens_estimate=960,
            peak_stage="tool_followup",
        )
        history.set_actual_usage(
            run.run_id,
            NormalizedUsage(input_tokens=910, output_tokens=70, total_tokens=980),
            stage="llm_second",
        )

        result = run_runtime_tool(
            {"action": "context_status"},
            tool_context={
                "run_id": run.run_id,
                "current_request": LLMRequest(
                    session_id="sess_runtime_peak_summary",
                    trace_id="trace_runtime_peak_summary",
                    message="现在上下文用了多少",
                    agent_id="main",
                    app_id="main_agent",
                ),
            },
            runtime_loop=runtime,
            run_history=history,
            latest_checkpoint_available=False,
        )

        self.assertIn("本轮首发请求约 220 tokens", result["summary"])
        self.assertIn("本轮累计约 980 tokens（输入 910 + 输出 70）", result["summary"])
        self.assertIn("本轮 actual-peak 约 980 tokens", result["summary"])
        self.assertIn(
            "峰值主要来自工具结果注入后的 follow-up 模型调用", result["summary"]
        )

    def test_render_runtime_context_status_text_clarifies_input_output_and_total(
        self,
    ) -> None:
        text = render_runtime_context_status_text(
            {
                "action": "context_status",
                "effective_window": 184000,
                "context_window": 200000,
                "estimate_source": "tokenizer",
                "next_request_estimate": {
                    "input_tokens_estimate": 3673,
                    "estimator_kind": "tokenizer",
                },
                "current_run": {
                    "initial_input_tokens_estimate": 3604,
                    "peak_input_tokens_estimate": 3743,
                    "peak_stage": "tool_followup",
                    "actual_cumulative_input_tokens": 4510,
                    "actual_cumulative_output_tokens": 143,
                    "actual_cumulative_total_tokens": 4653,
                    "actual_peak_input_tokens": 3198,
                    "actual_peak_output_tokens": 82,
                    "actual_peak_total_tokens": 3280,
                    "actual_peak_stage": "llm_second",
                },
                "last_actual_usage": {
                    "input_tokens": 3198,
                    "output_tokens": 82,
                    "total_tokens": 3280,
                },
                "compaction_status": "checkpoint-available",
            }
        )

        self.assertIn("当前上下文使用详情", text)
        self.assertIn("当前会话下一次请求预计带入 3673 tokens（约 2% / 184000）", text)
        self.assertIn("切换会话后会按目标会话重新计算", text)
        self.assertIn("压缩状态：已有可复用压缩检查点", text)

    def test_runtime_tool_summary_does_not_blame_tool_injection_when_peak_matches_initial(
        self,
    ) -> None:
        runtime, history = self._build_scripted_runtime_loop()
        run = history.start(
            session_id="sess_runtime_initial_summary",
            trace_id="trace_runtime_initial_summary",
            config_snapshot_id="cfg_bootstrap",
            bootstrap_manifest_id="boot_default",
        )
        history.set_preflight_usage(
            run.run_id,
            input_tokens_estimate=220,
            estimator_kind="tokenizer",
            peak_input_tokens_estimate=220,
            peak_stage="initial_request",
        )
        history.set_actual_usage(
            run.run_id,
            NormalizedUsage(input_tokens=180, output_tokens=20, total_tokens=200),
            stage="llm_first",
        )

        result = run_runtime_tool(
            {"action": "context_status"},
            tool_context={
                "run_id": run.run_id,
                "current_request": LLMRequest(
                    session_id="sess_runtime_initial_summary",
                    trace_id="trace_runtime_initial_summary",
                    message="现在上下文用了多少",
                    agent_id="main",
                    app_id="main_agent",
                ),
            },
            runtime_loop=runtime,
            run_history=history,
            latest_checkpoint_available=False,
        )

        self.assertIn("本轮首发请求约 220 tokens", result["summary"])
        self.assertIn("本轮 actual-peak 约 200 tokens", result["summary"])
        self.assertNotIn("工具结果注入后", result["summary"])

    def test_registry_lists_and_calls_time_tool(self) -> None:
        registry = ToolRegistry()
        registry.register("time", run_time_tool)

        result = registry.call("time", {"timezone": "UTC"})

        self.assertEqual(registry.list(), ["time"])
        self.assertEqual(result["timezone"], "UTC")
        self.assertIn("iso_time", result)

    def test_time_tool_uses_requested_or_detected_timezone(self) -> None:
        cases = [
            {
                "payload": {"tz": "Asia/Shanghai"},
                "detected_timezone": None,
                "expected_timezone": "Asia/Shanghai",
            },
            {
                "payload": {},
                "detected_timezone": "Asia/Shanghai",
                "expected_timezone": "Asia/Shanghai",
            },
        ]

        for case in cases:
            with self.subTest(payload=case["payload"]):
                result = self._fixed_time_result(
                    case["payload"],
                    detected_timezone=case["detected_timezone"],
                )
                self.assertEqual(result["timezone"], case["expected_timezone"])
                self.assertEqual(result["iso_time"], "2026-04-01T13:47:22+08:00")

    def test_detect_local_timezone_label_prefers_zoneinfo_name(self) -> None:
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch(
                "marten_runtime.tools.builtins.time_tool.Path.exists", return_value=True
            ),
            mock.patch(
                "marten_runtime.tools.builtins.time_tool.Path.is_symlink",
                return_value=True,
            ),
            mock.patch(
                "marten_runtime.tools.builtins.time_tool.Path.resolve",
                return_value=Path(
                    "/private/var/db/timezone/tz/2025c.1.0/zoneinfo/Asia/Shanghai"
                ),
            ),
        ):
            result = _detect_local_timezone_label()

        self.assertEqual(result, "Asia/Shanghai")

    def test_detect_local_timezone_label_falls_back_to_local_offset(self) -> None:
        fixed_local = datetime(
            2026,
            4,
            1,
            13,
            47,
            22,
            tzinfo=timezone(timedelta(hours=8)),
        )

        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch(
                "marten_runtime.tools.builtins.time_tool.Path.exists",
                return_value=False,
            ),
            mock.patch(
                "marten_runtime.tools.builtins.time_tool.datetime"
            ) as mocked_datetime,
        ):
            mocked_datetime.now.return_value = fixed_local

            result = _detect_local_timezone_label()

        self.assertEqual(result, "+08:00")
