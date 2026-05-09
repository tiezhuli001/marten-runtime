from __future__ import annotations

from marten_runtime.evals.models import EvalCaseSpec
from marten_runtime.runtime.finalization_contract_prompt import (
    FinalizationContractDraft,
    SpawnSubagentAcceptanceClaimDraft,
    render_finalization_contract_block,
)
from marten_runtime.runtime.llm_client import LLMReply, _normalize_reply_contract_metadata
from marten_runtime.tools.builtins.time_tool import render_time_tool_text


def _contracted_final_reply(final_text: str) -> LLMReply:
    visible_text = str(final_text or "").strip()
    return LLMReply(
        final_text=f"{visible_text}\n{render_finalization_contract_block()}".strip()
    )


def _plain_final_reply(final_text: str) -> LLMReply:
    return LLMReply(final_text=str(final_text or "").strip())


def _empty_session_summary_reply() -> LLMReply:
    return _plain_final_reply("")


class ScriptedEvalLLMClient:
    def __init__(
        self,
        *,
        case_id: str,
        provider_name: str,
        model_name: str,
        context: dict[str, object] | None = None,
    ) -> None:
        self.case_id = case_id
        self.provider_name = provider_name
        self.model_name = model_name
        self.context = dict(context or {})
        self.requests = []
        self._conversation_calls = 0
        self._conversation_turns = 0
        self._subagent_child_calls = 0
        self._memory_written = False
        self._memory_replaced = False
        self._subagent_spawn_count = 0

    def complete(self, request):  # noqa: ANN001
        self.requests.append(request)
        if request.request_kind == "session_summary":
            return _normalize_reply_contract_metadata(
                request,
                _empty_session_summary_reply(),
            )
        if request.agent_id == "compaction":
            if self.case_id == "proactive_compaction_cn":
                return _normalize_reply_contract_metadata(
                    request,
                    _plain_final_reply("当前进展：长线程已压缩。"),
                )
            return _normalize_reply_contract_metadata(
                request,
                _plain_final_reply("当前进展：旧历史已经压缩。"),
            )
        if request.request_kind == "subagent":
            return _normalize_reply_contract_metadata(
                request,
                _scripted_subagent_child_reply(self, request),
            )
        if request.tool_result is not None:
            scripted = _scripted_tool_followup_reply(self, request)
            if scripted is not None:
                return _normalize_reply_contract_metadata(request, scripted)
            if self.case_id in {"memory_write_then_read_cn", "memory_replace_then_read_cn"}:
                self._memory_written = True
                return _normalize_reply_contract_metadata(
                    request,
                    _contracted_final_reply("已记住。"),
                )
            if self.case_id == "tool_followup_to_final_cn":
                return _normalize_reply_contract_metadata(
                    request,
                    _contracted_final_reply(render_time_tool_text(request.tool_result)),
                )
            return _normalize_reply_contract_metadata(
                request,
                _contracted_final_reply(str(request.tool_result)),
            )

        self._conversation_calls += 1
        if request.request_kind in {"interactive", "conversation"}:
            self._conversation_turns += 1
        message = str(request.message or "")
        scripted_memory = _scripted_memory_suite_reply(self, message)
        if scripted_memory is not None:
            return _normalize_reply_contract_metadata(request, scripted_memory)
        scripted_subagent = _scripted_subagent_suite_reply(self)
        if scripted_subagent is not None:
            return _normalize_reply_contract_metadata(request, scripted_subagent)
        return _normalize_reply_contract_metadata(
            request,
            _scripted_main_chain_reply(self, request, message),
        )


class PromptTooLongThenCompactThenFinalEvalClient:
    def __init__(self, *, provider_name: str, model_name: str, final_text: str) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.final_text = final_text
        self.requests = []
        self._calls = 0

    def complete(self, request):  # noqa: ANN001
        self.requests.append(request)
        if getattr(request, "request_kind", "") == "session_summary":
            return _normalize_reply_contract_metadata(
                request,
                _empty_session_summary_reply(),
            )
        if getattr(request, "agent_id", "") == "compaction":
            return _normalize_reply_contract_metadata(
                request,
                _plain_final_reply("当前进展：旧历史已经压缩。"),
            )
        self._calls += 1
        if self._calls == 1:
            raise RuntimeError("provider_http_error:400:prompt too long")
        return _normalize_reply_contract_metadata(
            request,
            _contracted_final_reply(self.final_text),
        )


class FixedReplyLLMClient:
    def __init__(self, *, provider_name: str, model_name: str, reply_text: str) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.reply_text = reply_text
        self.requests = []

    def complete(self, request):  # noqa: ANN001
        self.requests.append(request)
        if getattr(request, "request_kind", "") == "session_summary":
            return _normalize_reply_contract_metadata(
                request,
                _empty_session_summary_reply(),
            )
        if getattr(request, "agent_id", "") == "compaction":
            return _normalize_reply_contract_metadata(
                request,
                _plain_final_reply(self.reply_text),
            )
        return _normalize_reply_contract_metadata(
            request,
            _contracted_final_reply(self.reply_text),
        )


