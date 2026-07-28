from __future__ import annotations

import hashlib
from typing import Mapping


STANDARD_OBSERVATION = "standard"
SENSITIVE_BAZI_OBSERVATION = "sensitive_bazi"
METADATA_ONLY_OBSERVATION = "metadata_only"
REDACTED_TEXT = "[REDACTED:sensitive_bazi]"
METADATA_REDACTED_TEXT = "[REDACTED:metadata_only]"


def is_sensitive_bazi(policy: str | None) -> bool:
    return str(policy or STANDARD_OBSERVATION) == SENSITIVE_BAZI_OBSERVATION


def is_metadata_only(policy: str | None) -> bool:
    return str(policy or STANDARD_OBSERVATION) == METADATA_ONLY_OBSERVATION


def resolve_observation_policy(
    agent_policy: str | None,
    tool_policy: str | None = None,
) -> str:
    if is_sensitive_bazi(agent_policy) or is_sensitive_bazi(tool_policy):
        return SENSITIVE_BAZI_OBSERVATION
    if is_metadata_only(agent_policy) or is_metadata_only(tool_policy):
        return METADATA_ONLY_OBSERVATION
    return STANDARD_OBSERVATION


def project_text(value: str | None, policy: str | None) -> str | None:
    if value is None:
        return value
    if is_sensitive_bazi(policy):
        return REDACTED_TEXT if str(value).strip() else ""
    if is_metadata_only(policy):
        return METADATA_REDACTED_TEXT if str(value).strip() else ""
    return value


def project_generation_input(payload: Mapping[str, object], policy: str | None) -> dict:
    if not is_sensitive_bazi(policy) and not is_metadata_only(policy):
        return dict(payload)
    return {
        "message": METADATA_REDACTED_TEXT if is_metadata_only(policy) else REDACTED_TEXT,
        "available_tools": list(payload.get("available_tools") or []),
        "requested_tool_name": payload.get("requested_tool_name"),
        "tool_history_count": int(payload.get("tool_history_count") or 0),
    }


def project_generation_output(payload: Mapping[str, object], policy: str | None) -> dict:
    if not is_sensitive_bazi(policy) and not is_metadata_only(policy):
        return dict(payload)
    tool_name = payload.get("tool_name")
    if tool_name:
        tool_payload = payload.get("tool_payload")
        if is_metadata_only(policy):
            target = tool_payload.get("target_agent_id") if isinstance(tool_payload, dict) else None
            return {"tool_name": tool_name, "tool_payload": {"target_agent_id": target}}
        action = tool_payload.get("action") if isinstance(tool_payload, dict) else None
        return {"tool_name": tool_name, "tool_payload": {"action": action}}
    return {"final_text": METADATA_REDACTED_TEXT if is_metadata_only(policy) else REDACTED_TEXT}


def project_tool_payload(payload: Mapping[str, object], policy: str | None) -> dict:
    if is_metadata_only(policy):
        return {"target_agent_id": payload.get("target_agent_id")}
    if not is_sensitive_bazi(policy):
        return dict(payload)
    projected = {"action": payload.get("action")}
    for field in (
        "calendarType",
        "isLeapMonth",
        "timeBasis",
        "timezone",
        "sourceTimeStandard",
        "detailLevel",
    ):
        if field in payload:
            projected[field] = payload[field]
    return projected


def project_tool_result(result: Mapping[str, object], policy: str | None) -> dict:
    if is_metadata_only(policy):
        return {
            field: result[field]
            for field in ("ok", "target_agent_id")
            if field in result
        }
    if not is_sensitive_bazi(policy):
        return dict(result)
    projected = {
        field: result[field]
        for field in (
            "ok",
            "is_error",
            "protocolVersion",
            "requestId",
            "action",
            "resultSchemaVersion",
            "inputFingerprint",
        )
        if field in result
    }
    engine = result.get("engine")
    if isinstance(engine, dict):
        projected["engine"] = dict(engine)
    error = result.get("error")
    if isinstance(error, dict):
        projected["error"] = {
            field: error[field]
            for field in ("code", "retryable")
            if field in error
        }
    time_basis = result.get("timeBasis")
    if isinstance(time_basis, dict):
        projected["timeBasis"] = _project_time_basis(time_basis)
    diagnostics = result.get("degradedDiagnostics")
    if isinstance(diagnostics, list):
        projected["degradedDiagnostics"] = [
            {
                field: item[field]
                for field in ("reason", "elapsedMs", "exitCode", "stderrTruncated")
                if isinstance(item, dict) and field in item
            }
            for item in diagnostics[:3]
        ]
    if "result" in result:
        projected["resultPresent"] = True
    citation_results = []
    for item in result.get("results") or []:
        if not isinstance(item, dict) or not item.get("source_id") or not item.get("chunk_id"):
            continue
        citation_results.append(
            {
                "source_id": item["source_id"],
                "chunk_id": item["chunk_id"],
            }
        )
    if citation_results:
        projected["results"] = citation_results
    for field in (
        "retrieval_mode",
        "vector_status",
        "rerank_status",
        "degraded_reason",
    ):
        if field in result:
            projected[field] = result[field]
    return projected


def _project_time_basis(value: Mapping[str, object]) -> dict:
    projected = {
        field: value[field]
        for field in (
            "requested",
            "timezone",
            "sourceTimeStandard",
            "sourceUtcOffsetMinutes",
            "dstAdjustmentMinutes",
            "sourceCalendarType",
            "sourceIsLeapMonth",
            "effectiveCalendarType",
            "trueSolarAlgorithm",
            "dayBoundaryPolicy",
            "qiyunMethod",
        )
        if field in value
    }
    place = value.get("placeResolution")
    if isinstance(place, dict):
        projected["placeResolution"] = {
            field: place[field]
            for field in ("provider", "resolverVersion", "level", "coordinateSystem")
            if field in place
        }
        adcode = str(place.get("adcode") or "")
        if adcode:
            projected["placeResolution"]["adcodeHash"] = hashlib.sha256(
                adcode.encode("utf-8")
            ).hexdigest()[:12]
    else:
        projected["placeResolution"] = None
    return projected
