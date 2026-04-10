from __future__ import annotations

import json
import math

from marten_runtime.runtime.usage_models import PreflightEstimate


def serialize_payload_stably(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def classify_serialized_payload_chars(serialized_payload: str) -> dict[str, int]:
    buckets = {
        "ascii_text_chars": 0,
        "cjk_chars": 0,
        "other_non_ascii_chars": 0,
        "json_structure_chars": 0,
        "whitespace_chars": 0,
        "escaped_unicode_sequences": 0,
    }
    index = 0
    while index < len(serialized_payload):
        if _looks_like_escaped_unicode_sequence(serialized_payload, index):
            buckets["escaped_unicode_sequences"] += 1
            index += 6
            continue
        ch = serialized_payload[index]
        if ch in {" ", "\t", "\r", "\n"}:
            buckets["whitespace_chars"] += 1
        elif ch in {'{', '}', '[', ']', ':', ',', '"'}:
            buckets["json_structure_chars"] += 1
        elif _is_cjk(ch):
            buckets["cjk_chars"] += 1
        elif ord(ch) <= 0x7F:
            buckets["ascii_text_chars"] += 1
        else:
            buckets["other_non_ascii_chars"] += 1
        index += 1
    return buckets


def estimate_payload_tokens(payload: object, *, tokenizer_family: str | None) -> PreflightEstimate:
    normalized_family = (tokenizer_family or "rough").strip().lower()
    serialized = serialize_payload_stably(payload)
    buckets = classify_serialized_payload_chars(serialized)
    if normalized_family == "openai_cl100k":
        return PreflightEstimate(
            input_tokens_estimate=_estimate_weighted(
                buckets,
                ascii_divisor=3.9,
                cjk_divisor=1.12,
                other_divisor=1.9,
                json_divisor=1.8,
                whitespace_divisor=5.8,
                escaped_unicode_divisor=0.32,
            ),
            estimator_kind="tokenizer",
            degraded=False,
        )
    if normalized_family == "openai_o200k":
        return PreflightEstimate(
            input_tokens_estimate=_estimate_weighted(
                buckets,
                ascii_divisor=4.1,
                cjk_divisor=1.15,
                other_divisor=1.95,
                json_divisor=1.9,
                whitespace_divisor=6.0,
                escaped_unicode_divisor=0.34,
            ),
            estimator_kind="tokenizer",
            degraded=False,
        )
    return PreflightEstimate(
        input_tokens_estimate=_estimate_weighted(
            buckets,
            ascii_divisor=4.0,
            cjk_divisor=1.2,
            other_divisor=2.0,
            json_divisor=2.0,
            whitespace_divisor=6.0,
            escaped_unicode_divisor=0.36,
        ),
        estimator_kind="rough",
        degraded=True,
    )


def _estimate_weighted(
    buckets: dict[str, int],
    *,
    ascii_divisor: float,
    cjk_divisor: float,
    other_divisor: float,
    json_divisor: float,
    whitespace_divisor: float,
    escaped_unicode_divisor: float,
) -> int:
    return int(
        math.ceil(
            buckets["ascii_text_chars"] / ascii_divisor
            + buckets["cjk_chars"] / cjk_divisor
            + buckets["other_non_ascii_chars"] / other_divisor
            + buckets["json_structure_chars"] / json_divisor
            + buckets["whitespace_chars"] / whitespace_divisor
            + buckets.get("escaped_unicode_sequences", 0) / escaped_unicode_divisor
        )
    )


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0x3040 <= code <= 0x309F
        or 0x30A0 <= code <= 0x30FF
        or 0xAC00 <= code <= 0xD7AF
    )


def _looks_like_escaped_unicode_sequence(serialized_payload: str, index: int) -> bool:
    if index + 6 > len(serialized_payload):
        return False
    if serialized_payload[index] != "\\" or serialized_payload[index + 1] != "u":
        return False
    return all(ch in "0123456789abcdefABCDEF" for ch in serialized_payload[index + 2 : index + 6])
