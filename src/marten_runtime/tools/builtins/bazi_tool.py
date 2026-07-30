from __future__ import annotations

import unicodedata
from copy import deepcopy
from datetime import date
from typing import Mapping
from uuid import uuid4

from marten_runtime.runtime.bazi_bridge import (
    BaziBridgeError,
    BaziBridgeManager,
    ENGINE,
    PROTOCOL_VERSION,
    RESULT_SCHEMAS,
)


_STEMS = "甲乙丙丁戊己庚辛壬癸"
_BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
_JIAZI = frozenset(
    _STEMS[index % len(_STEMS)] + _BRANCHES[index % len(_BRANCHES)]
    for index in range(60)
)
_BIRTH_PROPERTIES = {
    "action": {"type": "string", "enum": ["chart", "dayun"]},
    "gender": {"type": "string", "enum": ["male", "female"]},
    "birthYear": {"type": "integer", "minimum": 1901, "maximum": 2100},
    "birthMonth": {"type": "integer", "minimum": 1, "maximum": 12},
    "birthDay": {"type": "integer", "minimum": 1, "maximum": 31},
    "birthHour": {"type": "integer", "minimum": 0, "maximum": 23},
    "birthMinute": {"type": "integer", "minimum": 0, "maximum": 59, "default": 0},
    "calendarType": {"type": "string", "enum": ["solar", "lunar"], "default": "solar"},
    "isLeapMonth": {"type": "boolean", "default": False},
    "birthPlace": {"type": "string", "minLength": 2, "maxLength": 200},
    "timeBasis": {"type": "string", "enum": ["clock", "true_solar"], "default": "clock"},
    "timezone": {"type": "string", "const": "Asia/Shanghai", "default": "Asia/Shanghai"},
    "sourceTimeStandard": {
        "type": "string",
        "enum": ["recorded_civil", "beijing_standard"],
        "default": "recorded_civil",
    },
    "detailLevel": {"type": "string", "enum": ["default", "full"], "default": "default"},
}
_PILLAR_PATTERN = f"^[{_STEMS}][{_BRANCHES}]$"
_RESULT_CACHE_NAMESPACE = "bazi.successful_requests"
CURRENT_RESULT_STATE_KEY = "bazi.current_result"
RESULTS_BY_ACTION_STATE_KEY = "bazi.results_by_action"

BAZI_PARAMETERS_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$defs": {
        "birthRequest": {
            "type": "object",
            "properties": _BIRTH_PROPERTIES,
            "required": [
                "action",
                "gender",
                "birthYear",
                "birthMonth",
                "birthDay",
                "birthHour",
            ],
            "allOf": [
                {
                    "if": {
                        "required": ["isLeapMonth"],
                        "properties": {"isLeapMonth": {"const": True}},
                    },
                    "then": {
                        "required": ["calendarType"],
                        "properties": {"calendarType": {"const": "lunar"}},
                    },
                },
                {
                    "if": {
                        "required": ["timeBasis"],
                        "properties": {"timeBasis": {"const": "true_solar"}},
                    },
                    "then": {"required": ["birthPlace"]},
                },
            ],
            "additionalProperties": False,
        },
        "resolveRequest": {
            "type": "object",
            "properties": {
                "action": {"const": "resolve_pillars"},
                "gender": {"type": "string", "enum": ["male", "female"]},
                "yearPillar": {"type": "string", "pattern": _PILLAR_PATTERN},
                "monthPillar": {"type": "string", "pattern": _PILLAR_PATTERN},
                "dayPillar": {"type": "string", "pattern": _PILLAR_PATTERN},
                "hourPillar": {"type": "string", "pattern": _PILLAR_PATTERN},
            },
            "required": [
                "action",
                "yearPillar",
                "monthPillar",
                "dayPillar",
                "hourPillar",
            ],
            "additionalProperties": False,
        },
    },
    "oneOf": [
        {"$ref": "#/$defs/birthRequest"},
        {"$ref": "#/$defs/resolveRequest"},
    ],
}


