import os
import queue
import unittest
from unittest.mock import patch

from pathlib import Path
from tempfile import TemporaryDirectory

from marten_runtime.evals.compare import _extract_total_tokens_from_result
from marten_runtime.evals.executor import (
    REPO_ROOT,
    _copy_repo_scaffold,
    _execute_case_live,
    _execute_case_live_child,
    _execute_case_live_with_timeout,
    _is_retryable_live_subagent_timeout,
    _seed_case_state,
    _should_collect_subagent_diagnostics,
    _should_include_live_mcp_scaffold,
    execute_suite,
)
from marten_runtime.evals.graders import grade_case_result
from marten_runtime.evals.loader import load_case_spec, load_suite_spec
from marten_runtime.evals.scripted_runtime import (
    FixedReplyLLMClient,
    PromptTooLongThenCompactThenFinalEvalClient,
    ScriptedEvalLLMClient,
    _contracted_final_reply,
)
from marten_runtime.evals.models import (
    EvalCaseSpec,
    EvalCaseObservation,
    EvalExpectations,
    EvalFinalTextExpectations,
    EvalSuiteSpec,
    EvalToolCallExpectations,
    EvalTurnSpec,
    EvalWeights,
)
from marten_runtime.interfaces.http.app import create_app
from marten_runtime.runtime.llm_client import LLMRequest
from marten_runtime.runtime.recovery_flow import assess_finalization_text_with_details
from marten_runtime.tools.registry import ToolSnapshot
from tests.http_app_support import build_test_app


