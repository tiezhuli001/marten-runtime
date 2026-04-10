import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from marten_runtime.automation.models import AutomationJob
from marten_runtime.automation.sqlite_store import SQLiteAutomationStore
from marten_runtime.automation.store import AutomationStore
from marten_runtime.data_access.adapter import DomainDataAdapter
from marten_runtime.self_improve.models import (
    FailureEvent,
    LessonCandidate,
    SystemLesson,
)
from marten_runtime.self_improve.sqlite_store import SQLiteSelfImproveStore
from marten_runtime.runtime.history import CompactionDiagnostics, InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMRequest, ScriptedLLMClient
from marten_runtime.runtime.loop import RuntimeLoop
from marten_runtime.runtime.usage_models import NormalizedUsage
from marten_runtime.session.compaction_trigger import CompactionSettings
from marten_runtime.tools.builtins.runtime_tool import (
    render_runtime_context_status_text,
    run_runtime_tool,
)
from marten_runtime.tools.builtins.automation_tool import (
    render_automation_tool_text,
    run_automation_tool,
    run_delete_automation_tool,
    run_get_automation_detail_tool,
    run_list_automations_tool,
    run_pause_automation_tool,
    run_register_automation_tool,
    run_resume_automation_tool,
    run_update_automation_tool,
)
from marten_runtime.tools.builtins.self_improve_tool import (
    run_delete_lesson_candidate_tool,
    run_get_lesson_candidate_detail_tool,
    run_get_self_improve_summary_tool,
    run_list_lesson_candidates_tool,
    run_list_self_improve_evidence_tool,
    run_list_system_lessons_tool,
    run_save_lesson_candidate_tool,
    run_self_improve_tool,
)
from marten_runtime.tools.builtins.time_tool import (
    _detect_local_timezone_label,
    run_time_tool,
    render_time_tool_text,
)
from marten_runtime.tools.registry import ToolRegistry