def configure_scripted_runtime(runtime, case: EvalCaseSpec, *, provider_name: str, model_name: str, context: dict[str, object]) -> None:  # noqa: ANN001
    llm = ScriptedEvalLLMClient(
        case_id=case.case_id,
        provider_name=provider_name,
        model_name=model_name,
        context=context,
    )
    runtime.runtime_loop.llm = llm
    for name in runtime.models_config.profiles:
        runtime.llm_client_factory.cache_client(name, llm)
    isolated_reply_text = _isolated_compaction_reply_text(case.case_id)
    if isolated_reply_text is not None:
        runtime.llm_client_factory.create_isolated = lambda profile_name: FixedReplyLLMClient(  # type: ignore[method-assign]
            provider_name=provider_name,
            model_name=model_name,
            reply_text=isolated_reply_text,
        )


def _isolated_compaction_reply_text(case_id: str) -> str | None:
    if case_id == "context_compaction_continuity_cn":
        return "当前进展：旧历史已经压缩。"
    if case_id == "proactive_compaction_cn":
        return "当前进展：长线程已压缩。"
    return None


def _scripted_tool_followup_reply(llm: ScriptedEvalLLMClient, request) -> LLMReply | None:  # noqa: ANN001
    if llm.case_id in {
        "memory_capture_preference_cn",
        "memory_delayed_recall_same_session_cn",
        "memory_delayed_recall_cross_session_cn",
        "memory_overwrite_then_recall_cn",
        "memory_long_gap_with_interference_recall_cn",
        "memory_stale_conflict_rejection_cn",
    }:
        requested_tool_name = str(request.requested_tool_name or "").strip()
        if requested_tool_name == "memory":
            if llm.case_id in {"memory_overwrite_then_recall_cn", "memory_stale_conflict_rejection_cn"}:
                llm._memory_replaced = True
            else:
                llm._memory_written = True
            if llm.case_id == "memory_capture_preference_cn":
                return _contracted_final_reply("我记住了：以后所有答复都用中文，并保持简洁。")
            return _contracted_final_reply("已记住。")
    if llm.case_id == "subagent_multi_child_progress_cn" and llm._subagent_spawn_count == 1:
        llm._subagent_spawn_count += 1
        return LLMReply(
            tool_name="spawn_subagent",
            tool_payload={
                "task": "inspect README structure",
                "label": "readme-check",
                "finalize_response": True,
            },
        )
    if llm.case_id == "subagent_multi_child_progress_cn" and llm._subagent_spawn_count == 2:
        return _contracted_final_reply(
            "已受理，两个子 agent 正在后台执行，完成后会通知你结果。",
            finalization_contract_draft=FinalizationContractDraft(
                spawn_subagent_acceptance=SpawnSubagentAcceptanceClaimDraft(
                    queue_state="running",
                    notify_phrase="after_finish",
                )
            ),
        )
    return None