class EvalExecutorTests(unittest.TestCase):
    @staticmethod
    def _request(*, request_kind: str, message: str = "你好") -> LLMRequest:
        return LLMRequest(
            session_id="sess_eval",
            trace_id="trace_eval",
            message=message,
            summary_input_text=message if request_kind == "session_summary" else None,
            agent_id="main",
            available_tools=[],
            tool_snapshot=ToolSnapshot(tool_snapshot_id="tool_empty"),
            request_kind=request_kind,
        )

    def test_scripted_eval_contracted_reply_uses_transport_style_contract_block(self) -> None:
        reply = _contracted_final_reply("scripted eval ok")

        self.assertIsNone(reply.finalization_contract_draft)
        self.assertIn("```finalization_contract", reply.final_text or "")

    def test_scripted_eval_direct_answer_initial_reply_does_not_preseed_structured_contract(self) -> None:
        llm = ScriptedEvalLLMClient(
            case_id="direct_answer_cn",
            provider_name="openai",
            model_name="gpt-5.4",
        )

        reply = llm.complete(self._request(request_kind="interactive"))
        details = assess_finalization_text_with_details(
            [],
            reply.final_text or "",
            user_message="你好",
            finalization_contract_draft=reply.finalization_contract_draft,
            enforce_structured_contract=True,
        )

        self.assertEqual(reply.final_text, "你好，我在。")
        self.assertIsNone(reply.finalization_contract_draft)
        self.assertEqual(details.assessment, "unrecoverable")

    def test_scripted_eval_clients_do_not_synthesize_session_summary_metadata(self) -> None:
        request = self._request(request_kind="session_summary", message="用户消息")
        clients = [
            ScriptedEvalLLMClient(
                case_id="direct_answer_cn",
                provider_name="openai",
                model_name="gpt-5.4",
            ),
            PromptTooLongThenCompactThenFinalEvalClient(
                provider_name="openai",
                model_name="gpt-5.4",
                final_text="final",
            ),
            FixedReplyLLMClient(
                provider_name="openai",
                model_name="gpt-5.4",
                reply_text="final",
            ),
        ]

        for client in clients:
            with self.subTest(client=client.__class__.__name__):
                reply = client.complete(request)
                self.assertEqual(reply.final_text, "")
                self.assertIsNone(reply.finalization_contract_draft)

    def test_execute_suite_scripted_direct_answer_case(self) -> None:
        case = EvalCaseSpec(
            case_id="direct_answer_cn",
            suite_id="main_chain_core",
            family="direct_answer",
            description="direct answer",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            turns=[EvalTurnSpec(role="user", content="你好")],
            expectations=EvalExpectations(
                final_text=EvalFinalTextExpectations(contains_any=["你好"]),
                tool_path=EvalToolCallExpectations(),
            ),
            weights=EvalWeights(outcome=100, tool_path=0, efficiency=0, context=0),
        )
        suite = EvalSuiteSpec(
            suite_id="main_chain_core",
            description="demo",
            default_mode="scripted",
            scripted_supported=True,
            required_dependencies=["provider"],
            baseline_policy="latest_passed_auto",
            case_files=[],
            cases=[case],
            suite_fingerprint="suite123",
        )

        summary, observations = execute_suite(suite, mode="scripted", profile_name="openai_gpt_5_4")

        self.assertEqual(summary.eval_mode, "scripted")
        self.assertEqual(len(observations), 1)
        self.assertIn("你好", observations[0].final_text)
        self.assertTrue(observations[0].run_id)
        self.assertTrue(observations[0].trace_id)

    def test_execute_suite_single_turn_observation_keeps_run_diagnostics_for_token_extraction(self) -> None:
        case = EvalCaseSpec(
            case_id="direct_answer_cn",
            suite_id="main_chain_core",
            family="direct_answer",
            description="direct answer",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            turns=[EvalTurnSpec(role="user", content="你好")],
            expectations=EvalExpectations(
                final_text=EvalFinalTextExpectations(contains_any=["你好"]),
                tool_path=EvalToolCallExpectations(),
            ),
            weights=EvalWeights(outcome=100, tool_path=0, efficiency=0, context=0),
        )
        suite = EvalSuiteSpec(
            suite_id="main_chain_core",
            description="demo",
            default_mode="scripted",
            scripted_supported=True,
            required_dependencies=["provider"],
            baseline_policy="latest_passed_auto",
            case_files=[],
            cases=[case],
            suite_fingerprint="suite123",
        )

        summary, observations = execute_suite(suite, mode="scripted", profile_name="openai_gpt_5_4")

        turns = observations[0].diagnostics_json.get("turns") or []
        self.assertEqual(len(turns), 1)
        self.assertIn("run", turns[0])
        result = grade_case_result(case, observations[0], eval_run_id=summary.eval_run_id)
        self.assertEqual(_extract_total_tokens_from_result(result), 0.0)

    def test_execute_suite_scripted_single_tool_case_collects_tool_calls(self) -> None:
        case = EvalCaseSpec(
            case_id="time_single_tool_cn",
            suite_id="main_chain_core",
            family="single_tool",
            description="time",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            turns=[EvalTurnSpec(role="user", content="告诉我北京时间")],
            expectations=EvalExpectations(
                final_text=EvalFinalTextExpectations(contains_all=["北京时间"]),
                tool_path=EvalToolCallExpectations(),
            ),
            weights=EvalWeights(outcome=100, tool_path=0, efficiency=0, context=0),
        )
        suite = EvalSuiteSpec(
            suite_id="main_chain_core",
            description="demo",
            default_mode="scripted",
            scripted_supported=True,
            required_dependencies=["provider"],
            baseline_policy="latest_passed_auto",
            case_files=[],
            cases=[case],
            suite_fingerprint="suite123",
        )

        _, observations = execute_suite(suite, mode="scripted", profile_name="openai_gpt_5_4")

        self.assertEqual(observations[0].tool_calls_count, 1)
        self.assertEqual(observations[0].tool_calls[0]["tool_name"], "time")

    def test_seed_case_state_preloads_compacted_context_for_compaction_continuity_case(self) -> None:
        app = build_test_app(emit_explicit_empty_contract=True)
        runtime = app.state.runtime
        case = load_case_spec(
            Path("evals/cases/main_chain_core/context_compaction_continuity_cn.toml")
        )

        _seed_case_state(runtime, case)
        compacted = runtime.session_store.get(
            "seed_context_compaction_continuity_cn"
        ).latest_compacted_context
        self.assertIsNotNone(compacted)
        self.assertEqual(
            compacted.compact_id if compacted is not None else None,
            "cmp_eval_context_continuity",
        )
        self.assertIn("日报同步告警排查", compacted.summary_text if compacted is not None else "")

    def test_seed_case_state_lowers_profile_window_for_proactive_compaction_case(self) -> None:
        app = build_test_app(emit_explicit_empty_contract=True)
        runtime = app.state.runtime
        case = load_case_spec(
            Path("evals/cases/main_chain_core/proactive_compaction_cn.toml")
        )

        original = runtime.models_config.profiles[case.profile_name]
        _seed_case_state(runtime, case)
        updated = runtime.models_config.profiles[case.profile_name]

        self.assertEqual(updated.context_window_tokens, 400)
        self.assertEqual(updated.reserve_output_tokens, 50)
        self.assertEqual(updated.compact_trigger_ratio, 0.5)
        self.assertNotEqual(updated.context_window_tokens, original.context_window_tokens)

    def test_seed_case_state_can_target_effective_profile_override(self) -> None:
        app = build_test_app(emit_explicit_empty_contract=True)
        runtime = app.state.runtime
        case = load_case_spec(
            Path("evals/cases/main_chain_core/proactive_compaction_cn.toml")
        ).model_copy(update={"profile_name": "minimax_m2_7_highspeed"})

        original_openai = runtime.models_config.profiles["openai_gpt_5_4"]
        original_minimax = runtime.models_config.profiles["minimax_m2_7_highspeed"]
        _seed_case_state(runtime, case, effective_profile_name="openai_gpt_5_4")
        updated_openai = runtime.models_config.profiles["openai_gpt_5_4"]
        updated_minimax = runtime.models_config.profiles["minimax_m2_7_highspeed"]

        self.assertEqual(updated_openai.context_window_tokens, 400)
        self.assertEqual(updated_openai.reserve_output_tokens, 50)
        self.assertEqual(updated_openai.compact_trigger_ratio, 0.5)
        self.assertEqual(
            updated_minimax.context_window_tokens,
            original_minimax.context_window_tokens,
        )
        self.assertEqual(
            updated_minimax.reserve_output_tokens,
            original_minimax.reserve_output_tokens,
        )
        self.assertNotEqual(
            updated_openai.context_window_tokens,
            original_openai.context_window_tokens,
        )

    def test_copy_repo_scaffold_keeps_live_eval_memory_isolated_per_workspace(self) -> None:
        env = {"OPENAI_API_KEY": "test-key", "MINIMAX_API_KEY": "test-key"}
        with TemporaryDirectory() as left_dir, TemporaryDirectory() as right_dir:
            left_root = Path(left_dir)
            right_root = Path(right_dir)
            _copy_repo_scaffold(REPO_ROOT, left_root, include_mcp=False)
            _copy_repo_scaffold(REPO_ROOT, right_root, include_mcp=False)

            left_app = create_app(repo_root=left_root, env=env, load_env_file=False)
            right_app = create_app(repo_root=right_root, env=env, load_env_file=False)

            left_runtime = left_app.state.runtime
            right_runtime = right_app.state.runtime
            left_runtime.memory_service.replace(
                "eval-user",
                section="preferences",
                content="以后回答尽量简洁。",
            )

            self.assertEqual(
                left_runtime.memory_service.load("eval-user").sections,
                {"preferences": ["以后回答尽量简洁。"]},
            )
            self.assertEqual(
                right_runtime.memory_service.load("eval-user").sections,
                {},
            )

    def test_execute_suite_scripted_subagent_case_collects_child_and_parent_diagnostics(self) -> None:
        case = load_case_spec(
            Path("evals/cases/subagent_task_progress/subagent_child_completion_notice_cn.toml")
        )
        suite = EvalSuiteSpec(
            suite_id="subagent_task_progress",
            grader_id="subagent_task_progress",
            description="subagent eval",
            default_mode="scripted",
            scripted_supported=True,
            required_dependencies=["provider", "subagent"],
            baseline_policy="latest_passed_auto",
            case_files=[],
            cases=[case],
            suite_fingerprint="suite123",
        )

        _, observations = execute_suite(suite, mode="scripted", profile_name="openai_gpt_5_4")

        self.assertEqual(len(observations), 1)
        subagent = observations[0].diagnostics_json.get("subagent") or {}
        tasks = list(subagent.get("tasks") or [])
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["status"], "succeeded")
        self.assertTrue(tasks[0].get("child_run"))
        parent_session = subagent.get("parent_session") or {}
        history = list(parent_session.get("history") or [])
        self.assertTrue(
            any(
                item.get("role") == "system"
                and "subagent task completed" in str(item.get("content") or "")
                for item in history
            )
        )

    def test_execute_suite_scripted_runtime_case_does_not_depend_on_context_substring(self) -> None:
        case = load_case_spec(
            Path("evals/cases/main_chain_core/multi_turn_time_then_context_cn.toml")
        ).model_copy(
            update={
                "turns": [
                    EvalTurnSpec(role="user", content="先告诉我现在北京时间。"),
                    EvalTurnSpec(role="user", content="再告诉我当前 token 窗口使用情况。"),
                ]
            }
        )
        suite = EvalSuiteSpec(
            suite_id="main_chain_core",
            description="demo",
            default_mode="scripted",
            scripted_supported=True,
            required_dependencies=["provider"],
            baseline_policy="latest_passed_auto",
            case_files=[],
            cases=[case],
            suite_fingerprint="suite123",
        )

        _, observations = execute_suite(suite, mode="scripted", profile_name="openai_gpt_5_4")

        self.assertEqual([call["tool_name"] for call in observations[0].tool_calls], ["time", "runtime"])
        self.assertIn("当前上下文使用详情", observations[0].final_text)

    def test_execute_suite_scripted_cross_session_memory_case_does_not_depend_on_exact_new_session_phrase(
        self,
    ) -> None:
        case = load_case_spec(
            Path("evals/cases/memory_long_horizon/memory_delayed_recall_cross_session_cn.toml")
        ).model_copy(
            update={
                "turns": [
                    EvalTurnSpec(role="user", content="记住：技术方案默认用中文标题。"),
                    EvalTurnSpec(role="user", content="切到一个新会话。"),
                    EvalTurnSpec(
                        role="user",
                        content="我在新会话里继续写技术方案，直接告诉我标题应该怎么写，并明确标题语言。",
                    ),
                ]
            }
        )
        suite = EvalSuiteSpec(
            suite_id="memory_long_horizon",
            grader_id="memory_long_horizon",
            description="memory eval",
            default_mode="scripted",
            scripted_supported=True,
            required_dependencies=["provider"],
            baseline_policy="latest_passed_auto",
            case_files=[],
            cases=[case],
            suite_fingerprint="suite123",
        )

        _, observations = execute_suite(suite, mode="scripted", profile_name="openai_gpt_5_4")

        self.assertEqual([call["tool_name"] for call in observations[0].tool_calls], ["memory", "session"])
        self.assertIn("中文标题", observations[0].final_text)

    def test_execute_suite_live_copies_mcp_scaffold_when_suite_declares_mcp_dependency(self) -> None:
        case = EvalCaseSpec(
            case_id="subagent_live_probe",
            suite_id="subagent_task_progress",
            family="subagent_task_progress",
            grader_id="subagent_task_progress",
            description="probe",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            turns=[EvalTurnSpec(role="user", content="probe")],
            component_weights={"delegation_quality": 100},
            gate_components=["delegation_quality"],
        )
        suite = EvalSuiteSpec(
            suite_id="subagent_task_progress",
            grader_id="subagent_task_progress",
            description="probe",
            default_mode="live",
            scripted_supported=True,
            required_dependencies=["provider", "subagent", "mcp"],
            baseline_policy="latest_passed_auto",
            case_files=[],
            cases=[case],
            suite_fingerprint="suite123",
        )
        captured: list[bool] = []

        def _fake_execute_case_live(case_arg, *, source_repo_root, include_mcp, profile_name):  # noqa: ANN001
            captured.append(bool(include_mcp))
            self.assertEqual(profile_name, "openai_gpt_5_4")
            return type("Obs", (), {"final_text": "", "run_id": None, "trace_id": None, "tool_calls": [], "tool_calls_count": 0, "llm_request_count": 0, "duration_ms": 0, "diagnostics_json": {}, "blocked_reason": None, "error_code": None, "langfuse_url": None, "case_id": case_arg.case_id, "family": case_arg.family})()

        with patch("marten_runtime.evals.executor._execute_case_live", side_effect=_fake_execute_case_live):
            execute_suite(suite, mode="live", profile_name="openai_gpt_5_4")

        self.assertEqual(captured, [True])

    def test_execute_suite_scripted_skips_local_mcp_bootstrap(self) -> None:
        case = EvalCaseSpec(
            case_id="subagent_scripted_probe",
            suite_id="subagent_task_progress",
            family="subagent_task_progress",
            grader_id="subagent_task_progress",
            description="probe",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            turns=[EvalTurnSpec(role="user", content="probe")],
            component_weights={"delegation_quality": 100},
            gate_components=["delegation_quality"],
        )
        suite = EvalSuiteSpec(
            suite_id="subagent_task_progress",
            grader_id="subagent_task_progress",
            description="probe",
            default_mode="live",
            scripted_supported=True,
            required_dependencies=["provider", "subagent", "mcp"],
            baseline_policy="latest_passed_auto",
            case_files=[],
            cases=[case],
            suite_fingerprint="suite123",
        )
        captured: list[bool] = []

        def _fake_execute_case_scripted(
            case_arg,
            *,
            source_repo_root,
            effective_profile_name,
            provider_name,
            model_name,
            include_mcp,
        ):  # noqa: ANN001
            del source_repo_root, provider_name, model_name
            captured.append(bool(include_mcp))
            self.assertEqual(effective_profile_name, "openai_gpt_5_4")
            return EvalCaseObservation(case_id=case_arg.case_id, family=case_arg.family)

        with patch("marten_runtime.evals.executor._execute_case_scripted", side_effect=_fake_execute_case_scripted):
            execute_suite(suite, mode="scripted", profile_name="openai_gpt_5_4")

        self.assertEqual(captured, [False])

    def test_execute_suite_live_provider_only_suite_skips_local_mcp_bootstrap(self) -> None:
        case = EvalCaseSpec(
            case_id="provider_only_live_probe",
            suite_id="main_chain_core",
            family="direct_answer",
            description="probe",
            agent_id="main",
            profile_name="openai_gpt_5_4",
            turns=[EvalTurnSpec(role="user", content="你好")],
            expectations=EvalExpectations(
                final_text=EvalFinalTextExpectations(contains_any=["你好"]),
                tool_path=EvalToolCallExpectations(),
            ),
            weights=EvalWeights(outcome=100, tool_path=0, efficiency=0, context=0),
        )
        suite = EvalSuiteSpec(
            suite_id="main_chain_core",
            description="probe",
            default_mode="live",
            scripted_supported=True,
            required_dependencies=["provider"],
            baseline_policy="latest_passed_auto",
            case_files=[],
            cases=[case],
            suite_fingerprint="suite123",
        )
        captured: dict[str, object] = {}

        def _fake_run_case(app, case_arg):  # noqa: ANN001
            del case_arg
            captured["mcp_servers"] = [server.server_id for server in app.state.runtime.mcp_servers]
            captured["mcp_discovery"] = dict(app.state.runtime.mcp_discovery)
            return EvalCaseObservation(case_id=case.case_id, family=case.family)

        with patch(
            "marten_runtime.evals.executor._run_case_via_http",
            side_effect=_fake_run_case,
        ), patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "test-key", "MINIMAX_API_KEY": "test-key"},
            clear=False,
        ):
            execute_suite(suite, mode="live", profile_name="openai_gpt_5_4")

        self.assertEqual(captured["mcp_servers"], [])
        self.assertEqual(captured["mcp_discovery"], {})

    def test_execute_suite_live_overrides_agent_profiles_with_requested_profile(self) -> None:
        case = EvalCaseSpec(
            case_id="live_profile_override_probe",
            suite_id="main_chain_core",
            family="direct_answer",
            description="probe",
            agent_id="main",
            profile_name="minimax_m2_7_highspeed",
            turns=[EvalTurnSpec(role="user", content="你好")],
            expectations=EvalExpectations(
                final_text=EvalFinalTextExpectations(contains_any=["你好"]),
                tool_path=EvalToolCallExpectations(),
            ),
            weights=EvalWeights(outcome=100, tool_path=0, efficiency=0, context=0),
        )
        suite = EvalSuiteSpec(
            suite_id="main_chain_core",
            description="probe",
            default_mode="live",
            scripted_supported=True,
            required_dependencies=["provider"],
            baseline_policy="latest_passed_auto",
            case_files=[],
            cases=[case],
            suite_fingerprint="suite123",
        )
        captured: dict[str, str | None] = {}

        def _fake_run_case(app, case_arg):  # noqa: ANN001
            runtime = app.state.runtime
            captured["requested_agent_profile"] = runtime.agent_registry.get(
                case_arg.agent_id
            ).model_profile
            captured["default_agent_profile"] = runtime.default_agent.model_profile
            return EvalCaseObservation(case_id=case_arg.case_id, family=case_arg.family)

        with patch(
            "marten_runtime.evals.executor._run_case_via_http",
            side_effect=_fake_run_case,
        ), patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "test-key", "MINIMAX_API_KEY": "test-key"},
            clear=False,
        ):
            execute_suite(suite, mode="live", profile_name="openai_gpt_5_4")

        self.assertEqual(captured["requested_agent_profile"], "openai_gpt_5_4")
        self.assertEqual(captured["default_agent_profile"], "openai_gpt_5_4")

    def test_execute_suite_scripted_overrides_agent_profiles_with_requested_profile(self) -> None:
        case = EvalCaseSpec(
            case_id="scripted_profile_override_probe",
            suite_id="main_chain_core",
            family="direct_answer",
            description="probe",
            agent_id="main",
            profile_name="minimax_m2_7_highspeed",
            turns=[EvalTurnSpec(role="user", content="你好")],
            expectations=EvalExpectations(
                final_text=EvalFinalTextExpectations(contains_any=["你好"]),
                tool_path=EvalToolCallExpectations(),
            ),
            weights=EvalWeights(outcome=100, tool_path=0, efficiency=0, context=0),
        )
        suite = EvalSuiteSpec(
            suite_id="main_chain_core",
            description="probe",
            default_mode="scripted",
            scripted_supported=True,
            required_dependencies=["provider"],
            baseline_policy="latest_passed_auto",
            case_files=[],
            cases=[case],
            suite_fingerprint="suite123",
        )
        captured: dict[str, str | None] = {}

        def _fake_run_case(app, case_arg):  # noqa: ANN001
            runtime = app.state.runtime
            captured["requested_agent_profile"] = runtime.agent_registry.get(
                case_arg.agent_id
            ).model_profile
            captured["default_agent_profile"] = runtime.default_agent.model_profile
            return EvalCaseObservation(case_id=case_arg.case_id, family=case_arg.family)

        with patch(
            "marten_runtime.evals.executor._run_case_via_http",
            side_effect=_fake_run_case,
        ):
            execute_suite(suite, mode="scripted", profile_name="openai_gpt_5_4")

        self.assertEqual(captured["requested_agent_profile"], "openai_gpt_5_4")
        self.assertEqual(captured["default_agent_profile"], "openai_gpt_5_4")

    def test_live_subagent_timeout_retry_predicate_uses_structured_provider_diagnostics(self) -> None:
        case = load_case_spec(
            Path("evals/cases/subagent_task_progress/subagent_child_completion_notice_cn.toml")
        )
        observation = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            diagnostics_json={
                "subagent": {
                    "tasks": [
                        {
                            "status": "timed_out",
                            "child_run": {
                                "error_code": "PROVIDER_TIMEOUT",
                                "provider_calls": [
                                    {
                                        "final_error_code": "PROVIDER_TIMEOUT",
                                        "attempts": [
                                            {"retryable": True, "error_code": "PROVIDER_UPSTREAM_UNAVAILABLE"}
                                        ],
                                    }
                                ],
                            },
                        }
                    ]
                }
            },
        )

        self.assertTrue(_is_retryable_live_subagent_timeout(case, observation))

    def test_execute_case_live_retries_once_after_structured_subagent_provider_timeout(self) -> None:
        case = load_case_spec(
            Path("evals/cases/subagent_task_progress/subagent_child_completion_notice_cn.toml")
        )
        timeout_observation = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            diagnostics_json={
                "subagent": {
                    "tasks": [
                        {
                            "status": "timed_out",
                            "child_run": {
                                "error_code": "PROVIDER_TIMEOUT",
                                "provider_calls": [
                                    {
                                        "final_error_code": "PROVIDER_TIMEOUT",
                                        "attempts": [{"retryable": True}],
                                    }
                                ],
                            },
                        }
                    ]
                }
            },
        )
        passed_observation = EvalCaseObservation(
            case_id=case.case_id,
            family=case.family,
            final_text="子任务已完成。",
        )

        with patch(
            "marten_runtime.evals.executor._run_case_via_http",
            side_effect=[timeout_observation, passed_observation],
        ) as run_case, patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "test-key", "MINIMAX_API_KEY": "test-key"},
            clear=False,
        ):
            observation = _execute_case_live(
                case,
                source_repo_root=REPO_ROOT,
                include_mcp=False,
                profile_name="openai_gpt_5_4",
            )

        self.assertIs(observation, passed_observation)
        self.assertEqual(run_case.call_count, 2)

    def test_execute_suite_live_caps_subagent_timeout_to_case_wait_budget(self) -> None:
        case = load_case_spec(
            Path("evals/cases/subagent_task_progress/subagent_child_completion_notice_cn.toml")
        )
        suite = EvalSuiteSpec(
            suite_id="subagent_task_progress",
            grader_id="subagent_task_progress",
            description="probe",
            default_mode="live",
            scripted_supported=True,
            required_dependencies=["provider", "subagent"],
            baseline_policy="latest_passed_auto",
            case_files=[],
            cases=[case],
            suite_fingerprint="suite123",
        )
        captured: dict[str, object] = {}

        def _fake_run_case(app, case_arg):  # noqa: ANN001
            captured["subagent_timeout_seconds"] = (
                app.state.runtime.subagent_service.subagent_timeout_seconds
            )
            return EvalCaseObservation(case_id=case_arg.case_id, family=case_arg.family)

        with patch(
            "marten_runtime.evals.executor._run_case_via_http",
            side_effect=_fake_run_case,
        ), patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "test-key", "MINIMAX_API_KEY": "test-key"},
            clear=False,
        ):
            _execute_case_live(
                case,
                source_repo_root=REPO_ROOT,
                include_mcp=False,
                profile_name="openai_gpt_5_4",
            )

        self.assertEqual(captured["subagent_timeout_seconds"], 300)


    def test_subagent_dispatch_case_collects_diagnostics_after_single_turn(self) -> None:
        case = load_case_spec(
            Path("evals/cases/subagent_task_progress/subagent_background_task_acceptance_cn.toml")
        ).model_copy(update={"grader_id": "subagent_task_progress"})

        self.assertTrue(_should_collect_subagent_diagnostics(case, 1))

    def test_subagent_external_mcp_suite_keeps_mcp_dependency_separate(self) -> None:
        progress_suite = load_suite_spec(Path("evals/suites/subagent_task_progress.toml"))
        external_suite = load_suite_spec(Path("evals/suites/subagent_external_mcp_completion.toml"))

        self.assertEqual(progress_suite.required_dependencies, ["provider", "subagent"])
        self.assertEqual(external_suite.required_dependencies, ["provider", "subagent", "mcp"])
        self.assertEqual(external_suite.cases[0].grader_case["timeout_ms"], 300000)


    def test_live_case_timeout_uses_case_grader_timeout_when_larger_than_global_default(self) -> None:
        case = load_case_spec(
            Path("evals/cases/subagent_task_progress/subagent_external_mcp_completion_cn.toml")
        )
        suite = EvalSuiteSpec(
            suite_id="subagent_external_mcp_completion",
            grader_id="subagent_task_progress",
            description="probe",
            default_mode="live",
            scripted_supported=True,
            required_dependencies=["provider", "subagent", "mcp"],
            baseline_policy="latest_passed_auto",
            case_files=[],
            cases=[case],
            suite_fingerprint="suite123",
        )
        captured: list[float | None] = []

        def _fake_execute_case_live_with_timeout(case_arg, **kwargs):  # noqa: ANN001
            del case_arg
            captured.append(kwargs.get("case_timeout_seconds"))
            return EvalCaseObservation(case_id=case.case_id, family=case.family)

        with patch(
            "marten_runtime.evals.executor._execute_case_live_with_timeout",
            side_effect=_fake_execute_case_live_with_timeout,
        ), patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "test-key", "MINIMAX_API_KEY": "test-key"},
            clear=False,
        ):
            execute_suite(
                suite,
                mode="live",
                profile_name="openai_gpt_5_4",
                case_timeout_seconds=120,
            )

        self.assertEqual(captured, [300.0])

    def test_live_case_timeout_uses_global_timeout_when_larger_than_case_timeout(self) -> None:
        case = load_case_spec(
            Path("evals/cases/subagent_task_progress/subagent_background_task_acceptance_cn.toml")
        )
        suite = EvalSuiteSpec(
            suite_id="subagent_task_progress",
            grader_id="subagent_task_progress",
            description="probe",
            default_mode="live",
            scripted_supported=True,
            required_dependencies=["provider", "subagent"],
            baseline_policy="latest_passed_auto",
            case_files=[],
            cases=[case],
            suite_fingerprint="suite123",
        )
        captured: list[float | None] = []

        def _fake_execute_case_live_with_timeout(case_arg, **kwargs):  # noqa: ANN001
            del case_arg
            captured.append(kwargs.get("case_timeout_seconds"))
            return EvalCaseObservation(case_id=case.case_id, family=case.family)

        with patch(
            "marten_runtime.evals.executor._execute_case_live_with_timeout",
            side_effect=_fake_execute_case_live_with_timeout,
        ), patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "test-key", "MINIMAX_API_KEY": "test-key"},
            clear=False,
        ):
            execute_suite(
                suite,
                mode="live",
                profile_name="openai_gpt_5_4",
                case_timeout_seconds=120,
            )

        self.assertEqual(captured, [120.0])


    def test_live_case_timeout_zero_disables_parent_case_timeout_even_when_case_declares_timeout(self) -> None:
        case = load_case_spec(
            Path("evals/cases/subagent_task_progress/subagent_external_mcp_completion_cn.toml")
        )
        suite = EvalSuiteSpec(
            suite_id="subagent_external_mcp_completion",
            grader_id="subagent_task_progress",
            description="probe",
            default_mode="live",
            scripted_supported=True,
            required_dependencies=["provider", "subagent", "mcp"],
            baseline_policy="latest_passed_auto",
            case_files=[],
            cases=[case],
            suite_fingerprint="suite123",
        )
        captured: list[float | None] = []

        def _fake_execute_case_live_with_timeout(case_arg, **kwargs):  # noqa: ANN001
            del case_arg
            captured.append(kwargs.get("case_timeout_seconds"))
            return EvalCaseObservation(case_id=case.case_id, family=case.family)

        with patch(
            "marten_runtime.evals.executor._execute_case_live_with_timeout",
            side_effect=_fake_execute_case_live_with_timeout,
        ), patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "test-key", "MINIMAX_API_KEY": "test-key"},
            clear=False,
        ):
            execute_suite(
                suite,
                mode="live",
                profile_name="openai_gpt_5_4",
                case_timeout_seconds=0,
            )

        self.assertEqual(captured, [None])

    def test_execute_suite_live_blocked_diagnostics_use_effective_case_timeout(self) -> None:
        case = load_case_spec(
            Path("evals/cases/subagent_task_progress/subagent_external_mcp_completion_cn.toml")
        )
        suite = EvalSuiteSpec(
            suite_id="subagent_external_mcp_completion",
            grader_id="subagent_task_progress",
            description="probe",
            default_mode="live",
            scripted_supported=True,
            required_dependencies=["provider", "subagent", "mcp"],
            baseline_policy="latest_passed_auto",
            case_files=[],
            cases=[case],
            suite_fingerprint="suite123",
        )

        with patch(
            "marten_runtime.evals.executor._execute_case_live_with_timeout",
            side_effect=TimeoutError("eval case timed out: subagent_external_mcp_completion_cn"),
        ), patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "test-key", "MINIMAX_API_KEY": "test-key"},
            clear=False,
        ):
            _summary, observations = execute_suite(
                suite,
                mode="live",
                profile_name="openai_gpt_5_4",
                case_timeout_seconds=120,
            )

        self.assertEqual(observations[0].diagnostics_json["case_timeout_seconds"], 300.0)

    def test_execute_case_live_with_timeout_raises_when_case_hangs(self) -> None:
        case = load_case_spec(Path("evals/cases/main_chain_core/direct_answer_cn.toml"))

        def _hang(*args, **kwargs):  # noqa: ANN001
            del args, kwargs
            import time
            time.sleep(5)
            return EvalCaseObservation(case_id=case.case_id, family=case.family)

        with patch("marten_runtime.evals.executor._execute_case_live", side_effect=_hang):
            with self.assertRaises(TimeoutError) as ctx:
                _execute_case_live_with_timeout(
                    case,
                    source_repo_root=REPO_ROOT,
                    include_mcp=False,
                    profile_name="openai_gpt_5_4",
                    case_timeout_seconds=0.05,
                )

        self.assertIn(case.case_id, str(ctx.exception))

    def test_execute_case_live_with_timeout_reads_queue_result_before_join_timeout(self) -> None:
        case = load_case_spec(Path("evals/cases/main_chain_core/direct_answer_cn.toml"))
        observation = EvalCaseObservation(case_id=case.case_id, family=case.family, final_text="ok")

        class FakeQueue:
            def __init__(self, *args, **kwargs):
                del args, kwargs
                self._items: list[object] = []

            def put(self, item):  # noqa: ANN001
                self._items.append(item)

            def get_nowait(self):
                if not self._items:
                    raise queue.Empty
                return self._items.pop(0)

        class FakeProcess:
            exitcode = None

            def __init__(self, *, target, kwargs, daemon):  # noqa: ANN001
                del daemon
                self._target = target
                self._kwargs = kwargs
                self.started = False

            def start(self):
                self.started = True
                self._target(**self._kwargs)

            def join(self, timeout=None):  # noqa: ANN001
                del timeout
                self.started = False

            def is_alive(self):
                return self.started

            def terminate(self):
                raise AssertionError("successful queued result must be read before terminate")

            def kill(self):
                raise AssertionError("successful queued result must be read before kill")

        class FakeContext:
            def Queue(self, maxsize=0):  # noqa: N802
                del maxsize
                return FakeQueue()

            def Process(self, *, target, kwargs, daemon):  # noqa: N802, ANN001
                return FakeProcess(target=target, kwargs=kwargs, daemon=daemon)

        with patch("marten_runtime.evals.executor.multiprocessing.get_context", return_value=FakeContext()), patch(
            "marten_runtime.evals.executor._execute_case_live",
            return_value=observation,
        ):
            result = _execute_case_live_with_timeout(
                case,
                source_repo_root=REPO_ROOT,
                include_mcp=False,
                profile_name="openai_gpt_5_4",
                case_timeout_seconds=0.05,
            )

        self.assertEqual(result.final_text, "ok")

    def test_execute_case_live_with_timeout_waits_for_result_after_process_exit(self) -> None:
        case = load_case_spec(Path("evals/cases/main_chain_core/direct_answer_cn.toml"))
        observation = EvalCaseObservation(case_id=case.case_id, family=case.family, final_text="ok")

        class DelayedQueue:
            def __init__(self, *args, **kwargs):
                del args, kwargs
                self._items: list[object] = []
                self.nowait_calls = 0

            def put(self, item):  # noqa: ANN001
                self._items.append(item)

            def get_nowait(self):
                self.nowait_calls += 1
                raise queue.Empty

            def get(self, timeout=None):  # noqa: ANN001
                del timeout
                if not self._items:
                    raise queue.Empty
                return self._items.pop(0)

        class ExitedProcess:
            exitcode = 0

            def __init__(self, *, target, kwargs, daemon):  # noqa: ANN001
                del daemon
                self._target = target
                self._kwargs = kwargs

            def start(self):
                self._target(**self._kwargs)

            def join(self, timeout=None):  # noqa: ANN001
                del timeout

            def is_alive(self):
                return False

            def terminate(self):
                raise AssertionError("exited process must not be terminated")

            def kill(self):
                raise AssertionError("exited process must not be killed")

        class FakeContext:
            def Queue(self, maxsize=0):  # noqa: N802
                del maxsize
                return DelayedQueue()

            def Process(self, *, target, kwargs, daemon):  # noqa: N802, ANN001
                return ExitedProcess(target=target, kwargs=kwargs, daemon=daemon)

        with patch("marten_runtime.evals.executor.multiprocessing.get_context", return_value=FakeContext()), patch(
            "marten_runtime.evals.executor._execute_case_live",
            return_value=observation,
        ):
            result = _execute_case_live_with_timeout(
                case,
                source_repo_root=REPO_ROOT,
                include_mcp=False,
                profile_name="openai_gpt_5_4",
                case_timeout_seconds=0.05,
            )

        self.assertEqual(result.final_text, "ok")

    def test_execute_case_live_with_timeout_terminates_child_after_reading_result(self) -> None:
        case = load_case_spec(Path("evals/cases/main_chain_core/direct_answer_cn.toml"))
        observation = EvalCaseObservation(case_id=case.case_id, family=case.family, final_text="ok")
        actions: list[str] = []

        class FakeQueue:
            def __init__(self, *args, **kwargs):
                del args, kwargs
                self._items: list[object] = []

            def put(self, item):  # noqa: ANN001
                self._items.append(item)

            def get_nowait(self):
                if not self._items:
                    raise queue.Empty
                return self._items.pop(0)

        class LingeringProcess:
            exitcode = None

            def __init__(self, *, target, kwargs, daemon):  # noqa: ANN001
                del daemon
                self._target = target
                self._kwargs = kwargs
                self._alive = True

            def start(self):
                self._target(**self._kwargs)

            def join(self, timeout=None):  # noqa: ANN001
                del timeout

            def is_alive(self):
                return self._alive

            def terminate(self):
                actions.append("terminate")
                self._alive = False

            def kill(self):
                actions.append("kill")
                self._alive = False

        class FakeContext:
            def Queue(self, maxsize=0):  # noqa: N802
                del maxsize
                return FakeQueue()

            def Process(self, *, target, kwargs, daemon):  # noqa: N802, ANN001
                return LingeringProcess(target=target, kwargs=kwargs, daemon=daemon)

        with patch("marten_runtime.evals.executor.multiprocessing.get_context", return_value=FakeContext()), patch(
            "marten_runtime.evals.executor._execute_case_live",
            return_value=observation,
        ):
            result = _execute_case_live_with_timeout(
                case,
                source_repo_root=REPO_ROOT,
                include_mcp=False,
                profile_name="openai_gpt_5_4",
                case_timeout_seconds=0.05,
            )

        self.assertEqual(result.final_text, "ok")
        self.assertEqual(actions, ["terminate"])


    def test_execute_suite_live_turns_case_timeout_into_blocked_observation(self) -> None:
        case = load_case_spec(Path("evals/cases/main_chain_core/direct_answer_cn.toml"))
        suite = EvalSuiteSpec(
            suite_id="main_chain_core",
            description="probe",
            default_mode="live",
            scripted_supported=True,
            required_dependencies=["provider"],
            baseline_policy="latest_passed_auto",
            case_files=[],
            cases=[case],
            suite_fingerprint="suite123",
        )
        progress: list[str] = []

        with patch(
            "marten_runtime.evals.executor._execute_case_live_with_timeout",
            side_effect=TimeoutError("eval case timed out: direct_answer_cn"),
        ), patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "test-key", "MINIMAX_API_KEY": "test-key"},
            clear=False,
        ):
            _summary, observations = execute_suite(
                suite,
                mode="live",
                profile_name="openai_gpt_5_4",
                case_timeout_seconds=1,
                progress_printer=progress.append,
            )

        self.assertEqual(observations[0].blocked_reason, "eval case timed out: direct_answer_cn")
        self.assertEqual(observations[0].error_code, "EVAL_CASE_TIMEOUT")
        self.assertTrue(any("case_start case_id=direct_answer_cn" in item for item in progress))
        self.assertTrue(any("case_done case_id=direct_answer_cn status=blocked" in item for item in progress))

    def test_execute_suite_live_turns_case_exception_into_blocked_observation(self) -> None:
        case = load_case_spec(Path("evals/cases/main_chain_core/direct_answer_cn.toml"))
        suite = EvalSuiteSpec(
            suite_id="main_chain_core",
            description="probe",
            default_mode="live",
            scripted_supported=True,
            required_dependencies=["provider"],
            baseline_policy="latest_passed_auto",
            case_files=[],
            cases=[case],
            suite_fingerprint="suite123",
        )
        progress: list[str] = []

        with patch(
            "marten_runtime.evals.executor._execute_case_live_with_timeout",
            side_effect=RuntimeError("provider exploded"),
        ), patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "test-key", "MINIMAX_API_KEY": "test-key"},
            clear=False,
        ):
            _summary, observations = execute_suite(
                suite,
                mode="live",
                profile_name="openai_gpt_5_4",
                case_timeout_seconds=1,
                progress_printer=progress.append,
            )

        self.assertIn("eval case failed: direct_answer_cn: RuntimeError: provider exploded", observations[0].blocked_reason or "")
        self.assertEqual(observations[0].error_code, "EVAL_CASE_ERROR")
        self.assertEqual(observations[0].diagnostics_json["exception_type"], "RuntimeError")
        self.assertTrue(any("case_done case_id=direct_answer_cn status=blocked" in item for item in progress))

    def test_should_include_live_mcp_scaffold_only_when_suite_declares_mcp_dependency(self) -> None:
        with TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            self.assertFalse(_should_include_live_mcp_scaffold(repo_root, include_mcp=False))
            (repo_root / "mcps.example.json").write_text("{}", encoding="utf-8")
            (repo_root / "mcps.json").write_text("{}", encoding="utf-8")
            self.assertFalse(_should_include_live_mcp_scaffold(repo_root, include_mcp=False))
            self.assertTrue(_should_include_live_mcp_scaffold(repo_root, include_mcp=True))


if __name__ == "__main__":
    unittest.main()
