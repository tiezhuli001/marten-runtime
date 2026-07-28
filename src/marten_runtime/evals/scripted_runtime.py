from __future__ import annotations

import time

from marten_runtime.evals.models import EvalCaseSpec
from marten_runtime.runtime.finalization_contract_prompt import (
    FinalizationContractDraft,
    SpawnSubagentAcceptanceClaimDraft,
    render_finalization_contract_block,
)
from marten_runtime.runtime.llm_client import LLMReply, _normalize_reply_contract_metadata
from marten_runtime.runtime.tool_followup_support import build_finalization_evidence_ledger
from marten_runtime.tools.builtins.time_tool import render_time_tool_text


def _contracted_final_reply(final_text: str) -> LLMReply:
    visible_text = str(final_text or "").strip()
    return LLMReply(
        final_text=f"{visible_text}\n{render_finalization_contract_block()}".strip()
    )


def _plain_final_reply(final_text: str) -> LLMReply:
    return LLMReply(final_text=str(final_text or "").strip())


def _result_covered_final_reply(final_text: str) -> LLMReply:
    visible_text = str(final_text or "").strip()
    block = render_finalization_contract_block(
        FinalizationContractDraft(requires_result_coverage=True)
    )
    return LLMReply(final_text=f"{visible_text}\n{block}".strip())


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
        self._knowledge_large_progress_polls = 0

    def complete(self, request):  # noqa: ANN001
        self.requests.append(request)
        if request.request_kind == "agent_routing":
            message = str(request.message or "")
            target = "bazi" if self.case_id.startswith("bazi_") or any(
                marker in message
                for marker in ("八字", "四柱", "农历", "子平", "盲派", "大运")
            ) else "main"
            return LLMReply(
                tool_name="agent_route",
                tool_payload={"target_agent_id": target},
            )
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
        if request.request_kind == "bazi_dayun_repair" and self.case_id.startswith("bazi_"):
            return _normalize_reply_contract_metadata(
                request,
                LLMReply(
                    tool_name="bazi",
                    tool_payload=dict(request.requested_tool_payload or {"action": "dayun"}),
                ),
            )
        if request.request_kind == "bazi_knowledge_search" and self.case_id.startswith("bazi_"):
            query = (
                "no_matching_theory_token"
                if self.case_id == "bazi_no_recall_degradation_cn"
                else "bazi_theory_evidence_boundary"
            )
            payload = {
                **dict(request.requested_tool_payload or {}),
                "action": "search",
                "namespace": "bazi-theory",
                "query": query,
                "top_k": 3,
            }
            if self.case_id == "bazi_no_recall_degradation_cn":
                payload["filters"] = {"school": "missing-school"}
            return _normalize_reply_contract_metadata(
                request,
                LLMReply(
                    tool_name="knowledge",
                    tool_payload=payload,
                ),
            )
        if request.request_kind == "finalization_retry" and self.case_id.startswith("bazi_"):
            return _normalize_reply_contract_metadata(
                request,
                _bazi_result_covered_reply(
                    request,
                    _scripted_bazi_analysis_text(),
                ),
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
        scripted_subagent = _scripted_main_chain_subagent_reply(self)
        if scripted_subagent is not None:
            return _normalize_reply_contract_metadata(request, scripted_subagent)
        scripted_subagent = _scripted_subagent_suite_reply(self)
        if scripted_subagent is not None:
            return _normalize_reply_contract_metadata(request, scripted_subagent)
        scripted_knowledge = _scripted_knowledge_suite_reply(self)
        if scripted_knowledge is not None:
            return _normalize_reply_contract_metadata(request, scripted_knowledge)
        scripted_bazi = _scripted_bazi_suite_reply(self)
        if scripted_bazi is not None:
            return _normalize_reply_contract_metadata(request, scripted_bazi)
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
    if case.case_id == "bazi_fingerprint_mismatch_cn":
        _install_bazi_fingerprint_mismatch_fixture(runtime)
    isolated_reply_text = _isolated_compaction_reply_text(case.case_id)
    if isolated_reply_text is not None:
        runtime.llm_client_factory.create_isolated = lambda profile_name: FixedReplyLLMClient(  # type: ignore[method-assign]
            provider_name=provider_name,
            model_name=model_name,
            reply_text=isolated_reply_text,
        )


def _install_bazi_fingerprint_mismatch_fixture(runtime) -> None:  # noqa: ANN001
    registry = runtime.tool_registry
    original_handler = registry._handlers["bazi"]

    def mismatched_bazi_handler(payload, *, tool_context=None):  # noqa: ANN001, ANN202
        result = original_handler(payload, tool_context=tool_context)
        if payload.get("action") != "dayun" or result.get("ok") is not True:
            return result
        return {
            **result,
            "inputFingerprint": f"sha256:{'f' * 64}",
        }

    registry._handlers["bazi"] = mismatched_bazi_handler


def _isolated_compaction_reply_text(case_id: str) -> str | None:
    if case_id == "context_compaction_continuity_cn":
        return "当前进展：旧历史已经压缩。"
    if case_id == "proactive_compaction_cn":
        return "当前进展：长线程已压缩。"
    return None


def _scripted_tool_followup_reply(llm: ScriptedEvalLLMClient, request) -> LLMReply | None:  # noqa: ANN001
    if llm.case_id.startswith("bazi_"):
        return _scripted_bazi_tool_followup(llm, request)
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
    if llm.case_id == "knowledge_large_file_progress_cn":
        requested_tool_name = str(request.requested_tool_name or "").strip()
        tool_result = request.tool_result if isinstance(request.tool_result, dict) else {}
        if requested_tool_name == "knowledge" and str(tool_result.get("action") or "") == "ingest_file":
            job_id = str(tool_result.get("job_id") or "").strip()
            if job_id:
                llm.context["knowledge_large_job_id"] = job_id
                llm._knowledge_large_progress_polls += 1
                return LLMReply(
                    tool_name="knowledge",
                    tool_payload={"action": "ingest_status", "namespace": "fanqie", "job_id": job_id},
                )
        if requested_tool_name == "knowledge" and str(request.requested_tool_payload.get("action") or "") == "ingest_status":
            status = str(tool_result.get("status") or "")
            job_id = str(tool_result.get("job_id") or llm.context.get("knowledge_large_job_id") or "").strip()
            if status not in {"completed", "failed", "cancelled"} and llm._knowledge_large_progress_polls < 8 and job_id:
                llm._knowledge_large_progress_polls += 1
                time.sleep(0.2)
                return LLMReply(
                    tool_name="knowledge",
                    tool_payload={"action": "ingest_status", "namespace": "fanqie", "job_id": job_id},
                )
            return _contracted_final_reply(str(tool_result))
    return None


def _scripted_memory_suite_reply(llm: ScriptedEvalLLMClient, message: str) -> LLMReply | None:
    if llm.case_id == "memory_capture_preference_cn":
        return LLMReply(
            tool_name="memory",
            tool_payload={
                "action": "replace",
                "intent": "durable_write",
                "scope": "global",
                "source_excerpt": message,
                "section": "preferences",
                "type": "preference",
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
                    "scope": "global",
                    "section": "preferences",
                    "type": "preference",
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
                    "scope": "global",
                    "section": "preferences",
                    "type": "preference",
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
                    "scope": "global",
                    "section": "preferences",
                    "type": "preference",
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
                    "scope": "global",
                    "section": "preferences",
                    "type": "preference",
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
                    "scope": "global",
                    "section": "preferences",
                    "type": "preference",
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
                    "scope": "global",
                    "section": "preferences",
                    "type": "preference",
                    "content": "周报默认先结论，后细节。",
                },
            )
        return _contracted_final_reply("现在周报顺序是：先结论，后细节。")
    if llm.case_id == "memory_preference_applied_to_output_cn":
        return _contracted_final_reply("结论：本周接口联调已完成；细节：剩余文档整理中。")
    return None


def _scripted_main_chain_subagent_reply(llm: ScriptedEvalLLMClient) -> LLMReply | None:
    if llm.case_id == "subagent_github_lookup_cn":
        return _contracted_final_reply("子 agent 已受理 GitHub 信息查询。")
    if llm.case_id == "subagent_completion_notice_cn":
        return _contracted_final_reply("子 agent 已受理，完成后会通知你。")
    if llm.case_id == "subagent_parent_summary_cn":
        return _contracted_final_reply("子 agent 摘要：后台任务已完成。")
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
                    "task": "inspect README project focus",
                    "label": "readme-focus",
                    "finalize_response": True,
                },
            )
        return _contracted_final_reply("我吸收后的结论：README 主要描述 runtime 主链、eval 评测和 provider 基线。")
    if llm.case_id == "subagent_multi_child_progress_cn":
        if llm._conversation_turns == 1:
            llm._subagent_spawn_count += 1
            return LLMReply(
                tool_name="spawn_subagent",
                tool_payload={
                    "task": "inspect README project positioning",
                    "label": "readme-positioning",
                },
            )
        return _contracted_final_reply("两个子任务都完成了：项目定位是自托管 agent runtime harness；运行与评测入口包括快速开始、运行命令和离线评测。")
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