class BaziInputError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def run_bazi_tool(
    payload: dict,
    *,
    bridge_manager: BaziBridgeManager,
    tool_context: dict | None = None,
) -> dict:
    request_id = f"bazi_{uuid4().hex}"
    action = str(payload.get("action") or "").strip()
    try:
        arguments, detail_level = validate_bazi_payload(payload)
        cache = _successful_request_cache(tool_context)
        cache_key = _successful_request_cache_key(action, arguments, detail_level)
        cached = cache.get(cache_key)
        if isinstance(cached, dict):
            result = deepcopy(cached)
            result["requestId"] = request_id
            result["duplicateRequestSuppressed"] = True
            _remember_current_result(tool_context, result)
            return result
        response = bridge_manager.invoke(
            action,
            arguments,
            detail_level=detail_level,
            tool_context=tool_context,
            request_id=request_id,
        )
        result = _render_bridge_response(response)
        if result.get("ok") is True:
            cache[cache_key] = deepcopy(result)
            _remember_current_result(tool_context, result)
        return result
    except BaziInputError as exc:
        return _error_envelope(
            action=action,
            request_id=request_id,
            error_code=exc.error_code,
            message=str(exc),
        )
    except BaziBridgeError as exc:
        diagnostics = []
        if exc.diagnostics is not None:
            diagnostics.append(
                {
                    "reason": exc.diagnostics.reason,
                    "elapsedMs": exc.diagnostics.elapsed_ms,
                    "exitCode": exc.diagnostics.exit_code,
                    "stderrTruncated": exc.diagnostics.stderr_truncated,
                }
            )
        return _error_envelope(
            action=action,
            request_id=request_id,
            error_code=exc.error_code,
            message=str(exc),
            retryable=exc.retryable,
            degraded_diagnostics=diagnostics,
        )


def validate_bazi_payload(payload: Mapping[str, object]) -> tuple[dict, str]:
    if not isinstance(payload, Mapping):
        raise BaziInputError("bazi_bridge_invalid_request", "Bazi payload must be an object")
    action = payload.get("action")
    if action in {"chart", "dayun"}:
        return _validate_birth_payload(payload)
    if action == "resolve_pillars":
        return _validate_resolve_payload(payload), "default"
    raise BaziInputError("bazi_action_unsupported", "action must be chart, dayun, or resolve_pillars")


def _validate_birth_payload(payload: Mapping[str, object]) -> tuple[dict, str]:
    allowed = set(_BIRTH_PROPERTIES)
    _reject_extra_fields(payload, allowed)
    required = ("gender", "birthYear", "birthMonth", "birthDay", "birthHour")
    for field in required:
        if field not in payload:
            raise BaziInputError("bazi_bridge_invalid_request", f"{field} is required")
    gender = payload["gender"]
    if gender not in {"male", "female"}:
        raise BaziInputError("bazi_bridge_invalid_request", "gender must be male or female")
    year = _bounded_integer(payload["birthYear"], "birthYear", 1901, 2100)
    month = _bounded_integer(payload["birthMonth"], "birthMonth", 1, 12)
    day = _bounded_integer(payload["birthDay"], "birthDay", 1, 31)
    hour = _bounded_integer(payload["birthHour"], "birthHour", 0, 23)
    minute = _bounded_integer(payload.get("birthMinute", 0), "birthMinute", 0, 59)
    calendar_type = payload.get("calendarType", "solar")
    if calendar_type not in {"solar", "lunar"}:
        raise BaziInputError("bazi_bridge_invalid_request", "calendarType must be solar or lunar")
    is_leap_month = _coerce_boolean(payload.get("isLeapMonth", False), "isLeapMonth")
    if is_leap_month and calendar_type != "lunar":
        raise BaziInputError("bazi_bridge_invalid_request", "isLeapMonth requires lunar calendarType")
    if calendar_type == "solar":
        try:
            date(year, month, day)
        except ValueError as exc:
            raise BaziInputError("bazi_bridge_invalid_request", "birth date is not a valid solar date") from exc
    elif day > 30:
        raise BaziInputError("bazi_bridge_invalid_request", "lunar birthDay must be between 1 and 30")
    timezone = payload.get("timezone", "Asia/Shanghai")
    if timezone != "Asia/Shanghai":
        raise BaziInputError("bazi_timezone_unsupported", "timezone must be Asia/Shanghai")
    source_standard = payload.get("sourceTimeStandard", "recorded_civil")
    if source_standard not in {"recorded_civil", "beijing_standard"}:
        raise BaziInputError("bazi_bridge_invalid_request", "sourceTimeStandard is invalid")
    time_basis = payload.get("timeBasis", "clock")
    if time_basis not in {"clock", "true_solar"}:
        raise BaziInputError("bazi_bridge_invalid_request", "timeBasis must be clock or true_solar")
    birth_place = payload.get("birthPlace")
    if birth_place is not None and not isinstance(birth_place, str):
        raise BaziInputError("bazi_bridge_invalid_request", "birthPlace must be text")
    normalized_place = (
        " ".join(unicodedata.normalize("NFKC", birth_place).split())
        if isinstance(birth_place, str)
        else None
    )
    if time_basis == "true_solar" and not normalized_place:
        raise BaziInputError("bazi_birth_place_required", "birthPlace is required for true_solar")
    if normalized_place is not None and not 2 <= len(normalized_place) <= 200:
        raise BaziInputError("bazi_bridge_invalid_request", "birthPlace length must be between 2 and 200")
    detail_level = "full" if payload.get("action") == "dayun" else payload.get("detailLevel", "default")
    if detail_level not in {"default", "full"}:
        raise BaziInputError("bazi_bridge_invalid_request", "detailLevel must be default or full")
    arguments = {
        "gender": gender,
        "birthYear": year,
        "birthMonth": month,
        "birthDay": day,
        "birthHour": hour,
        "birthMinute": minute,
        "calendarType": calendar_type,
        "isLeapMonth": is_leap_month,
        "timeBasis": time_basis,
        "timezone": timezone,
        "sourceTimeStandard": source_standard,
    }
    if normalized_place is not None:
        arguments["birthPlace"] = normalized_place
    return arguments, str(detail_level)