def _scripted_memory_suite_reply(llm: ScriptedEvalLLMClient, message: str) -> LLMReply | None:
    if llm.case_id == "memory_capture_preference_cn":
        return LLMReply(
            tool_name="memory",
            tool_payload={
                "action": "replace",
                "intent": "durable_write",
                "source_excerpt": message,
                "section": "preferences",
                "content": "以后所有答复都用中文，并保持简洁。",
            },
        )
    if llm.case_id == "memory_delayed_recall_same_session_cn":
        if not llm._memory_written:
            return LLMReply(
                tool_name="memory",
                tool_payload={
                    "action": "replace",
                    "intent": "durable_write",
                    "source_excerpt": message,
                    "section": "preferences",
                    "content": "周报默认先给结论后给细节。",
                },
            )
        return _contracted_final_reply("你刚才设定的是：周报默认先给结论后给细节。")
    if llm.case_id == "memory_delayed_recall_cross_session_cn":
        if not llm._memory_written:
            return LLMReply(
                tool_name="memory",
                tool_payload={
                    "action": "replace",
                    "intent": "durable_write",
                    "source_excerpt": message,
                    "section": "preferences",
                    "content": "技术方案默认用中文标题。",
                },
            )
        if llm._conversation_turns == 2:
            return LLMReply(tool_name="session", tool_payload={"action": "new", "finalize_response": True})
        return _contracted_final_reply("在新会话里也保持：技术方案默认用中文标题。")
    if llm.case_id == "memory_overwrite_then_recall_cn":
        if llm._conversation_turns == 1:
            return LLMReply(
                tool_name="memory",
                tool_payload={
                    "action": "append",
                    "intent": "durable_write",
                    "source_excerpt": message,
                    "section": "preferences",
                    "content": "日报默认只给结论，不展开风险。",
                },
            )
        if llm._conversation_turns == 2:
            return LLMReply(
                tool_name="memory",
                tool_payload={
                    "action": "replace",
                    "intent": "durable_write",
                    "source_excerpt": message,
                    "section": "preferences",
                    "content": "以后日报先给风险，再给结论。",
                },
            )
        return _contracted_final_reply("现在日报应当先给风险，再给结论。")
    if llm.case_id == "memory_long_gap_with_interference_recall_cn":
        if not llm._memory_written:
            return LLMReply(
                tool_name="memory",
                tool_payload={
                    "action": "replace",
                    "intent": "durable_write",
                    "source_excerpt": message,
                    "section": "preferences",
                    "content": "日报先给风险再给结论。",
                },
            )
        if llm._conversation_turns == 2:
            return LLMReply(tool_name="time", tool_payload={"timezone": "Asia/Shanghai", "finalize_response": True})
        if llm._conversation_turns == 3:
            return _contracted_final_reply("收到")
        return _contracted_final_reply("你设定的日报顺序是：先给风险，再给结论。")
    if llm.case_id == "memory_stale_conflict_rejection_cn":
        if not llm._memory_replaced:
            return LLMReply(
                tool_name="memory",
                tool_payload={
                    "action": "replace",
                    "intent": "durable_write",
                    "source_excerpt": message,
                    "section": "preferences",
                    "content": "周报默认先结论，后细节。",
                },
            )
        return _contracted_final_reply("现在周报顺序是：先结论，后细节。")
    if llm.case_id == "memory_preference_applied_to_output_cn":
        return _contracted_final_reply("结论：本周接口联调已完成；细节：剩余文档整理中。")
    return None


def _scripted_subagent_suite_reply(llm: ScriptedEvalLLMClient) -> LLMReply | None:
    if llm.case_id == "subagent_background_task_acceptance_cn":
        llm._subagent_spawn_count += 1
        return LLMReply(
            tool_name="spawn_subagent",
            tool_payload={
                "task": "inspect repository structure",
                "label": "repo-structure",
                "finalize_response": True,
            },
        )
    if llm.case_id == "subagent_child_completion_notice_cn":
        if llm._conversation_turns == 1:
            llm._subagent_spawn_count += 1
            return LLMReply(
                tool_name="spawn_subagent",
                tool_payload={
                    "task": "inspect repository structure",
                    "label": "repo-structure",
                    "finalize_response": True,
                },
            )
        return _contracted_final_reply("子任务已完成：仓库结构已梳理。")
    if llm.case_id == "subagent_followup_uses_child_result_cn":
        if llm._conversation_turns == 1:
            llm._subagent_spawn_count += 1
            return LLMReply(
                tool_name="spawn_subagent",
                tool_payload={
                    "task": "inspect recent commits",
                    "label": "commit-check",
                    "finalize_response": True,
                },
            )
        return _contracted_final_reply("我吸收后的结论：最近提交主要集中在评测与报告。")
    if llm.case_id == "subagent_multi_child_progress_cn":
        if llm._conversation_turns == 1:
            llm._subagent_spawn_count += 1
            return LLMReply(
                tool_name="spawn_subagent",
                tool_payload={
                    "task": "inspect recent commits",
                    "label": "commit-check",
                },
            )
        return _contracted_final_reply("两个子任务都完成了：最近提交主要集中在评测与报告；README结构包含快速开始、配置和评测入口。")
    if llm.case_id == "subagent_duplicate_dispatch_penalty_cn":
        if llm._conversation_turns == 1:
            llm._subagent_spawn_count += 1
            return LLMReply(
                tool_name="spawn_subagent",
                tool_payload={
                    "task": "inspect README structure",
                    "label": "readme-check",
                    "finalize_response": True,
                },
            )
        return _contracted_final_reply("已有结果：README结构包含快速开始、配置和评测入口。")
    if llm.case_id == "subagent_simple_request_stays_main_thread_cn":
        return _contracted_final_reply("这个项目的主链路是 channel -> binding -> runtime loop -> tool -> delivery。")
    return None


def _scripted_subagent_child_reply(llm: ScriptedEvalLLMClient, request) -> LLMReply:  # noqa: ANN001
    llm._subagent_child_calls += 1
    if llm.case_id == "subagent_followup_uses_child_result_cn":
        return _contracted_final_reply("最近提交主要集中在评测与报告。")
    if llm.case_id == "subagent_multi_child_progress_cn":
        if llm._subagent_child_calls == 1:
            return _contracted_final_reply("最近提交主要集中在评测与报告。")
        return _contracted_final_reply("README结构包含快速开始、配置和评测入口。")
    if llm.case_id == "subagent_duplicate_dispatch_penalty_cn":
        return _contracted_final_reply("README结构包含快速开始、配置和评测入口。")
    return _contracted_final_reply("仓库结构已梳理，主链路围绕 channel -> binding -> runtime loop -> tool -> delivery。")


