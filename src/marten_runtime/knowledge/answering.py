from __future__ import annotations

import re
from time import perf_counter
from uuid import uuid4

from marten_runtime.runtime.llm_client import LLMRequest


_MAX_EVIDENCE_ITEMS = 3
_MAX_EVIDENCE_ITEM_CHARS = 1_800
_MAX_EVIDENCE_CHARS = _MAX_EVIDENCE_ITEMS * _MAX_EVIDENCE_ITEM_CHARS


class KnowledgeAnswerService:
    def __init__(self, *, knowledge_service, llm_factory, model_profile: str) -> None:  # noqa: ANN001
        self.knowledge_service = knowledge_service
        self.llm_factory = llm_factory
        self.model_profile = model_profile

    def answer(self, *, namespace: str, query: str) -> dict[str, object]:
        started_at = perf_counter()
        retrieval_started_at = perf_counter()
        search = self.knowledge_service.search(namespace=namespace, query=query, top_k=6)
        retrieval_ms = _elapsed_ms(retrieval_started_at)
        if not search.get("ok"):
            return search
        evidence = _select_evidence(query, list(search.get("results") or []))
        if not _has_direct_support(query, evidence):
            return {
                "ok": True,
                "answer": "当前知识库没有足够依据。",
                "evidence": evidence,
                "retrieval": _retrieval_diagnostics(search),
                "retrieval_ms": retrieval_ms,
                "generation_ms": 0.0,
                "total_ms": _elapsed_ms(started_at),
                "model_request_count": 0,
                "usage": {},
                "insufficient_evidence": True,
            }
        prompt = _answer_prompt(query, evidence)
        generation_started_at = perf_counter()
        client = self.llm_factory()
        reply = client.complete(
            LLMRequest(
                session_id=f"knowledge_{uuid4().hex[:12]}",
                trace_id=f"knowledge_{uuid4().hex[:12]}",
                message=prompt,
                agent_id="knowledge-console",
                system_prompt=(
                    "你是经典命理知识库的证据解释器。只能依据用户消息中的证据回答，"
                    "不得使用参数知识补充事实，不得调用工具。"
                ),
                request_kind="knowledge_answer",
                prompt_mode="minimal",
                max_completion_tokens=640,
                timeout_seconds_override=60,
            )
        )
        generation_ms = _elapsed_ms(generation_started_at)
        answer = str(reply.final_text or "").strip()
        if not answer or reply.tool_name:
            return {
                "ok": False,
                "error_code": "KNOWLEDGE_ANSWER_INVALID",
                "message": "answer model did not return a final evidence explanation",
                "model_request_count": 1,
                "retrieval_ms": retrieval_ms,
                "generation_ms": generation_ms,
            }
        return {
            "ok": True,
            "answer": answer,
            "evidence": evidence,
            "retrieval": _retrieval_diagnostics(search),
            "retrieval_ms": retrieval_ms,
            "generation_ms": generation_ms,
            "total_ms": _elapsed_ms(started_at),
            "model_request_count": 1,
            "usage": _usage_payload(reply.usage),
            "insufficient_evidence": False,
            "model": {
                "profile": self.model_profile,
                "provider": str(getattr(client, "provider_name", "")),
                "model": str(getattr(client, "model_name", "")),
            },
        }


def _select_evidence(query: str, results: list[dict[str, object]]) -> list[dict[str, object]]:
    terms = _query_terms(query)
    directly_supported = [
        item
        for item in results
        if any(term in str(item.get("text") or "") for term in terms)
    ]
    selected_results = directly_supported or results
    candidates: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    used_chars = 0
    for item in selected_results:
        if len(candidates) >= _MAX_EVIDENCE_ITEMS:
            break
        metadata = dict(item.get("metadata") or {})
        if str(metadata.get("evidence_kind") or "") in {"course_notes", "case_record"}:
            continue
        identity = (str(item.get("source_id") or ""), str(item.get("heading") or ""))
        if identity in seen:
            continue
        text = str(item.get("text") or "").strip()
        remaining = _MAX_EVIDENCE_CHARS - used_chars
        if remaining <= 0:
            break
        text = text[:min(remaining, _MAX_EVIDENCE_ITEM_CHARS)]
        candidates.append(
            {
                "chunk_id": str(item.get("chunk_id") or ""),
                "source_id": identity[0],
                "source_title": str(item.get("source_title") or ""),
                "heading": identity[1],
                "evidence_kind": str(metadata.get("evidence_kind") or ""),
                "text": text,
            }
        )
        seen.add(identity)
        used_chars += len(text)
    return candidates


def _retrieval_diagnostics(search: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in search.items() if key != "results"}


def _has_direct_support(query: str, evidence: list[dict[str, object]]) -> bool:
    corpus = "\n".join(str(item.get("text") or "") for item in evidence)
    return bool(evidence) and any(term in corpus for term in _query_terms(query))


def _query_terms(query: str) -> set[str]:
    compact = re.sub(r"[？?，,。.!！：:\s]", "", str(query or ""))
    for suffix in ("有什么特征", "有哪些特征", "是什么意思", "是什么", "为什么", "怎样", "如何", "怎么"):
        compact = compact.replace(suffix, "")
    terms = {compact}
    if compact.endswith("格") and len(compact) > 2:
        terms.add(compact[:-1])
    return {term for term in terms if len(term) >= 2}


def _answer_prompt(query: str, evidence: list[dict[str, object]]) -> str:
    blocks = []
    for index, item in enumerate(evidence, start=1):
        blocks.append(
            "证据 {index}\n书名：{title}\n章节：{heading}\n证据类型：{kind}\n"
            "内部引用：{source_id}/{chunk_id}\n正文：\n{text}".format(index=index, **item, title=item["source_title"], kind=item["evidence_kind"])
        )
    return (
        f"问题：{query}\n\n" + "\n\n".join(blocks) +
        "\n\n请只根据以上证据，用现代中文回答，总计不超过 600 个中文字符。固定输出四段："
        "\n## 原文依据\n逐条短引，不得把解释写成原文。"
        "\n## 现代解释\n直接回答问题，不扩展人格、财富、疾病或现实事件结论。"
        "\n## 适用限制\n说明证据边界；证据不足处明确写出。"
        "\n## 引用\n使用“《书名》·章节”的格式，并保留对应的 [证据 N]。"
    )


def _usage_payload(usage: object | None) -> dict[str, object]:
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        return dict(usage.model_dump(mode="json"))
    if isinstance(usage, dict):
        return dict(usage)
    return {"raw": str(usage)}


def _elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000.0, 3)
