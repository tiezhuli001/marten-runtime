import unittest

from marten_runtime.runtime.finalization_contract_prompt import (
    CurrentSessionIdentityClaimDraft,
    FinalizationContractDraft,
    LiveRuntimeContextClaimDraft,
    LiveTimeClaimDraft,
    MemoryMutationClaimDraft,
    RuntimeNumericClaimDraft,
    SessionSwitchClaimDraft,
    SpawnSubagentAcceptanceClaimDraft,
)
from marten_runtime.runtime.llm_client import ToolExchange, ToolFollowupFragment
from marten_runtime.runtime.recovery_flow import (
    _FINALIZATION_CONTRACT_RULES,
    _FINALIZATION_CONTRACT_SPECS,
    _apply_finalization_draft_to_evidence_ledger,
    _evidence_text_is_covered,
    _resolve_finalization_evidence_ledger,
    assess_finalization_text,
    assess_finalization_text_with_details,
    is_generic_tool_failure_text,
    recover_successful_tool_followup_text,
    recover_successful_tool_followup_text_with_meta,
    recover_tool_result_text,
)
from marten_runtime.runtime.tool_followup_support import build_finalization_evidence_ledger


def _time_history() -> list[ToolExchange]:
    return [
        ToolExchange(
            tool_name="time",
            tool_payload={"timezone": "Asia/Shanghai"},
            tool_result={"ok": True, "iso_time": "2026-05-03T21:37:00+08:00"},
            recovery_fragment=ToolFollowupFragment(
                text="现在是北京时间 2026年5月3日 21:37:00。",
                source="tool_result",
                tool_name="time",
            ),
        )
    ]


def _runtime_history() -> list[ToolExchange]:
    return [
        ToolExchange(
            tool_name="runtime",
            tool_payload={"action": "context_status"},
            tool_result={
                "ok": True,
                "action": "context_status",
                "next_request_estimate": {
                    "input_tokens_estimate": 3000,
                    "effective_window_tokens": 184000,
                    "context_window_tokens": 200000,
                },
                "usage_percent": 2,
                "replay_user_turns": 8,
                "recent_tool_outcome_summary_limit": 3,
                "compaction_status": "none",
            },
            recovery_fragment=ToolFollowupFragment(
                text=(
                    "当前上下文使用详情\n"
                    "- 当前会话下一次请求预计带入 3000 tokens（约 2% / 184000）。\n"
                    "- 有效窗口：184000 tokens（原始窗口 200000）。\n"
                    "- 压缩状态：稳定。"
                ),
                source="tool_result",
                tool_name="runtime",
            ),
        )
    ]


def _time_history_without_iso() -> list[ToolExchange]:
    return [
        ToolExchange(
            tool_name="time",
            tool_payload={"timezone": "Asia/Shanghai"},
            tool_result={"ok": True},
            recovery_fragment=ToolFollowupFragment(
                text="现在是北京时间 2026年5月3日 21:37:00。",
                source="tool_result",
                tool_name="time",
            ),
        )
    ]


def _runtime_history_fragment_only() -> list[ToolExchange]:
    return [
        ToolExchange(
            tool_name="runtime",
            tool_payload={"action": "context_status"},
            tool_result={
                "ok": True,
                "action": "context_status",
                "compaction_status": "none",
            },
            recovery_fragment=ToolFollowupFragment(
                text=(
                    "当前上下文使用详情\n"
                    "- 当前会话下一次请求预计带入 3000 tokens（约 2% / 184000）。\n"
                    "- 有效窗口：184000 tokens（原始窗口 200000）。\n"
                    "- 压缩状态：稳定。"
                ),
                source="tool_result",
                tool_name="runtime",
            ),
        )
    ]


def _memory_write_history() -> list[ToolExchange]:
    return [
        ToolExchange(
            tool_name="memory",
            tool_payload={
                "action": "replace",
                "intent": "durable_write",
                "scope": "global",
                "section": "preferences",
                "type": "preference",
                "content": "以后始终用中文回复",
            },
            tool_result={"ok": True},
        )
    ]