def _scripted_knowledge_suite_reply(llm: ScriptedEvalLLMClient) -> LLMReply | None:
    if not llm.case_id.startswith("knowledge_"):
        return None
    if llm.case_id == "knowledge_large_file_progress_cn":
        return LLMReply(
            tool_name="knowledge",
            tool_payload={"action": "ingest_file", "namespace": "fanqie", "file_path": "evals/fixtures/knowledge/fanqie_large.txt", "source": {"title": "Fanqie Large", "kind": "txt", "uri": "eval://fanqie/large"}},
        )
    query_by_case = {
        "knowledge_keyword_recall_cn": "fanqie_chapter_1",
        "knowledge_semantic_recall_cn": "fanqie_master_scene",
        "knowledge_rerank_improvement_cn": "fanqie_best_chunk",
        "knowledge_namespace_isolation_cn": "fanqie_only",
        "knowledge_config_mismatch_cn": "mismatch_chunk",
        "knowledge_delete_recall_cn": "remaining_chunk",
    }
    return LLMReply(
        tool_name="knowledge",
        tool_payload={"action": "search", "namespace": "fanqie", "query": query_by_case.get(llm.case_id, llm.case_id), "top_k": 5},
    )


def _scripted_bazi_suite_reply(llm: ScriptedEvalLLMClient) -> LLMReply | None:
    if not llm.case_id.startswith("bazi_"):
        return None
    if llm.case_id == "bazi_resolve_pillars_cn":
        return LLMReply(
            tool_name="bazi",
            tool_payload={
                "action": "resolve_pillars",
                "yearPillar": "戊辰",
                "monthPillar": "甲寅",
                "dayPillar": "辛丑",
                "hourPillar": "戊子",
            },
        )
    return LLMReply(tool_name="bazi", tool_payload=_bazi_birth_payload("chart"))


