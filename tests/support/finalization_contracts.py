from __future__ import annotations

from marten_runtime.runtime.finalization_contract_prompt import (
    FinalizationContractDraft,
    extract_finalization_contract_block,
    render_finalization_contract_block,
)
from marten_runtime.runtime.llm_client import LLMReply


def plain_final_reply(final_text: str, **kwargs) -> LLMReply:
    draft = kwargs.pop("finalization_contract_draft", None)
    return LLMReply(final_text=final_text, finalization_contract_draft=draft, **kwargs)


def contracted_final_reply(final_text: str, **kwargs) -> LLMReply:
    if "finalization_contract_draft" in kwargs:
        draft = kwargs.pop("finalization_contract_draft")
    else:
        draft = FinalizationContractDraft()
    if draft is None:
        return LLMReply(final_text=final_text, finalization_contract_draft=None, **kwargs)
    rendered = f"{str(final_text or '').strip()}\n{render_finalization_contract_block(draft)}"
    parsed = extract_finalization_contract_block(rendered)
    return LLMReply(
        final_text=parsed.final_text,
        finalization_contract_draft=parsed.contract_draft,
        **kwargs,
    )