def _scripted_main_chain_reply(llm: ScriptedEvalLLMClient, request, message: str) -> LLMReply:
    if llm.case_id == "direct_answer_cn":
        if request.request_kind in {"contract_repair", "finalization_retry"}:
            return _contracted_final_reply("你好，我在。")
        return _plain_final_reply("你好，我在。")
    if llm.case_id == "context_compaction_continuity_cn":
        return _contracted_final_reply("压缩后继续完成当前任务。")
    if llm.case_id == "time_single_tool_cn":
        return LLMReply(tool_name="time", tool_payload={"timezone": "Asia/Shanghai", "finalize_response": True})
    if llm.case_id == "runtime_context_status_cn":
        return LLMReply(tool_name="runtime", tool_payload={"action": "context_status", "finalize_response": True})
    if llm.case_id == "runtime_usage_window_cn":
        return LLMReply(tool_name="runtime", tool_payload={"action": "context_status", "finalize_response": True})
    if llm.case_id == "session_catalog_cn":
        return LLMReply(tool_name="session", tool_payload={"action": "list", "finalize_response": True})
    if llm.case_id == "tool_followup_to_final_cn":
        return LLMReply(tool_name="time", tool_payload={"timezone": "Asia/Shanghai"})
    if llm.case_id == "memory_write_then_read_cn":
        if not llm._memory_written:
            return LLMReply(
                tool_name="memory",
                tool_payload={
                    "action": "append",
                    "intent": "durable_write",
                    "source_excerpt": message,
                    "section": "preferences",
                    "content": "以后始终用中文回复。",
                },
            )
        return _contracted_final_reply(_memory_reply_from_request(request))
    if llm.case_id == "memory_replace_then_read_cn":
        if not llm._memory_written:
            return LLMReply(
                tool_name="memory",
                tool_payload={
                    "action": "replace",
                    "intent": "durable_write",
                    "source_excerpt": message,
                    "section": "preferences",
                    "content": "以后回答尽量简洁。",
                },
            )
        return _contracted_final_reply(_memory_reply_from_request(request))
    if llm.case_id == "multi_turn_time_then_context_cn":
        if llm._conversation_turns == 2:
            return LLMReply(tool_name="runtime", tool_payload={"action": "context_status", "finalize_response": True})
        return LLMReply(tool_name="time", tool_payload={"timezone": "Asia/Shanghai", "finalize_response": True})
    if llm.case_id == "multi_turn_memory_reuse_cn":
        if llm._conversation_turns == 1:
            return LLMReply(
                tool_name="memory",
                tool_payload={
                    "action": "append",
                    "intent": "durable_write",
                    "source_excerpt": message,
                    "section": "preferences",
                    "content": "以后始终用中文回复。",
                },
            )
        if llm._memory_written or request.memory_text:
            return _contracted_final_reply(_memory_reply_from_request(request))
        return _contracted_final_reply("已继续。")
    if llm.case_id == "proactive_compaction_cn":
        if request.compact_summary_text:
            return _contracted_final_reply("已在压缩后的上下文里继续执行。")
        return _contracted_final_reply("已继续执行。")
    if llm.case_id == "session_new_continuity_cn":
        if llm._conversation_turns == 1:
            return LLMReply(tool_name="session", tool_payload={"action": "new", "finalize_response": True})
        return _contracted_final_reply("新会话里继续执行。")
    if llm.case_id == "session_resume_continuity_cn":
        target_session_id = str(llm.context.get("target_session_id") or "")
        if llm._conversation_turns == 1:
            return LLMReply(
                tool_name="session",
                tool_payload={"action": "resume", "session_id": target_session_id, "finalize_response": True},
            )
        marker = str(llm.context.get("target_marker") or "旧会话")
        return _contracted_final_reply(f"已在{marker}继续执行。")
    if llm.case_id == "direct_answer_followup_cn":
        return _contracted_final_reply("继续保持同一任务上下文。")
    return _contracted_final_reply("scripted eval ok")


def _memory_reply_from_request(request) -> str:  # noqa: ANN001
    memory_text = str(request.memory_text or "").strip()
    if "简洁" in memory_text:
        return "我记住了：以后回答尽量简洁。"
    if "中文" in memory_text:
        return "我记住了：以后始终用中文回复。"
    if "中文标题" in memory_text:
        return "我记住了：技术方案默认用中文标题。"
    if "先给结论后给细节" in memory_text:
        return "我记住了：周报默认先给结论后给细节。"
    if "先给风险再给结论" in memory_text:
        return "我记住了：日报先给风险再给结论。"
    return "我已经读取到当前用户记忆。"