def _scripted_bazi_tool_followup(llm: ScriptedEvalLLMClient, request) -> LLMReply:
    tool_name = str(request.requested_tool_name or "")
    action = str((request.requested_tool_payload or {}).get("action") or "")
    result = request.tool_result if isinstance(request.tool_result, dict) else {}
    if tool_name == "bazi":
        fingerprint = str(result.get("inputFingerprint") or "")
        if action == "resolve_pillars":
            return _bazi_result_covered_reply(
                request, "反查候选已由 bazi engine 返回。"
            )
        if action == "chart":
            llm.context["bazi_chart_fingerprint"] = fingerprint
            if llm.case_id in {
                "bazi_dayun_citation_cn",
                "bazi_fingerprint_mismatch_cn",
                "bazi_theory_citation_cn",
            }:
                payload = _bazi_birth_payload("dayun")
                return LLMReply(tool_name="bazi", tool_payload=payload)
            knowledge_payload = {
                    "action": "search",
                    "namespace": "bazi-theory",
                    "query": (
                        "no_matching_theory_token"
                        if llm.case_id == "bazi_no_recall_degradation_cn"
                        else "bazi_theory_evidence_boundary"
                    ),
                    "top_k": 3,
                }
            if llm.case_id == "bazi_no_recall_degradation_cn":
                knowledge_payload["filters"] = {"school": "missing-school"}
            return LLMReply(
                tool_name="knowledge",
                tool_payload=knowledge_payload,
            )
        if action == "dayun":
            chart_fingerprint = str(llm.context.get("bazi_chart_fingerprint") or "")
            if not chart_fingerprint:
                chart_fingerprint = _bazi_fingerprint_from_history(
                    request.tool_history, "chart"
                )
            if llm.case_id == "bazi_fingerprint_mismatch_cn":
                return _bazi_result_covered_reply(
                    request,
                    f"chart={chart_fingerprint}; dayun={fingerprint}; fingerprint 不一致，停止综合解释。",
                )
            return LLMReply(
                tool_name="knowledge",
                tool_payload={
                    "action": "search",
                    "namespace": "bazi-theory",
                    "query": "bazi_theory_evidence_boundary",
                    "top_k": 3,
                },
            )
    if tool_name == "knowledge":
        references = [
            _readable_bazi_reference(item)
            for item in result.get("results") or []
            if isinstance(item, dict)
        ]
        references = [item for item in references if item]
        if not references:
            return _bazi_result_covered_reply(
                request,
                "排盘事实保留；theory 暂不可用。现实建议应结合当前信息和专业支持。",
            )
        return _bazi_result_covered_reply(
            request,
            _scripted_bazi_analysis_text(),
        )
    return _result_covered_final_reply("Bazi scripted evaluation completed.")