class ToolTests(unittest.TestCase):
    def test_render_time_tool_text_formats_human_readable_time(self) -> None:
        text = render_time_tool_text(
            {
                "timezone": "Asia/Shanghai",
                "iso_time": "2026-04-08T10:29:00+08:00",
            }
        )

        self.assertEqual(text, "现在是北京时间 2026年4月8日 10:29")

    def test_render_automation_tool_text_formats_list_result(self) -> None:
        text = render_automation_tool_text(
            {
                "action": "list",
                "count": 2,
                "items": [
                    {
                        "automation_id": "job_1",
                        "name": "早报",
                        "schedule_expr": "08:00",
                        "enabled": True,
                    },
                    {
                        "automation_id": "job_2",
                        "name": "晚报",
                        "schedule_expr": "20:00",
                        "enabled": False,
                    },
                ],
            }
        )

        self.assertIn("当前共有 2 个定时任务", text)
        self.assertNotIn("📌 共", text)
        self.assertNotIn("📁 详情", text)
        self.assertIn("- 早报｜已启用｜08:00", text)
        self.assertIn("- 晚报｜已暂停｜20:00", text)

    def test_render_automation_tool_text_formats_detail_result(self) -> None:
        text = render_automation_tool_text(
            {
                "action": "detail",
                "automation": {
                    "automation_id": "github_trending_digest_2230",
                    "name": "GitHub热榜推荐",
                    "schedule_kind": "daily",
                    "schedule_expr": "22:30",
                    "timezone": "Asia/Shanghai",
                    "enabled": True,
                    "delivery_channel": "feishu",
                    "delivery_target": "chat_1",
                    "skill_id": "github_trending_digest",
                },
            }
        )

        self.assertIn("定时任务 GitHub热榜推荐 的当前配置如下", text)
        self.assertIn("automation_id：github_trending_digest_2230", text)
        self.assertIn("状态：已启用", text)
        self.assertIn("调度：daily 22:30", text)
        self.assertIn("时区：Asia/Shanghai", text)

    def test_render_automation_tool_text_formats_register_result(self) -> None:
        text = render_automation_tool_text(
            {
                "action": "register",
                "ok": True,
                "automation_id": "daily_hot",
                "name": "Daily GitHub Hot Repos",
                "schedule_kind": "daily",
                "schedule_expr": "09:30",
                "timezone": "Asia/Shanghai",
                "enabled": True,
                "skill_id": "github_trending_digest",
            }
        )

        self.assertIn("已创建定时任务 Daily GitHub Hot Repos", text)
        self.assertIn("automation_id：daily_hot", text)
        self.assertIn("调度：daily 09:30", text)
        self.assertIn("状态：已启用", text)

    def test_render_automation_tool_text_formats_pause_resume_update_delete_results(self) -> None:
        pause_text = render_automation_tool_text(
            {
                "action": "pause",
                "ok": True,
                "automation": {
                    "automation_id": "daily_hot",
                    "name": "Daily GitHub Hot Repos",
                    "schedule_kind": "daily",
                    "schedule_expr": "09:30",
                    "timezone": "Asia/Shanghai",
                    "enabled": False,
                },
            }
        )
        resume_text = render_automation_tool_text(
            {
                "action": "resume",
                "ok": True,
                "automation": {
                    "automation_id": "daily_hot",
                    "name": "Daily GitHub Hot Repos",
                    "schedule_kind": "daily",
                    "schedule_expr": "09:30",
                    "timezone": "Asia/Shanghai",
                    "enabled": True,
                },
            }
        )
        update_text = render_automation_tool_text(
            {
                "action": "update",
                "ok": True,
                "automation": {
                    "automation_id": "daily_hot",
                    "name": "Daily GitHub Hot Repos",
                    "schedule_kind": "daily",
                    "schedule_expr": "10:00",
                    "timezone": "Asia/Shanghai",
                    "enabled": True,
                },
            }
        )
        delete_text = render_automation_tool_text(
            {
                "action": "delete",
                "ok": True,
                "automation_id": "daily_hot",
            }
        )

        self.assertIn("已暂停定时任务 Daily GitHub Hot Repos", pause_text)
        self.assertIn("状态：已暂停", pause_text)
        self.assertIn("已恢复定时任务 Daily GitHub Hot Repos", resume_text)
        self.assertIn("状态：已启用", resume_text)
        self.assertIn("已更新定时任务 Daily GitHub Hot Repos", update_text)
        self.assertIn("调度：daily 10:00", update_text)
        self.assertIn("已删除定时任务 daily_hot", delete_text)

    def _build_adapter(
        self, tmpdir: str
    ) -> tuple[DomainDataAdapter, SQLiteAutomationStore]:
        automation_store = SQLiteAutomationStore(Path(tmpdir) / "automations.sqlite3")
        adapter = DomainDataAdapter(
            self_improve_store=SQLiteSelfImproveStore(
                Path(tmpdir) / "self_improve.sqlite3"
            ),
            automation_store=automation_store,
        )
        return adapter, automation_store

    def test_runtime_tool_returns_compact_user_readable_context_status(self) -> None:
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(ScriptedLLMClient([]), ToolRegistry(), history)
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
                "model_profile": "minimax_coding",
                "current_request": LLMRequest(
                    session_id="sess_runtime",
                    trace_id="trace_runtime",
                    message="请告诉我当前上下文情况",
                    agent_id="assistant",
                    app_id="example_assistant",
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
        self.assertEqual(result["model_profile"], "minimax_coding")
        self.assertEqual(result["context_window"], 1000)
        self.assertEqual(result["effective_window"], 900)
        self.assertEqual(result["latest_checkpoint"], "available")
        self.assertEqual(result["compaction_status"], "proactive-used")
        self.assertIn("tokens", result["summary"])
        self.assertNotIn("compacted_context_id", result)

    def test_runtime_tool_prefers_actual_usage_and_reports_estimate_source(
        self,
    ) -> None:
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(ScriptedLLMClient([]), ToolRegistry(), history)
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
                "model_profile": "minimax_coding",
                "current_request": LLMRequest(
                    session_id="sess_runtime_usage",
                    trace_id="trace_runtime_usage",
                    message="现在上下文用了多少",
                    agent_id="assistant",
                    app_id="example_assistant",
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
                    agent_id="assistant",
                    app_id="example_assistant",
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
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(ScriptedLLMClient([]), ToolRegistry(), history)
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
                    agent_id="assistant",
                    app_id="example_assistant",
                ),
            },
            runtime_loop=runtime,
            run_history=history,
            latest_checkpoint_available=False,
        )

        text = render_runtime_context_status_text(result)
        self.assertIn("本轮 actual-peak：无（本轮未发生模型调用）", text)
        self.assertIn("本轮峰值输入上下文：3838 tokens", text)

    def test_runtime_tool_uses_previous_run_actual_peak_for_direct_runtime_query(
        self,
    ) -> None:
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(ScriptedLLMClient([]), ToolRegistry(), history)
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
                    agent_id="assistant",
                    app_id="example_assistant",
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
        self.assertIn("本轮 actual-peak：无（本轮未发生模型调用）", text)
        self.assertIn("上一轮 actual-peak：4262 tokens", text)

    def test_runtime_tool_skips_intermediate_no_llm_runs_when_finding_last_actual_peak(
        self,
    ) -> None:
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(ScriptedLLMClient([]), ToolRegistry(), history)

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
                    agent_id="assistant",
                    app_id="example_assistant",
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
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(ScriptedLLMClient([]), ToolRegistry(), history)
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
                    agent_id="assistant",
                    app_id="example_assistant",
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
        self.assertEqual(result["current_run"]["actual_peak_total_tokens"], 980)
        self.assertEqual(result["current_run"]["actual_peak_stage"], "llm_second")

    def test_runtime_tool_summary_calls_out_tool_result_injection_as_peak_source(
        self,
    ) -> None:
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(ScriptedLLMClient([]), ToolRegistry(), history)
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
                    agent_id="assistant",
                    app_id="example_assistant",
                ),
            },
            runtime_loop=runtime,
            run_history=history,
            latest_checkpoint_available=False,
        )

        self.assertIn("本轮首发请求约 220 tokens", result["summary"])
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
        self.assertIn("本轮 actual-peak：3280 tokens", text)
        self.assertIn("模型输入：3198", text)
        self.assertIn("模型输出：82", text)
        self.assertIn("总计：3280", text)
        self.assertIn("峰值主要来自工具结果注入后的 follow-up 模型调用", text)

    def test_runtime_tool_summary_does_not_blame_tool_injection_when_peak_matches_initial(
        self,
    ) -> None:
        history = InMemoryRunHistory()
        runtime = RuntimeLoop(ScriptedLLMClient([]), ToolRegistry(), history)
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
                    agent_id="assistant",
                    app_id="example_assistant",
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

    def test_time_tool_accepts_tz_alias_and_returns_requested_timezone_time(
        self,
    ) -> None:
        fixed_now = datetime(2026, 4, 1, 5, 47, 22, tzinfo=timezone.utc)

        with mock.patch(
            "marten_runtime.tools.builtins.time_tool.datetime"
        ) as mocked_datetime:
            mocked_datetime.now.return_value = fixed_now

            result = run_time_tool({"tz": "Asia/Shanghai"})

        self.assertEqual(result["timezone"], "Asia/Shanghai")
        self.assertEqual(result["iso_time"], "2026-04-01T13:47:22+08:00")

    def test_time_tool_defaults_to_detected_local_timezone_when_payload_empty(
        self,
    ) -> None:
        fixed_now = datetime(2026, 4, 1, 5, 47, 22, tzinfo=timezone.utc)

        with (
            mock.patch(
                "marten_runtime.tools.builtins.time_tool.datetime"
            ) as mocked_datetime,
            mock.patch(
                "marten_runtime.tools.builtins.time_tool._detect_local_timezone_label",
                return_value="Asia/Shanghai",
            ),
        ):
            mocked_datetime.now.return_value = fixed_now

            result = run_time_tool({})

        self.assertEqual(result["timezone"], "Asia/Shanghai")
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

    def test_register_automation_tool_saves_daily_job(self) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = self._build_adapter(tmpdir)
            registry = ToolRegistry()
            registry.register(
                "register_automation",
                lambda payload: run_register_automation_tool(payload, store, adapter),
            )

            result = registry.call(
                "register_automation",
                {
                    "automation_id": "daily_hot",
                    "name": "Daily GitHub Hot Repos",
                    "app_id": "example_assistant",
                    "agent_id": "assistant",
                    "prompt_template": "Summarize today's hot repositories.",
                    "schedule_kind": "daily",
                    "schedule_expr": "09:30",
                    "timezone": "Asia/Shanghai",
                    "session_target": "isolated",
                    "delivery_channel": "feishu",
                    "delivery_target": "oc_test_chat",
                    "skill_id": "github_trending_digest",
                },
            )

            enabled = store.list_enabled()

            self.assertTrue(result["ok"])
            self.assertEqual(result["automation_id"], "daily_hot")
            self.assertEqual(result["name"], "Daily GitHub Hot Repos")
            self.assertEqual(result["schedule_text"], "每天 09:30")
            self.assertIn("semantic_fingerprint", result)
            self.assertEqual(len(enabled), 1)
            self.assertEqual(enabled[0].schedule_expr, "09:30")
            self.assertEqual(enabled[0].delivery_target, "oc_test_chat")

    def test_register_automation_tool_accepts_skill_alias_and_generates_automation_id(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = self._build_adapter(tmpdir)

            result = run_register_automation_tool(
                {
                    "name": "GitHub热榜推荐",
                    "app_id": "example_assistant",
                    "agent_id": "assistant",
                    "schedule_kind": "daily",
                    "schedule_expr": "23:25",
                    "timezone": "Asia/Shanghai",
                    "delivery_channel": "feishu",
                    "delivery_target": "oc_test_chat",
                    "skill": "github_trending_digest",
                },
                store,
                adapter,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["automation_id"], "github_trending_digest_2325")
            self.assertEqual(result["name"], "GitHub热榜推荐")
            self.assertEqual(result["schedule_text"], "每天 23:25")
            saved = store.get("github_trending_digest_2325")
            self.assertEqual(saved.skill_id, "github_trending_digest")
            self.assertEqual(saved.schedule_expr, "23:25")

    def test_register_automation_tool_accepts_task_name_trigger_time_and_6field_daily_cron(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = self._build_adapter(tmpdir)

            result = run_register_automation_tool(
                {
                    "task_name": "GitHub热榜推荐 推送",
                    "app_id": "example_assistant",
                    "agent_id": "assistant",
                    "schedule_kind": "cron",
                    "schedule_expr": "0 10 21 * * *",
                    "timezone": "Asia/Shanghai",
                    "delivery_channel": "feishu",
                    "delivery_target": "oc_test_chat",
                    "skill_id": "github_trending_digest",
                },
                store,
                adapter,
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["name"], "GitHub热榜推荐 推送")
            self.assertEqual(result["schedule_kind"], "daily")
            self.assertEqual(result["schedule_expr"], "21:10")
            self.assertEqual(result["schedule_text"], "每天 21:10")

            created = store.get(result["automation_id"])
            self.assertEqual(created.name, "GitHub热榜推荐 推送")
            self.assertEqual(created.schedule_expr, "21:10")

    def test_list_automations_tool_returns_public_jobs_via_adapter(self) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = self._build_adapter(tmpdir)
            run_register_automation_tool(
                {
                    "automation_id": "daily_hot",
                    "name": "Daily GitHub Hot Repos",
                    "app_id": "example_assistant",
                    "agent_id": "assistant",
                    "prompt_template": "Summarize today's hot repositories.",
                    "schedule_kind": "daily",
                    "schedule_expr": "09:30",
                    "timezone": "Asia/Shanghai",
                    "session_target": "isolated",
                    "delivery_channel": "feishu",
                    "delivery_target": "oc_test_chat",
                    "skill_id": "github_trending_digest",
                },
                store,
                adapter,
            )
            store.save(
                AutomationJob(
                    automation_id="self_improve_internal",
                    name="Internal Self Improve",
                    app_id="example_assistant",
                    agent_id="assistant",
                    prompt_template="Summarize failures.",
                    schedule_kind="daily",
                    schedule_expr="03:00",
                    timezone="UTC",
                    session_target="isolated",
                    delivery_channel="http",
                    delivery_target="internal",
                    skill_id="self_improve",
                    enabled=True,
                    internal=True,
                )
            )

            result = run_list_automations_tool({"delivery_channel": "feishu"}, adapter)

        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["automation_id"], "daily_hot")
        self.assertEqual(result["items"][0]["name"], "Daily GitHub Hot Repos")
        self.assertEqual(result["items"][0]["schedule_text"], "每天 09:30")
        self.assertNotIn("delivery_target", result["items"][0])

    def test_automation_family_tool_defaults_empty_payload_to_list_for_read_queries(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = self._build_adapter(tmpdir)
            run_register_automation_tool(
                {
                    "automation_id": "daily_hot",
                    "name": "Daily GitHub Hot Repos",
                    "app_id": "example_assistant",
                    "agent_id": "assistant",
                    "prompt_template": "Summarize today's hot repositories.",
                    "schedule_kind": "daily",
                    "schedule_expr": "09:30",
                    "timezone": "Asia/Shanghai",
                    "session_target": "isolated",
                    "delivery_channel": "feishu",
                    "delivery_target": "oc_test_chat",
                    "skill_id": "github_trending_digest",
                },
                store,
                adapter,
            )

            result = run_automation_tool({}, store, adapter)

        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "list")
        self.assertEqual(result["count"], 1)
        self.assertNotIn("delivery_channel", result["items"][0])

    def test_list_automations_tool_normalizes_legacy_skill_named_job_for_display(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = self._build_adapter(tmpdir)
            store.save(
                AutomationJob(
                    automation_id="github_trending_digest_0102",
                    name="github_trending_digest_0102",
                    app_id="example_assistant",
                    agent_id="assistant",
                    prompt_template="",
                    schedule_kind="daily",
                    schedule_expr="0 10 21 * * *",
                    timezone="Asia/Shanghai",
                    session_target="isolated",
                    delivery_channel="feishu",
                    delivery_target="oc_test_chat",
                    skill_id="github_trending_digest",
                    enabled=True,
                    internal=False,
                )
            )

            result = run_list_automations_tool({"delivery_channel": "feishu"}, adapter)

        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(
            result["items"][0]["automation_id"], "github_trending_digest_0102"
        )
        self.assertEqual(result["items"][0]["name"], "GitHub热榜推荐")
        self.assertEqual(result["items"][0]["schedule_expr"], "21:10")
        self.assertEqual(result["items"][0]["schedule_text"], "每天 21:10")

    def test_list_automations_tool_normalizes_canonical_skill_named_job_for_display(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = self._build_adapter(tmpdir)
            store.save(
                AutomationJob(
                    automation_id="github_trending_digest_0102",
                    name="github_trending_digest_0102",
                    app_id="example_assistant",
                    agent_id="assistant",
                    prompt_template="",
                    schedule_kind="daily",
                    schedule_expr="0 10 21 * * *",
                    timezone="Asia/Shanghai",
                    session_target="isolated",
                    delivery_channel="feishu",
                    delivery_target="oc_test_chat",
                    skill_id="github_trending_digest",
                    enabled=True,
                    internal=False,
                )
            )

            result = run_list_automations_tool({"delivery_channel": "feishu"}, adapter)

        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(
            result["items"][0]["automation_id"], "github_trending_digest_0102"
        )
        self.assertEqual(result["items"][0]["name"], "GitHub热榜推荐")

    def test_list_automations_tool_normalizes_legacy_default_github_name_for_display(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = self._build_adapter(tmpdir)
            store.save(
                AutomationJob(
                    automation_id="github_digest_daily",
                    name="GitHub热榜推荐",
                    app_id="example_assistant",
                    agent_id="assistant",
                    prompt_template="",
                    schedule_kind="daily",
                    schedule_expr="23:30",
                    timezone="Asia/Shanghai",
                    session_target="isolated",
                    delivery_channel="feishu",
                    delivery_target="oc_test_chat",
                    skill_id="github_trending_digest",
                    enabled=False,
                    internal=False,
                )
            )

            result = run_list_automations_tool(
                {"delivery_channel": "feishu", "include_disabled": True}, adapter
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["automation_id"], "github_digest_daily")
        self.assertEqual(result["items"][0]["name"], "GitHub热榜推荐")

    def test_list_automations_tool_can_include_disabled_public_jobs(self) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = self._build_adapter(tmpdir)
            run_register_automation_tool(
                {
                    "automation_id": "daily_hot",
                    "name": "Daily GitHub Hot Repos",
                    "app_id": "example_assistant",
                    "agent_id": "assistant",
                    "prompt_template": "Summarize today's hot repositories.",
                    "schedule_kind": "daily",
                    "schedule_expr": "09:30",
                    "timezone": "Asia/Shanghai",
                    "session_target": "isolated",
                    "delivery_channel": "feishu",
                    "delivery_target": "oc_test_chat",
                    "skill_id": "github_trending_digest",
                },
                store,
                adapter,
            )
            store.set_enabled("daily_hot", False)

            default_result = run_list_automations_tool({}, adapter)
            disabled_result = run_list_automations_tool(
                {"include_disabled": True}, adapter
            )

        self.assertEqual(default_result["count"], 0)
        self.assertEqual(disabled_result["count"], 1)
        self.assertFalse(disabled_result["items"][0]["enabled"])

    def test_list_automations_tool_sorts_by_normalized_schedule_time_ascending(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = self._build_adapter(tmpdir)
            store.save(
                AutomationJob(
                    automation_id="job_2330",
                    name="GitHub热榜推荐",
                    app_id="example_assistant",
                    agent_id="assistant",
                    prompt_template="",
                    schedule_kind="daily",
                    schedule_expr="23:30",
                    timezone="Asia/Shanghai",
                    session_target="isolated",
                    delivery_channel="feishu",
                    delivery_target="oc_test_chat",
                    skill_id="github_trending_digest",
                    enabled=False,
                    internal=False,
                )
            )
            store.save(
                AutomationJob(
                    automation_id="job_2220",
                    name="github_trending_digest",
                    app_id="example_assistant",
                    agent_id="assistant",
                    prompt_template="",
                    schedule_kind="daily",
                    schedule_expr="22:20",
                    timezone="Asia/Shanghai",
                    session_target="isolated",
                    delivery_channel="feishu",
                    delivery_target="oc_test_chat",
                    skill_id="github_trending_digest",
                    enabled=True,
                    internal=False,
                )
            )
            store.save(
                AutomationJob(
                    automation_id="job_2110",
                    name="github_trending_digest",
                    app_id="example_assistant",
                    agent_id="assistant",
                    prompt_template="",
                    schedule_kind="daily",
                    schedule_expr="0 10 21 * * *",
                    timezone="Asia/Shanghai",
                    session_target="isolated",
                    delivery_channel="feishu",
                    delivery_target="oc_test_chat",
                    skill_id="github_trending_digest",
                    enabled=True,
                    internal=False,
                )
            )
            store.save(
                AutomationJob(
                    automation_id="job_2200",
                    name="GitHub热榜推荐",
                    app_id="example_assistant",
                    agent_id="assistant",
                    prompt_template="",
                    schedule_kind="daily",
                    schedule_expr="22:00",
                    timezone="Asia/Shanghai",
                    session_target="isolated",
                    delivery_channel="feishu",
                    delivery_target="oc_test_chat",
                    skill_id="github_trending_digest",
                    enabled=True,
                    internal=False,
                )
            )
            store.save(
                AutomationJob(
                    automation_id="job_2230",
                    name="GitHub热榜推荐",
                    app_id="example_assistant",
                    agent_id="assistant",
                    prompt_template="",
                    schedule_kind="daily",
                    schedule_expr="22:30",
                    timezone="Asia/Shanghai",
                    session_target="isolated",
                    delivery_channel="feishu",
                    delivery_target="oc_test_chat",
                    skill_id="github_trending_digest",
                    enabled=True,
                    internal=False,
                )
            )

            result = run_list_automations_tool(
                {"delivery_channel": "feishu", "include_disabled": True}, adapter
            )

        self.assertEqual(result["count"], 5)
        self.assertEqual(
            [item["schedule_expr"] for item in result["items"]],
            ["21:10", "22:00", "22:20", "22:30", "23:30"],
        )
        self.assertEqual(
            [item["name"] for item in result["items"]],
            [
                "GitHub热榜推荐",
                "GitHub热榜推荐",
                "GitHub热榜推荐",
                "GitHub热榜推荐",
                "GitHub热榜推荐",
            ],
        )

    def test_get_automation_detail_tool_returns_public_job_and_hides_internal(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = self._build_adapter(tmpdir)
            run_register_automation_tool(
                {
                    "automation_id": "daily_hot",
                    "name": "Daily GitHub Hot Repos",
                    "app_id": "example_assistant",
                    "agent_id": "assistant",
                    "prompt_template": "Summarize today's hot repositories.",
                    "schedule_kind": "daily",
                    "schedule_expr": "09:30",
                    "timezone": "Asia/Shanghai",
                    "session_target": "isolated",
                    "delivery_channel": "feishu",
                    "delivery_target": "oc_test_chat",
                    "skill_id": "github_trending_digest",
                },
                store,
                adapter,
            )
            store.save(
                AutomationJob(
                    automation_id="self_improve_internal",
                    name="Internal Self Improve",
                    app_id="example_assistant",
                    agent_id="assistant",
                    prompt_template="Summarize failures.",
                    schedule_kind="daily",
                    schedule_expr="03:00",
                    timezone="UTC",
                    session_target="isolated",
                    delivery_channel="http",
                    delivery_target="internal",
                    skill_id="self_improve",
                    enabled=True,
                    internal=True,
                )
            )

            detail = run_get_automation_detail_tool(
                {"automation_id": "daily_hot"}, adapter
            )

            with self.assertRaises(KeyError):
                run_get_automation_detail_tool(
                    {"automation_id": "self_improve_internal"}, adapter
                )
            with self.assertRaises(KeyError):
                run_get_automation_detail_tool({"automation_id": "missing"}, adapter)

        self.assertTrue(detail["ok"])
        self.assertEqual(detail["automation"]["automation_id"], "daily_hot")

    def test_update_pause_resume_and_delete_automation_tools(self) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = self._build_adapter(tmpdir)
            run_register_automation_tool(
                {
                    "automation_id": "daily_hot",
                    "name": "Daily GitHub Hot Repos",
                    "app_id": "example_assistant",
                    "agent_id": "assistant",
                    "prompt_template": "Summarize today's hot repositories.",
                    "schedule_kind": "daily",
                    "schedule_expr": "09:30",
                    "timezone": "Asia/Shanghai",
                    "session_target": "isolated",
                    "delivery_channel": "feishu",
                    "delivery_target": "oc_test_chat",
                    "skill_id": "github_trending_digest",
                },
                store,
                adapter,
            )

            updated = run_update_automation_tool(
                {
                    "automation_id": "daily_hot",
                    "name": "GitHub每日热榜Top10",
                    "schedule_expr": "23:50",
                },
                adapter,
            )
            paused = run_pause_automation_tool({"automation_id": "daily_hot"}, adapter)
            listed = run_list_automations_tool({"include_disabled": True}, adapter)
            resumed = run_resume_automation_tool(
                {"automation_id": "daily_hot"}, adapter
            )
            deleted = run_delete_automation_tool(
                {"automation_id": "daily_hot"}, adapter
            )

            self.assertTrue(updated["ok"])
            self.assertEqual(updated["automation"]["schedule_expr"], "23:50")
            self.assertFalse(paused["automation"]["enabled"])
            self.assertEqual(listed["count"], 1)
            self.assertFalse(listed["items"][0]["enabled"])
            self.assertTrue(resumed["automation"]["enabled"])
            self.assertTrue(deleted["ok"])
            self.assertEqual(store.list_all(), [])

    def test_update_automation_tool_canonicalizes_digest_skill_and_recomputes_fingerprint(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = self._build_adapter(tmpdir)
            run_register_automation_tool(
                {
                    "automation_id": "daily_hot",
                    "name": "Daily GitHub Hot Repos",
                    "app_id": "example_assistant",
                    "agent_id": "assistant",
                    "prompt_template": "Summarize today's hot repositories.",
                    "schedule_kind": "daily",
                    "schedule_expr": "09:30",
                    "timezone": "Asia/Shanghai",
                    "session_target": "isolated",
                    "delivery_channel": "feishu",
                    "delivery_target": "oc_test_chat",
                    "skill_id": "github_trending_digest",
                },
                store,
                adapter,
            )
            before = store.get("daily_hot")

            updated = run_update_automation_tool(
                {
                    "automation_id": "daily_hot",
                    "skill_id": "github_trending_digest",
                    "schedule_expr": "23:50",
                },
                adapter,
            )
            after = store.get("daily_hot")

        self.assertTrue(updated["ok"])
        self.assertEqual(after.skill_id, "github_trending_digest")
        self.assertEqual(after.schedule_expr, "23:50")
        self.assertNotEqual(before.semantic_fingerprint, after.semantic_fingerprint)

    def test_automation_family_tool_dispatches_register_and_list(self) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = self._build_adapter(tmpdir)

            created = run_automation_tool(
                {
                    "action": "register",
                    "automation_id": "daily_hot",
                    "name": "Daily GitHub Hot Repos",
                    "app_id": "example_assistant",
                    "agent_id": "assistant",
                    "prompt_template": "Summarize today's hot repositories.",
                    "schedule_kind": "daily",
                    "schedule_expr": "09:30",
                    "timezone": "Asia/Shanghai",
                    "session_target": "isolated",
                    "delivery_channel": "feishu",
                    "delivery_target": "oc_test_chat",
                    "skill_id": "github_trending_digest",
                },
                store,
                adapter,
            )
            listed = run_automation_tool(
                {"action": "list", "include_disabled": True}, store, adapter
            )

        self.assertEqual(created["action"], "register")
        self.assertTrue(created["ok"])
        self.assertEqual(listed["action"], "list")
        self.assertEqual(listed["count"], 1)

    def test_automation_family_tool_list_includes_paused_jobs_by_default(self) -> None:
        with TemporaryDirectory() as tmpdir:
            adapter, store = self._build_adapter(tmpdir)
            run_register_automation_tool(
                {
                    "automation_id": "daily_hot",
                    "name": "Daily GitHub Hot Repos",
                    "app_id": "example_assistant",
                    "agent_id": "assistant",
                    "prompt_template": "Summarize today's hot repositories.",
                    "schedule_kind": "daily",
                    "schedule_expr": "09:30",
                    "timezone": "Asia/Shanghai",
                    "session_target": "isolated",
                    "delivery_channel": "feishu",
                    "delivery_target": "oc_test_chat",
                    "skill_id": "github_trending_digest",
                },
                store,
                adapter,
            )
            store.set_enabled("daily_hot", False)

            listed = run_automation_tool({"action": "list"}, store, adapter)

        self.assertEqual(listed["action"], "list")
        self.assertTrue(listed["ok"])
        self.assertEqual(listed["count"], 1)
        self.assertFalse(listed["items"][0]["enabled"])

    def test_self_improve_tools_list_evidence_and_lessons_and_save_candidates(
        self,
    ) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            adapter = DomainDataAdapter(self_improve_store=store)
            store.record_failure(
                FailureEvent(
                    failure_id="failure_1",
                    agent_id="assistant",
                    run_id="run_1",
                    trace_id="trace_1",
                    session_id="session_1",
                    error_code="PROVIDER_TIMEOUT",
                    error_stage="llm",
                    summary="provider timed out",
                    fingerprint="assistant|hello",
                )
            )
            store.save_lesson(
                SystemLesson(
                    lesson_id="lesson_1",
                    agent_id="assistant",
                    topic_key="provider_timeout",
                    lesson_text="先减少无关工具面。",
                    source_fingerprints=["assistant|hello"],
                    active=True,
                )
            )
            store.save_candidate(
                LessonCandidate(
                    candidate_id="cand_keep",
                    agent_id="assistant",
                    source_fingerprints=["assistant|hello", "assistant|hello"],
                    candidate_text="pending candidate",
                    rationale="same failure repeated",
                    status="pending",
                    score=0.8,
                )
            )

            evidence = run_list_self_improve_evidence_tool(
                {"agent_id": "assistant"}, store
            )
            candidate = run_save_lesson_candidate_tool(
                {
                    "candidate_id": "cand_1",
                    "agent_id": "assistant",
                    "source_fingerprints": ["assistant|hello"],
                    "candidate_text": "遇到重复 provider timeout 时先减少无关工具面。",
                    "rationale": "same failure repeated",
                    "score": 0.9,
                },
                store,
            )
            candidates = run_list_lesson_candidates_tool(
                {"agent_id": "assistant", "status": "pending"}, adapter
            )
            detail = run_get_lesson_candidate_detail_tool(
                {"candidate_id": "cand_1"}, adapter
            )
            summary = run_get_self_improve_summary_tool(
                {"agent_id": "assistant"}, store
            )
            deleted = run_delete_lesson_candidate_tool(
                {"candidate_id": "cand_keep"}, adapter
            )
            missing_delete = run_delete_lesson_candidate_tool(
                {"candidate_id": "cand_missing"}, adapter
            )
            lessons = run_list_system_lessons_tool({"agent_id": "assistant"}, store)

        self.assertTrue(evidence["ok"])
        self.assertEqual(evidence["failure_count"], 1)
        self.assertTrue(candidate["ok"])
        self.assertEqual(candidate["candidate"]["status"], "pending")
        self.assertTrue(candidates["ok"])
        self.assertEqual(candidates["count"], 2)
        self.assertEqual(detail["candidate"]["candidate_id"], "cand_1")
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["candidate_counts"]["pending"], 2)
        self.assertEqual(summary["active_lessons_count"], 1)
        self.assertTrue(deleted["ok"])
        self.assertFalse(missing_delete["ok"])
        self.assertEqual(missing_delete["error"], "LESSON_CANDIDATE_NOT_FOUND")
        self.assertTrue(lessons["ok"])
        self.assertEqual(lessons["count"], 1)

    def test_self_improve_family_tool_dispatches_summary_and_delete(self) -> None:
        with TemporaryDirectory() as tmpdir:
            store = SQLiteSelfImproveStore(Path(tmpdir) / "self_improve.sqlite3")
            adapter = DomainDataAdapter(self_improve_store=store)
            store.save_lesson(
                SystemLesson(
                    lesson_id="lesson_1",
                    agent_id="assistant",
                    topic_key="provider_timeout",
                    lesson_text="先减少无关工具面。",
                    source_fingerprints=["assistant|hello"],
                    active=True,
                )
            )
            store.save_candidate(
                LessonCandidate(
                    candidate_id="cand_keep",
                    agent_id="assistant",
                    source_fingerprints=["assistant|hello", "assistant|hello"],
                    candidate_text="pending candidate",
                    rationale="same failure repeated",
                    status="pending",
                    score=0.8,
                )
            )

            summary = run_self_improve_tool(
                {"action": "summary", "agent_id": "assistant"}, adapter, store
            )
            deleted = run_self_improve_tool(
                {"action": "delete_candidate", "candidate_id": "cand_keep"},
                adapter,
                store,
            )

        self.assertEqual(summary["action"], "summary")
        self.assertTrue(summary["ok"])
        self.assertEqual(deleted["action"], "delete_candidate")
        self.assertTrue(deleted["ok"])


if __name__ == "__main__":
    unittest.main()