def _validate_resolve_payload(payload: Mapping[str, object]) -> dict:
    fields = ("yearPillar", "monthPillar", "dayPillar", "hourPillar")
    _reject_extra_fields(payload, {"action", "gender", *fields})
    gender = payload.get("gender")
    if gender is not None and gender not in {"male", "female"}:
        raise BaziInputError("bazi_bridge_invalid_request", "gender must be male or female")
    arguments: dict[str, str] = {}
    for field in fields:
        value = payload.get(field)
        if not isinstance(value, str) or value not in _JIAZI:
            raise BaziInputError("bazi_bridge_invalid_request", f"{field} must be a valid Jiazi")
        arguments[field] = value
    return arguments


def _bounded_integer(value: object, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.isascii() and normalized.isdigit():
            value = int(normalized)
    if isinstance(value, bool) or not isinstance(value, int):
        raise BaziInputError("bazi_bridge_invalid_request", f"{field} must be an integer")
    if not minimum <= value <= maximum:
        code = "bazi_birth_year_unsupported" if field == "birthYear" else "bazi_bridge_invalid_request"
        raise BaziInputError(code, f"{field} must be between {minimum} and {maximum}")
    return value


def _coerce_boolean(value: object, field: str) -> bool:
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    if not isinstance(value, bool):
        raise BaziInputError("bazi_bridge_invalid_request", f"{field} must be boolean")
    return value


def _reject_extra_fields(payload: Mapping[str, object], allowed: set[str]) -> None:
    extra = sorted(set(payload) - allowed)
    if extra:
        raise BaziInputError("bazi_bridge_invalid_request", f"Unsupported field: {extra[0]}")


def _successful_request_cache(tool_context: dict | None) -> dict:
    if not isinstance(tool_context, dict):
        return {}
    state = tool_context.get("turn_tool_state")
    if not isinstance(state, dict):
        return {}
    cache = state.setdefault(_RESULT_CACHE_NAMESPACE, {})
    if not isinstance(cache, dict):
        raise ValueError(f"tool_context turn state {_RESULT_CACHE_NAMESPACE} must be a dictionary")
    return cache


def _successful_request_cache_key(action: str, arguments: Mapping[str, object], detail_level: str) -> tuple:
    return action, detail_level, tuple(sorted(arguments.items()))


def _remember_current_result(tool_context: dict | None, result: dict[str, object]) -> None:
    state = (tool_context or {}).get("turn_tool_state")
    if isinstance(state, dict):
        state[CURRENT_RESULT_STATE_KEY] = deepcopy(result)
        by_action = state.setdefault(RESULTS_BY_ACTION_STATE_KEY, {})
        if isinstance(by_action, dict):
            action = str(result.get("action") or "")
            if action:
                by_action[action] = deepcopy(result)


def _render_bridge_response(response: dict) -> dict:
    if not response["ok"]:
        return {**response, "is_error": True}
    normalized = dict(response["normalizedTime"] or {}) if response["normalizedTime"] is not None else None
    if normalized is not None and isinstance(normalized.get("placeResolution"), dict):
        place = dict(normalized["placeResolution"])
        place.pop("resolvedLongitude", None)
        place.pop("resolvedLatitude", None)
        normalized["placeResolution"] = place
    return {
        "ok": True,
        "protocolVersion": response["protocolVersion"],
        "requestId": response["requestId"],
        "action": response["action"],
        "resultSchemaVersion": response["resultSchemaVersion"],
        "engine": dict(response["engine"]),
        "inputFingerprint": response["inputFingerprint"],
        "timeBasis": normalized,
        "result": dict(response["structuredContent"]),
        "degradedDiagnostics": list(response.get("degradedDiagnostics") or []),
    }


def _error_envelope(
    *,
    action: str,
    request_id: str,
    error_code: str,
    message: str,
    retryable: bool = False,
    degraded_diagnostics: list[dict] | None = None,
) -> dict:
    return {
        "ok": False,
        "is_error": True,
        "protocolVersion": PROTOCOL_VERSION,
        "requestId": request_id,
        "action": action if action in RESULT_SCHEMAS else None,
        "resultSchemaVersion": RESULT_SCHEMAS.get(action),
        "engine": dict(ENGINE),
        "inputFingerprint": None,
        "error": {"code": error_code, "message": message, "retryable": retryable},
        "degradedDiagnostics": list(degraded_diagnostics or []),
    }