def _bazi_fingerprint_from_history(tool_history, action: str) -> str:  # noqa: ANN001
    for exchange in reversed(tool_history):
        if exchange.tool_name != "bazi":
            continue
        exchange_action = str(
            exchange.tool_payload.get("action")
            or exchange.tool_result.get("action")
            or ""
        ).strip()
        if exchange_action == action:
            return str(exchange.tool_result.get("inputFingerprint") or "").strip()
    return ""


def _bazi_birth_payload(action: str) -> dict[str, object]:
    return {
        "action": action,
        "gender": "male",
        "birthYear": 1988,
        "birthMonth": 2,
        "birthDay": 15,
        "birthHour": 23,
        "birthMinute": 30,
        "calendarType": "solar",
        "timeBasis": "clock",
        "sourceTimeStandard": "beijing_standard",
    }


def _scripted_bazi_analysis_text() -> str:
    return (
        "一、命盘\n天干：戊　甲　辛　戊\n地支：辰　寅　丑　子\n天干、地支与大运以本轮 taibu-core-marten 结果为准。\n\n"
        "二、原局格局喜用\n按格局、旺衰、调候、病药、财官、体用、做功和喜忌综合判断。\n\n"
        "三、大运\n按原局与已核验行运说明阶段变化。\n\n"
        "四、健康注意\n2006（丙戌）｜待核验脾胃检查、治疗或开刀经历｜流年戌冲原局年支辰，并与日支丑形成刑，岁运共同引动土象病位；现实判断结合现实信息和专业支持。\n\n"
        "五、学历\n本科｜2006 年前后完成关键升学｜流年丙戌处于已核验大运，引动原局印食结构，待本人核验。\n\n"
        "六、事业\n2012-2014 年进入专业输出型岗位｜食伤做功在对应行运得到发挥。\n\n"
        "七、婚姻\n日支丑的婚姻桃花为午。2014（甲午）财星透出、午为日支丑的桃花，并与时支子相冲，是首次结婚窗口。\n\n"
        "八、六亲\n2006（丙戌）｜待核验父亲脾胃检查｜流年戌冲年支辰，父星与年柱土象同步受作用。\n2016（丙申）｜待核验母亲腿脚或胆部检查｜流年申冲月支寅，母星与月柱寅木身体取象同步受作用。\n\n"
        "九、财富等级\n财富结构分：6/9＝成局路径 2 + 承载 2 + 大运 3 - 制约 1。无财时由食伤生财或暗成财局参与成局路径，官印、杀印、食神制杀与禄只在成格时作为职业变现通道，不直接改称财星。命理年收入能力区间：30-60 万元；这是传统文化模型估算，不等同现实收入。未提供储蓄率、资产和负债，不能换算净积累与总资产。\n\n"
        "十、过三关\n"
        "2006（丙戌）｜待核验关键升学结果｜推算原因：流年：丙戌引动学习结构；大运：本轮已核验行运；原局：印食结构被引动。\n"
        "2014（甲午）｜待核验出现重要恋爱对象｜推算原因：流年：甲午为日支丑的桃花；大运：本轮已核验行运；原局：夫妻宫被桃花引动。\n"
        "2006（丙戌）｜待核验本人脾胃检查｜推算原因：流年：丙戌冲年支辰、刑日支丑；大运：本轮已核验行运；原局：脾胃土象被引动。\n"
        "2016（丙申）｜待核验家庭环境变化｜推算原因：流年：丙申冲月支寅；大运：本轮已核验行运；原局：月柱家庭宫位被引动。\n\n"
        "十一、参考依据\n使用本轮检索到的书名与篇章。"
    )