def _memory_delete_history() -> list[ToolExchange]:
    return [
        ToolExchange(
            tool_name="memory",
            tool_payload={
                "action": "delete",
                "intent": "durable_delete",
                "scope": "global",
                "section": "preferences",
                "type": "preference",
                "content": "以后始终用中文回复",
            },
            tool_result={"ok": True},
        )
    ]


def _session_show_history() -> list[ToolExchange]:
    return [
        ToolExchange(
            tool_name="session",
            tool_payload={"action": "show"},
            tool_result={
                "ok": True,
                "action": "show",
                "session": {"session_id": "sess_current123"},
            },
        )
    ]


def _session_new_history() -> list[ToolExchange]:
    return [
        ToolExchange(
            tool_name="session",
            tool_payload={"action": "new"},
            tool_result={
                "ok": True,
                "action": "new",
                "transition": {
                    "binding_changed": True,
                    "mode": "switched",
                    "target_session_id": "sess_new123",
                },
                "session": {"session_id": "sess_new123"},
            },
        )
    ]


def _spawn_history(queue_state: str = "queued") -> list[ToolExchange]:
    return [
        ToolExchange(
            tool_name="spawn_subagent",
            tool_payload={"notify_on_finish": True},
            tool_result={
                "ok": True,
                "status": "accepted",
                "queue_state": queue_state,
            },
        )
    ]


def _mcp_readme_history() -> list[ToolExchange]:
    return [
        ToolExchange(
            tool_name="mcp",
            tool_payload={"action": "list", "query": "github repository file content/readme tools"},
            tool_result={
                "ok": True,
                "action": "list",
                "servers": [
                    {"server_id": "github", "tool_count": 38, "state": "discovered"},
                    {"server_id": "github_trending", "tool_count": 1, "state": "configured"},
                ],
            },
        ),
        ToolExchange(
            tool_name="mcp",
            tool_payload={
                "action": "call",
                "server_id": "github",
                "tool_name": "get_file_contents",
                "arguments": {
                    "owner": "tiezhuli001",
                    "repo": "marten-runtime",
                    "path": "README.md",
                },
            },
            tool_result={
                "ok": True,
                "action": "call",
                "server_id": "github",
                "tool_name": "get_file_contents",
                "arguments": {
                    "owner": "tiezhuli001",
                    "repo": "marten-runtime",
                    "path": "README.md",
                },
                "result_text": "successfully downloaded text file (SHA: d8f224f84cbda99c2ab3aeb2cc6abde4abccca03)",
            },
        ),
    ]


def _mcp_readme_history_top_level_payload() -> list[ToolExchange]:
    return [
        ToolExchange(
            tool_name="mcp",
            tool_payload={"action": "list"},
            tool_result={
                "ok": True,
                "action": "list",
                "servers": [
                    {"server_id": "github", "tool_count": 38, "state": "discovered"},
                    {"server_id": "github_trending", "tool_count": 1, "state": "configured"},
                ],
            },
        ),
        ToolExchange(
            tool_name="mcp",
            tool_payload={
                "action": "call",
                "server_id": "github",
                "tool_name": "get_file_contents",
                "owner": "tiezhuli001",
                "repo": "marten-runtime",
                "path": "README.md",
            },
            tool_result={
                "ok": True,
                "action": "call",
                "server_id": "github",
                "tool_name": "get_file_contents",
                "result_text": "successfully downloaded text file (SHA: d8f224f84cbda99c2ab3aeb2cc6abde4abccca03)",
            },
        ),
    ]