def _bazi_result_covered_reply(request, final_text: str) -> LLMReply:  # noqa: ANN001
    ledger = build_finalization_evidence_ledger(
        user_message=str(request.message or ""),
        tool_history=list(request.tool_history),
        model_request_count=None,
        requires_result_coverage=True,
        requires_round_trip_report=False,
    )
    summaries = [
        str(item.result_summary).strip()
        for item in ledger.items
        if item.required_for_user_request and str(item.result_summary or "").strip()
    ]
    visible_text = str(final_text or "").strip()
    references = _bazi_knowledge_references(request.tool_history)
    missing_references = [item for item in references if item not in visible_text]
    if missing_references:
        rendered = "、".join(missing_references)
        visible_text = f"{visible_text}\n参考依据：{rendered}。".strip()
    return _result_covered_final_reply("\n\n".join([*summaries, visible_text]))


def _bazi_knowledge_references(tool_history) -> list[str]:  # noqa: ANN001
    references: list[str] = []
    for exchange in tool_history:
        if str(exchange.tool_name or "").strip() != "knowledge":
            continue
        action = str(
            exchange.tool_payload.get("action")
            or exchange.tool_result.get("action")
            or ""
        ).strip()
        if action != "search":
            continue
        for item in exchange.tool_result.get("results") or []:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("source_id") or "").strip()
            chunk_id = str(item.get("chunk_id") or "").strip()
            reference = _readable_bazi_reference(item)
            if source_id and chunk_id and reference and reference not in references:
                references.append(reference)
    return references


def _readable_bazi_reference(item: dict[str, object]) -> str:
    title = str(item.get("source_title") or "").strip()
    if not title:
        return ""
    heading = str(item.get("heading") or "").strip()
    book = title if title.startswith("《") else f"《{title}》"
    return f"{book}·{heading}" if heading else book


def _scripted_subagent_child_reply(llm: ScriptedEvalLLMClient, request) -> LLMReply:  # noqa: ANN001
    llm._subagent_child_calls += 1
    if llm.case_id == "subagent_followup_uses_child_result_cn":
        return _contracted_final_reply("README 主要描述 runtime 主链、eval 评测和 provider 基线。")
    if llm.case_id == "subagent_multi_child_progress_cn":
        if llm._subagent_child_calls == 1:
            return _contracted_final_reply("项目定位是自托管 agent runtime harness，核心能力围绕主链。")
        return _contracted_final_reply("运行与评测入口包括快速开始、运行命令和离线评测。")
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
                    "scope": "global",
                    "section": "preferences",
                    "type": "preference",
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
                    "scope": "global",
                    "section": "preferences",
                    "type": "preference",
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
                    "scope": "global",
                    "section": "preferences",
                    "type": "preference",
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