def _mcp_commit_history() -> list[ToolExchange]:
    return [
        ToolExchange(
            tool_name="mcp",
            tool_payload={"action": "list", "query": "GitHub repository commit history tools"},
            tool_result={
                "ok": True,
                "action": "list",
                "servers": [
                    {"server_id": "github", "tool_count": 38, "state": "discovered"},
                    {"server_id": "github_trending", "tool_count": 1, "state": "configured"},
                ],
            },
        ),
        ToolExchange(
            tool_name="mcp",
            tool_payload={
                "action": "call",
                "server_id": "github",
                "tool_name": "list_commits",
                "arguments": {
                    "owner": "tiezhuli001",
                    "repo": "marten-runtime",
                    "perPage": 1,
                },
            },
            tool_result={
                "ok": True,
                "action": "call",
                "server_id": "github",
                "tool_name": "list_commits",
                "arguments": {
                    "owner": "tiezhuli001",
                    "repo": "marten-runtime",
                    "perPage": 1,
                },
                "result_text": (
                    '[{"sha":"00d03bbcee9b09a6ddaa22074d28b669939d107e",'
                    '"commit":{"message":"docs: simplify doc surface and align provider baseline (#16)",'
                    '"author":{"date":"2026-04-29T03:46:24Z"}}}]'
                ),
            },
        ),
    ]


def _mcp_repo_tree_history() -> list[ToolExchange]:
    return [
        ToolExchange(
            tool_name="mcp",
            tool_payload={"action": "list", "query": "github repository tools for browsing tree and files"},
            tool_result={
                "ok": True,
                "action": "list",
                "servers": [
                    {"server_id": "github", "tool_count": 38, "state": "discovered"},
                    {"server_id": "github_trending", "tool_count": 1, "state": "configured"},
                ],
            },
        ),
        ToolExchange(
            tool_name="mcp",
            tool_payload={
                "action": "call",
                "server_id": "github",
                "tool_name": "get_file_contents",
                "owner": "tiezhuli001",
                "repo": "marten-runtime",
                "path": "",
                "arguments": {
                    "owner": "tiezhuli001",
                    "repo": "marten-runtime",
                    "path": "",
                },
            },
            tool_result={
                "ok": True,
                "action": "call",
                "server_id": "github",
                "tool_name": "get_file_contents",
                "result_text": (
                    '[{"type":"dir","name":"apps","path":"apps"},'
                    '{"type":"dir","name":"config","path":"config"},'
                    '{"type":"dir","name":"docs","path":"docs"},'
                    '{"type":"dir","name":"src","path":"src"},'
                    '{"type":"dir","name":"tests","path":"tests"}]'
                ),
            },
        ),
    ]


class RecoveryFlowTests(unittest.TestCase):
    def test_finalization_contract_specs_are_registered_declaratively(self) -> None:
        self.assertEqual(
            [spec.contract_id for spec in _FINALIZATION_CONTRACT_SPECS],
            [rule.contract_id for rule in _FINALIZATION_CONTRACT_RULES],
        )
        self.assertTrue(all(spec.claim_getter is not None for spec in _FINALIZATION_CONTRACT_SPECS))
        self.assertTrue(
            all(spec.history_confirmer is not None for spec in _FINALIZATION_CONTRACT_SPECS)
        )

    def test_finalization_contract_registry_order(self) -> None:
        self.assertEqual(
            [rule.contract_id for rule in _FINALIZATION_CONTRACT_RULES],
            [
                "session_switch",
                "current_session_identity",
                "memory_write",
                "memory_delete",
                "live_time",
                "live_runtime_context",
                "spawn_subagent_acceptance",
            ],
        )

    def test_free_text_claims_stay_in_llm_path_without_structured_contract(self) -> None:
        cases = (
            ("Current time is 21:37.", "what is the time now?"),
            ("Current context status is stable.", "what is the current context status?"),
            ("Current session id: sess_demo123", "what is my session id?"),
            ("Saved to memory.", "save that to memory."),
            ("Switched to a new session sess_demo123.", "create another session."),
        )
        for final_text, user_message in cases:
            with self.subTest(final_text=final_text, user_message=user_message):
                self.assertEqual(
                    assess_finalization_text([], final_text, user_message=user_message),
                    "accepted",
                )

    def test_assess_finalization_accepts_grounded_mcp_readme_synthesis(self) -> None:
        details = assess_finalization_text_with_details(
            _mcp_readme_history(),
            "已查看 `tiezhuli001/marten-runtime` 默认分支的 `README.md`，README 结构包含快速开始、运行、测试和文档。",
            user_message="梳理 README 结构",
            model_request_count=4,
        )

        self.assertEqual(details.assessment, "accepted")
        self.assertEqual(details.missing_evidence_items, ())

    def test_assess_finalization_accepts_grounded_mcp_readme_synthesis_with_top_level_payload(
        self,
    ) -> None:
        details = assess_finalization_text_with_details(
            _mcp_readme_history_top_level_payload(),
            "已检查 `tiezhuli001/marten-runtime` 的 `README.md`，README 结构包含快速开始、运行、测试和文档。",
            user_message="梳理 README 结构",
            model_request_count=4,
        )

        self.assertEqual(details.assessment, "accepted")
        self.assertEqual(details.missing_evidence_items, ())

    def test_assess_finalization_accepts_grounded_mcp_readme_synthesis_with_path_stem(
        self,
    ) -> None:
        details = assess_finalization_text_with_details(
            _mcp_readme_history_top_level_payload(),
            "README 结构包含快速开始、运行、测试和文档，整体偏工程运行手册风格。",
            user_message="梳理 README 结构",
            model_request_count=4,
        )

        self.assertEqual(details.assessment, "accepted")
        self.assertEqual(details.missing_evidence_items, ())

    def test_assess_finalization_accepts_grounded_mcp_commit_synthesis(self) -> None:
        details = assess_finalization_text_with_details(
            _mcp_commit_history(),
            (
                "tiezhuli001/marten-runtime 最新提交 sha=`00d03bbcee9b09a6ddaa22074d28b669939d107e`，"
                "原始时间 `2026-04-29T03:46:24Z`，"
                "提交说明 `docs: simplify doc surface and align provider baseline (#16)`。"
            ),
            user_message="查看当前任务所指仓库的最近提交信息，整理出最新一次提交的 sha、时间、作者和提交说明。",
            model_request_count=4,
        )

        self.assertEqual(details.assessment, "accepted")
        self.assertEqual(details.missing_evidence_items, ())

    def test_assess_finalization_accepts_grounded_mcp_repo_tree_synthesis(self) -> None:
        details = assess_finalization_text_with_details(
            _mcp_repo_tree_history(),
            "仓库顶层结构包含 apps、config、docs、src 和 tests，整体是一个带配置、源码、测试与文档分层的 runtime 项目。",
            user_message="梳理仓库结构",
            model_request_count=4,
        )

        self.assertEqual(details.assessment, "accepted")
        self.assertEqual(details.missing_evidence_items, ())

    def test_enforced_model_finalization_requires_structured_contract(self) -> None:
        self.assertEqual(
            assess_finalization_text(
                [],
                "Current time is 21:37.",
                user_message="what is the time now?",
                enforce_structured_contract=True,
            ),
            "unrecoverable",
        )

    def test_enforced_model_finalization_rejects_plain_continuation_without_structured_contract(
        self,
    ) -> None:
        cases = (
            (
                "已继续跟进部署告警排查任务。",
                "继续跟进上一轮那个部署告警排查任务。",
            ),
            (
                "已在旧会话继续。",
                "继续旧会话。",
            ),
            (
                "压缩后继续完成当前任务。",
                "在压缩后的上下文里继续执行。",
            ),
            (
                "当前偏好：以后始终用中文回复。",
                "读取刚才记住的偏好。",
            ),
            (
                "我记住了：以后始终用中文回复。",
                "继续当前任务，并说明你记住了什么。",
            ),
            (
                "周报默认先给结论后给细节。",
                "把我刚才设定的周报顺序完整复述一遍，明确先后顺序。",
            ),
            (
                "子任务已梳理仓库结构，结论是当前可用 MCP 服务共 0 个。",
                "子任务完成了吗？直接给我一句中文摘要，明确它梳理的对象和结论。",
            ),
            (
                "以后日报先给风险，再给结论。",
                "现在日报该怎么组织？",
            ),
            (
                "最近提交主要集中在评测和报告。",
                "直接告诉我你吸收后的结论，明确最近提交主要在改什么。",
            ),
        )
        for final_text, user_message in cases:
            with self.subTest(final_text=final_text, user_message=user_message):
                self.assertEqual(
                    assess_finalization_text(
                        [],
                        final_text,
                        user_message=user_message,
                        enforce_structured_contract=True,
                    ),
                    "unrecoverable",
                )

    def test_enforced_model_finalization_allows_session_bound_continuation_without_structured_contract(
        self,
    ) -> None:
        self.assertEqual(
            assess_finalization_text(
                _session_new_history(),
                "已切换到新会话（sess_new123）。继续“部署告警排查”任务。请补充最小必要信息。",
                user_message="在新会话里继续刚才那个部署告警排查任务。",
                finalization_contract_draft=FinalizationContractDraft(
                    session_switch=SessionSwitchClaimDraft(
                        kind="new",
                        session_id="sess_new123",
                    )
                ),
                enforce_structured_contract=True,
            ),
            "accepted",
        )

    def test_enforced_model_finalization_rejects_session_bound_continuation_without_structured_contract(
        self,
    ) -> None:
        self.assertEqual(
            assess_finalization_text(
                _session_new_history(),
                "已切换到新会话（sess_new123）。继续“部署告警排查”任务。请补充最小必要信息。",
                user_message="在新会话里继续刚才那个部署告警排查任务。",
                enforce_structured_contract=True,
            ),
            "retryable_degraded",
        )

    def test_structured_live_time_claim_requires_matching_time_history(self) -> None:
        draft = FinalizationContractDraft(
            live_time=LiveTimeClaimDraft(
                facets=["time", "date"],
                year=2026,
                month=5,
                day=3,
                hour=21,
                minute=37,
            )
        )
        self.assertEqual(
            assess_finalization_text(
                _time_history(),
                "现在是北京时间 2026-05-03 21:37。",
                finalization_contract_draft=draft,
                enforce_structured_contract=True,
            ),
            "accepted",
        )
        wrong = draft.model_copy(
            update={
                "live_time": LiveTimeClaimDraft(
                    facets=["time"],
                    hour=21,
                    minute=37,
                    second=59,
                    requires_second_precision=True,
                )
            }
        )
        self.assertEqual(
            assess_finalization_text(
                _time_history(),
                "21:37:59",
                finalization_contract_draft=wrong,
                enforce_structured_contract=True,
            ),
            "retryable_degraded",
        )

    def test_structured_live_time_claim_requires_structured_time_evidence(self) -> None:
        draft = FinalizationContractDraft(
            live_time=LiveTimeClaimDraft(
                facets=["time", "date"],
                year=2026,
                month=5,
                day=3,
                hour=21,
                minute=37,
            )
        )

        self.assertEqual(
            assess_finalization_text(
                _time_history_without_iso(),
                "现在是北京时间 2026-05-03 21:37。",
                finalization_contract_draft=draft,
                enforce_structured_contract=True,
            ),
            "retryable_degraded",
        )

    def test_structured_runtime_claim_binds_each_field_to_observed_value(self) -> None:
        matching = FinalizationContractDraft(
            live_runtime_context=LiveRuntimeContextClaimDraft(
                numeric_claims=[
                    RuntimeNumericClaimDraft(kind="estimated_usage", value=3000),
                    RuntimeNumericClaimDraft(kind="effective_window", value=184000),
                    RuntimeNumericClaimDraft(kind="remaining_effective", value=181000),
                ],
                status="稳定",
            )
        )
        self.assertEqual(
            assess_finalization_text(
                _runtime_history(),
                "当前上下文使用详情如上。",
                finalization_contract_draft=matching,
                enforce_structured_contract=True,
            ),
            "accepted",
        )
        mismatched = FinalizationContractDraft(
            live_runtime_context=LiveRuntimeContextClaimDraft(
                numeric_claims=[
                    RuntimeNumericClaimDraft(kind="effective_window", value=3000),
                ]
            )
        )
        self.assertEqual(
            assess_finalization_text(
                _runtime_history(),
                "有效窗口是 3000 tokens。",
                finalization_contract_draft=mismatched,
                enforce_structured_contract=True,
            ),
            "retryable_degraded",
        )

    def test_structured_runtime_claim_requires_structured_runtime_evidence(self) -> None:
        draft = FinalizationContractDraft(
            live_runtime_context=LiveRuntimeContextClaimDraft(
                numeric_claims=[
                    RuntimeNumericClaimDraft(kind="estimated_usage", value=3000),
                    RuntimeNumericClaimDraft(kind="effective_window", value=184000),
                ],
                status="稳定",
            )
        )

        self.assertEqual(
            assess_finalization_text(
                _runtime_history_fragment_only(),
                "当前上下文使用详情如上。",
                finalization_contract_draft=draft,
                enforce_structured_contract=True,
            ),
            "retryable_degraded",
        )

    def test_structured_memory_mutation_claims_bind_to_confirmed_content(self) -> None:
        write_draft = FinalizationContractDraft(
            memory_write=MemoryMutationClaimDraft(content="以后始终用中文回复")
        )
        delete_draft = FinalizationContractDraft(
            memory_delete=MemoryMutationClaimDraft(content="以后始终用中文回复")
        )
        self.assertEqual(
            assess_finalization_text(
                _memory_write_history(),
                "记住了：以后始终用中文回复。",
                finalization_contract_draft=write_draft,
                enforce_structured_contract=True,
            ),
            "accepted",
        )
        self.assertEqual(
            assess_finalization_text(
                _memory_delete_history(),
                "已删除该偏好：以后始终用中文回复。",
                finalization_contract_draft=delete_draft,
                enforce_structured_contract=True,
            ),
            "accepted",
        )
        mismatched = FinalizationContractDraft(
            memory_write=MemoryMutationClaimDraft(content="以后始终用英文回复")
        )
        self.assertEqual(
            assess_finalization_text(
                _memory_write_history(),
                "记住了：以后始终用英文回复。",
                finalization_contract_draft=mismatched,
                enforce_structured_contract=True,
            ),
            "retryable_degraded",
        )
        truncated = FinalizationContractDraft(
            memory_write=MemoryMutationClaimDraft(content="用中文")
        )
        self.assertEqual(
            assess_finalization_text(
                _memory_write_history(),
                "记住了：用中文。",
                finalization_contract_draft=truncated,
                enforce_structured_contract=True,
            ),
            "retryable_degraded",
        )

    def test_structured_session_claims_require_matching_tool_results(self) -> None:
        current_session = FinalizationContractDraft(
            current_session_identity=CurrentSessionIdentityClaimDraft(
                session_id="sess_current123"
            )
        )
        self.assertEqual(
            assess_finalization_text(
                _session_show_history(),
                "Current session id: sess_current123",
                finalization_contract_draft=current_session,
                enforce_structured_contract=True,
            ),
            "accepted",
        )
        session_switch = FinalizationContractDraft(
            session_switch=SessionSwitchClaimDraft(
                kind="new",
                session_id="sess_new123",
            )
        )
        self.assertEqual(
            assess_finalization_text(
                _session_new_history(),
                "Switched to a new session sess_new123.",
                finalization_contract_draft=session_switch,
                enforce_structured_contract=True,
            ),
            "accepted",
        )

    def test_structured_spawn_claim_respects_queue_state(self) -> None:
        accepted = FinalizationContractDraft(
            spawn_subagent_acceptance=SpawnSubagentAcceptanceClaimDraft(
                queue_state="queued",
                notify_phrase="after_start",
            )
        )
        self.assertEqual(
            assess_finalization_text(
                _spawn_history(queue_state="queued"),
                "Queued.",
                finalization_contract_draft=accepted,
                enforce_structured_contract=True,
            ),
            "accepted",
        )
        mismatched = FinalizationContractDraft(
            spawn_subagent_acceptance=SpawnSubagentAcceptanceClaimDraft(
                queue_state="running"
            )
        )
        self.assertEqual(
            assess_finalization_text(
                _spawn_history(queue_state="queued"),
                "Running in the background.",
                finalization_contract_draft=mismatched,
                enforce_structured_contract=True,
            ),
            "retryable_degraded",
        )

    def test_apply_finalization_draft_to_evidence_ledger_updates_required_flags(self) -> None:
        history = [
            ToolExchange(
                tool_name="time",
                tool_payload={"timezone": "Asia/Shanghai"},
                tool_result={"ok": True},
                recovery_fragment=ToolFollowupFragment(
                    text="现在是北京时间 2026-04-20 12:30:00。",
                    source="tool_result",
                    tool_name="time",
                ),
            ),
            ToolExchange(
                tool_name="runtime",
                tool_payload={"action": "context_status"},
                tool_result={"ok": True},
                recovery_fragment=ToolFollowupFragment(
                    text="当前上下文使用详情：预计占用 1234/184000 tokens。",
                    source="tool_result",
                    tool_name="runtime",
                ),
            ),
            ToolExchange(
                tool_name="mcp",
                tool_payload={"action": "list"},
                tool_result={"ok": True},
                recovery_fragment=ToolFollowupFragment(
                    text="当前可用 MCP 服务共 1 个。",
                    source="tool_result",
                    tool_name="mcp",
                ),
            ),
        ]
        ledger = build_finalization_evidence_ledger(
            user_message="请严格按顺序总结这次链路，并明确说明是否发生了多次模型/工具往返。",
            tool_history=history,
            model_request_count=4,
            requires_result_coverage=False,
            requires_round_trip_report=False,
        )
        updated = _apply_finalization_draft_to_evidence_ledger(
            ledger,
            finalization_contract_draft=FinalizationContractDraft(
                requires_result_coverage=True,
                requires_round_trip_report=True,
            ),
        )
        recovered = recover_successful_tool_followup_text_with_meta(
            history,
            model_request_count=4,
            finalization_evidence_ledger=updated,
        )
        self.assertIn("现在是北京时间", recovered)
        self.assertIn("当前上下文使用详情", recovered)
        self.assertIn("当前可用 MCP 服务共 1 个", recovered)
        self.assertIn("属于多次模型/工具往返", recovered)

    def test_evidence_coverage_uses_boundary_and_ordered_anchor_matching(self) -> None:
        self.assertFalse(
            _evidence_text_is_covered(
                "time=2026-05-03T21:37:00+08:00",
                "runtime ok",
            )
        )
        self.assertFalse(
            _evidence_text_is_covered(
                "当前时间：21:37",
                "当前 runtime 状态稳定",
            )
        )
        self.assertFalse(
            _evidence_text_is_covered(
                "当前时间：21:37",
                "现在是 21:37。",
            )
        )
        self.assertFalse(
            _evidence_text_is_covered(
                "现在是北京时间 2026年5月3日 21:37",
                "现在是北京时间 2026-05-03 21:37，这轮查询已经完成。",
            )
        )
        self.assertFalse(
            _evidence_text_is_covered(
                "当前上下文使用详情：预计占用 1234/184000 tokens。",
                "当前上下文使用详情：当前估算占用 1234/184000 tokens（1%）。",
            )
        )
        self.assertTrue(
            _evidence_text_is_covered(
                "当前上下文使用详情：当前估算占用 1234/184000 tokens（1%）。",
                "当前上下文使用详情：当前估算占用 1234/184000 tokens（1%）。",
            )
        )

    def test_assessment_accepts_payload_grounded_paraphrase_via_coverage_tokens(self) -> None:
        details = assess_finalization_text_with_details(
            _time_history(),
            "现在是 21:37。",
            user_message="请告诉我现在几点了？",
            model_request_count=2,
            finalization_contract_draft=FinalizationContractDraft(),
        )

        self.assertEqual(details.assessment, "accepted")

    def test_assessment_accepts_memory_read_paraphrase_via_section_tokens(self) -> None:
        history = [
            ToolExchange(
                tool_name="memory",
                tool_payload={"action": "get"},
                tool_result={
                    "ok": True,
                    "action": "get",
                    "sections": {"tasks": ["排查部署告警"]},
                },
            )
        ]

        details = assess_finalization_text_with_details(
            history,
            "继续排查部署告警，需要补充告警来源或关键日志。",
            user_message="在新会话里继续刚才那个部署告警排查任务。",
            model_request_count=3,
            finalization_contract_draft=FinalizationContractDraft(),
        )

        self.assertEqual(details.assessment, "accepted")

    def test_assessment_accepts_mcp_repo_paraphrase_via_structured_fact_token(self) -> None:
        history = [
            ToolExchange(
                tool_name="mcp",
                tool_payload={"server_id": "github", "tool_name": "get_repo"},
                tool_result={"full_name": "octo/repo"},
                recovery_fragment=ToolFollowupFragment(
                    text="上一轮调用了 github MCP，并获得了查询结果。关键结果：full_name=octo/repo。",
                    source="tool_result",
                    tool_name="mcp",
                ),
            )
        ]

        details = assess_finalization_text_with_details(
            history,
            "查到了 octo/repo 仓库。",
            user_message="查一下这个仓库",
            model_request_count=2,
            finalization_contract_draft=FinalizationContractDraft(),
        )

        self.assertEqual(details.assessment, "accepted")

    def test_resolve_finalization_evidence_ledger_defaults_to_structural_result_coverage(
        self,
    ) -> None:
        ledger = _resolve_finalization_evidence_ledger(
            _time_history(),
            user_message="请告诉我现在几点了？",
            model_request_count=2,
            finalization_evidence_ledger=None,
            finalization_contract_draft=None,
        )

        self.assertTrue(ledger.requires_result_coverage)
        self.assertFalse(ledger.requires_round_trip_report)
        required_items = [item for item in ledger.items if item.required_for_user_request]
        self.assertEqual(len(required_items), 1)
        self.assertEqual(required_items[0].tool_name, "time")

    def test_assessment_requires_tool_result_coverage_by_default_when_history_exists(
        self,
    ) -> None:
        details = assess_finalization_text_with_details(
            _time_history(),
            "好的。",
            user_message="请告诉我现在几点了？",
            model_request_count=2,
            finalization_contract_draft=FinalizationContractDraft(),
        )

        self.assertEqual(details.assessment, "retryable_degraded")
        self.assertTrue(any("现在是北京时间" in item for item in details.missing_evidence_items))

    def test_is_generic_tool_failure_text_matches_known_failure_copy(self) -> None:
        self.assertTrue(is_generic_tool_failure_text("工具执行失败，请重试。"))
        self.assertTrue(is_generic_tool_failure_text("tool execution failed, please retry."))
        self.assertFalse(is_generic_tool_failure_text("这不是工具失败文案"))

    def test_recover_successful_tool_followup_text_prefers_safe_fragments(self) -> None:
        history = [
            ToolExchange(
                tool_name="time",
                tool_payload={"timezone": "Asia/Shanghai"},
                tool_result={"ok": True},
                recovery_fragment=ToolFollowupFragment(
                    text="现在是北京时间 2026-04-20 12:30:00。",
                    source="tool_result",
                    tool_name="time",
                ),
            ),
            ToolExchange(
                tool_name="runtime",
                tool_payload={"action": "context_status"},
                tool_result={"ok": True},
                recovery_fragment=ToolFollowupFragment(
                    text="当前上下文使用详情：预计占用 1234/184000 tokens。",
                    source="tool_result",
                    tool_name="runtime",
                ),
            ),
        ]
        recovered = recover_successful_tool_followup_text(history)
        self.assertIn("现在是北京时间", recovered)
        self.assertIn("当前上下文使用详情", recovered)
        self.assertIn("2026年5月3日 21:37", recover_tool_result_text(_time_history()))


if __name__ == "__main__":
    unittest.main()
