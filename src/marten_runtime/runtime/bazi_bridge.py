from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from uuid import uuid4


PROTOCOL_VERSION = "1"
ENGINE = {
    "name": "taibu-core-marten",
    "version": "3.4.0-marten.1",
    "sourceCommit": "1f7f8920ef2c2b032401427623ac0b9a7496c68d",
    "patchId": "sect1-v1",
}
RESULT_SCHEMAS = {
    "chart": "bazi.chart.v1",
    "dayun": "bazi.dayun.v1",
    "resolve_pillars": "bazi.resolve_pillars.v1",
}
PLACE_PROVIDER = "amap"
PLACE_RESOLVER_VERSION = "taibu-14860a2-marten-v1"
PLACE_CACHE_NAMESPACE = "bazi.place_resolution"
PLACE_ERROR_CODES = frozenset(
    {
        "bazi_birth_place_required",
        "bazi_birth_place_unsupported",
        "bazi_place_ambiguous",
        "bazi_place_invalid_result",
        "bazi_place_precision_insufficient",
        "bazi_place_resolution_failed",
        "bazi_place_resolution_timeout",
        "bazi_place_resolver_unavailable",
    }
)
_FINGERPRINT_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_CHILD_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "NODE_EXTRA_CA_CERTS",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
)


@dataclass(frozen=True)
class BaziBridgeDiagnostics:
    elapsed_ms: int
    exit_code: int | None
    stderr: str
    stderr_truncated: bool
    reason: str | None = None


class BaziBridgeError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        retryable: bool = False,
        diagnostics: BaziBridgeDiagnostics | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.retryable = retryable
        self.diagnostics = diagnostics


class _BoundedReader(threading.Thread):
    def __init__(self, stream, limit: int) -> None:
        super().__init__(daemon=True)
        self._stream = stream
        self._limit = limit
        self.data = bytearray()
        self.exceeded = threading.Event()

    def run(self) -> None:
        try:
            read_chunk = getattr(self._stream, "read1", self._stream.read)
            while chunk := read_chunk(8192):
                remaining = self._limit + 1 - len(self.data)
                if remaining > 0:
                    self.data.extend(chunk[:remaining])
                if len(self.data) > self._limit:
                    self.exceeded.set()
        finally:
            self._stream.close()


class BaziBridgeManager:
    DEFAULT_TIMEOUT_SECONDS = 10.0
    MAX_STDOUT_BYTES = 1_048_576
    MAX_STDERR_BYTES = 16_384
    POLL_INTERVAL_SECONDS = 0.01
    PLACE_TIMEOUT_SECONDS = 3.0
    AMAP_ENDPOINT_HOST = "restapi.amap.com:443"
    SUPPORTED_REGION = "cn_mainland"

    def __init__(
        self,
        *,
        repo_root: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        node_path: str | Path | None = None,
        bridge_path: str | Path | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_stdout_bytes: int = MAX_STDOUT_BYTES,
        max_stderr_bytes: int = MAX_STDERR_BYTES,
    ) -> None:
        self.repo_root = (
            Path(repo_root).resolve()
            if repo_root is not None
            else Path(__file__).resolve().parents[3]
        )
        self.env = dict(env or {})
        self.node_path = self._resolve_node_path(node_path)
        self.bridge_path = (
            Path(bridge_path).expanduser().resolve()
            if bridge_path is not None
            else (self.repo_root / "third_party" / "taibu_bridge" / "index.mjs").resolve()
        )
        self.timeout_seconds = float(timeout_seconds)
        self.max_stdout_bytes = int(max_stdout_bytes)
        self.max_stderr_bytes = int(max_stderr_bytes)
        if self.timeout_seconds <= 0 or self.max_stdout_bytes <= 0 or self.max_stderr_bytes <= 0:
            raise ValueError("Bazi bridge limits must be positive")

    def diagnostics_summary(self) -> dict[str, object]:
        bridge_configured = bool(
            self.node_path is not None
            and self.node_path.is_file()
            and self.bridge_path.is_file()
        )
        key_configured = bool(str(self.env.get("AMAP_WEB_SERVICE_KEY") or "").strip())
        return {
            "bridge": {
                "configured": bridge_configured,
                "node_version": self._node_version() if bridge_configured else None,
                "protocol_version": PROTOCOL_VERSION,
                "timeout_seconds": self.timeout_seconds,
                "max_stdout_bytes": self.max_stdout_bytes,
                "max_stderr_bytes": self.max_stderr_bytes,
            },
            "place_resolution": {
                "provider": PLACE_PROVIDER,
                "configured": key_configured,
                "reason": None if key_configured else "credential_missing",
                "api_key_env": "AMAP_WEB_SERVICE_KEY",
                "endpoint_host": self.AMAP_ENDPOINT_HOST,
                "timeout_seconds": self.PLACE_TIMEOUT_SECONDS,
                "supported_region": self.SUPPORTED_REGION,
                "resolver_version": PLACE_RESOLVER_VERSION,
            },
        }

    def invoke(
        self,
        action: str,
        arguments: Mapping[str, object],
        *,
        detail_level: str = "default",
        tool_context: dict | None = None,
        request_id: str | None = None,
    ) -> dict:
        if action not in RESULT_SCHEMAS:
            raise ValueError(f"Unsupported Bazi action: {action}")
        if detail_level not in {"default", "full"}:
            raise ValueError("detail_level must be default or full")

        request_id = request_id or f"bazi_{uuid4().hex}"
        request = {
            "protocolVersion": PROTOCOL_VERSION,
            "requestId": request_id,
            "tool": action,
            "arguments": dict(arguments),
            "detailLevel": detail_level,
        }
        cache_key = self._place_cache_key(action, arguments)
        cache = self._place_cache(tool_context)
        cached = cache.get(cache_key) if cache_key is not None else None
        if cached is not None:
            if cached["kind"] == "success":
                request["resolvedPlace"] = dict(cached["resolvedPlace"])
            else:
                return self._cached_error_response(
                    request_id=request_id,
                    action=action,
                    cached=cached,
                )

        include_amap_key = cache_key is not None and "resolvedPlace" not in request
        response = self._run_process(
            request,
            tool_context=tool_context,
            include_amap_key=include_amap_key,
        )
        self._validate_response(response, request=request)

        if cache_key is not None and cached is None:
            if response["ok"]:
                place = response["normalizedTime"]["placeResolution"]
                cache[cache_key] = {"kind": "success", "resolvedPlace": dict(place)}
            elif response["error"]["code"] in PLACE_ERROR_CODES:
                cache[cache_key] = {
                    "kind": "error",
                    "error": dict(response["error"]),
                    "degradedDiagnostics": list(response.get("degradedDiagnostics") or []),
                }
        return response

    def _run_process(
        self,
        request: dict,
        *,
        tool_context: dict | None,
        include_amap_key: bool,
    ) -> dict:
        self._require_available()
        child_env = self._build_child_env(include_amap_key=include_amap_key)
        started = time.monotonic()
        timeout = self._effective_timeout(tool_context, started)
        stop_event = (tool_context or {}).get("stop_event")
        try:
            process = subprocess.Popen(
                [str(self.node_path), str(self.bridge_path)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=child_env,
                start_new_session=True,
            )
        except (OSError, ValueError) as exc:
            raise BaziBridgeError(
                "bazi_bridge_unavailable",
                "Bazi bridge process could not be started",
                diagnostics=BaziBridgeDiagnostics(0, None, "", False, type(exc).__name__),
            ) from exc

        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_reader = _BoundedReader(process.stdout, self.max_stdout_bytes)
        stderr_reader = _BoundedReader(process.stderr, self.max_stderr_bytes)
        stdout_reader.start()
        stderr_reader.start()
        try:
            process.stdin.write(
                json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                + b"\n"
            )
            process.stdin.close()
        except (BrokenPipeError, OSError):
            pass

        failure_code: str | None = None
        failure_reason: str | None = None
        while process.poll() is None:
            if stdout_reader.exceeded.is_set():
                failure_code = "bazi_bridge_invalid_output"
                failure_reason = "stdout_limit_exceeded"
                break
            if stderr_reader.exceeded.is_set():
                failure_code = "bazi_bridge_invalid_output"
                failure_reason = "stderr_limit_exceeded"
                break
            if stop_event is not None and getattr(stop_event, "is_set", lambda: False)():
                failure_code = "bazi_bridge_cancelled"
                failure_reason = "cancelled"
                break
            if time.monotonic() - started >= timeout:
                failure_code = "bazi_bridge_timeout"
                failure_reason = "deadline_exceeded"
                break
            time.sleep(self.POLL_INTERVAL_SECONDS)

        if failure_code is not None:
            self._kill_process_group(process)
        process.wait()
        stdout_reader.join(timeout=1.0)
        stderr_reader.join(timeout=1.0)
        elapsed_ms = round((time.monotonic() - started) * 1000)
        stderr = bytes(stderr_reader.data[: self.max_stderr_bytes]).decode(
            "utf-8", errors="replace"
        )
        diagnostics = BaziBridgeDiagnostics(
            elapsed_ms=elapsed_ms,
            exit_code=process.returncode,
            stderr=self._redact(stderr, request=request),
            stderr_truncated=stderr_reader.exceeded.is_set(),
            reason=failure_reason,
        )
        if failure_code is not None:
            raise BaziBridgeError(
                failure_code,
                self._failure_message(failure_code),
                retryable=failure_code in {"bazi_bridge_timeout", "bazi_bridge_cancelled"},
                diagnostics=diagnostics,
            )
        if stderr_reader.exceeded.is_set() or stdout_reader.exceeded.is_set():
            reason = (
                "stdout_limit_exceeded"
                if stdout_reader.exceeded.is_set()
                else "stderr_limit_exceeded"
            )
            raise BaziBridgeError(
                "bazi_bridge_invalid_output",
                "Bazi bridge output exceeded its byte limit",
                diagnostics=BaziBridgeDiagnostics(
                    diagnostics.elapsed_ms,
                    diagnostics.exit_code,
                    diagnostics.stderr,
                    diagnostics.stderr_truncated,
                    reason,
                ),
            )
        if process.returncode != 0:
            reason = "signal_exit" if process.returncode < 0 else "nonzero_exit"
            raise BaziBridgeError(
                "bazi_bridge_process_failed",
                "Bazi bridge process failed",
                diagnostics=BaziBridgeDiagnostics(
                    elapsed_ms, process.returncode, self._redact(stderr, request=request),
                    stderr_reader.exceeded.is_set(), reason,
                ),
            )
        return self._decode_stdout(bytes(stdout_reader.data), diagnostics=diagnostics)

    def _decode_stdout(self, output: bytes, *, diagnostics: BaziBridgeDiagnostics) -> dict:
        try:
            text = output.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise self._invalid_output("stdout_invalid_utf8", diagnostics) from exc
        lines = text.splitlines()
        if len(lines) != 1 or not lines[0]:
            reason = "stdout_empty" if not lines else "stdout_multiline"
            raise self._invalid_output(reason, diagnostics)
        try:
            response = json.loads(lines[0])
        except json.JSONDecodeError as exc:
            raise self._invalid_output("stdout_invalid_json", diagnostics) from exc
        if not isinstance(response, dict):
            raise self._invalid_output("stdout_not_object", diagnostics)
        return response

    def _validate_response(self, response: dict, *, request: dict) -> None:
        if response.get("protocolVersion") != PROTOCOL_VERSION:
            raise BaziBridgeError(
                "bazi_bridge_protocol_mismatch",
                "Bazi bridge protocol version does not match the runtime",
            )
        expected = {
            "requestId": request["requestId"],
            "action": request["tool"],
            "resultSchemaVersion": RESULT_SCHEMAS[request["tool"]],
            "engine": ENGINE,
        }
        for field, value in expected.items():
            if response.get(field) != value:
                raise BaziBridgeError(
                    "bazi_bridge_invalid_output",
                    f"Bazi bridge response has an invalid {field}",
                )
        if not isinstance(response.get("ok"), bool):
            raise BaziBridgeError("bazi_bridge_invalid_output", "Bazi bridge response has invalid ok")
        if not isinstance(response.get("degradedDiagnostics"), list):
            raise BaziBridgeError(
                "bazi_bridge_invalid_output", "Bazi bridge response has invalid diagnostics"
            )
        if response["ok"]:
            self._validate_success_response(response, request=request)
        else:
            self._validate_error_response(response)

    def _validate_success_response(self, response: dict, *, request: dict) -> None:
        action = request["tool"]
        fingerprint = response.get("inputFingerprint")
        if not isinstance(fingerprint, str) or not _FINGERPRINT_PATTERN.fullmatch(fingerprint):
            raise BaziBridgeError(
                "bazi_bridge_invalid_output", "Bazi bridge response has invalid fingerprint"
            )
        if not isinstance(response.get("structuredContent"), dict):
            raise BaziBridgeError(
                "bazi_bridge_invalid_output", "Bazi bridge response has invalid structured content"
            )
        normalized = response.get("normalizedTime")
        if action == "resolve_pillars":
            if normalized is not None:
                raise BaziBridgeError(
                    "bazi_bridge_invalid_output", "Resolve response has unexpected normalized time"
                )
            expected_fingerprint = self._fingerprint_resolve(request["arguments"])
            if fingerprint != expected_fingerprint:
                raise BaziBridgeError(
                    "bazi_bridge_invalid_output", "Resolve response fingerprint does not match input"
                )
            return
        if not isinstance(normalized, dict):
            raise BaziBridgeError(
                "bazi_bridge_invalid_output", "Birth response has invalid normalized time"
            )
        required = {
            "requested",
            "timezone",
            "sourceTimeStandard",
            "sourceUtcOffsetMinutes",
            "dstAdjustmentMinutes",
            "placeResolution",
            "sourceCalendarType",
            "sourceIsLeapMonth",
            "effectiveCalendarType",
            "effectiveBirthDateTime",
            "trueSolarAlgorithm",
            "dayBoundaryPolicy",
            "qiyunMethod",
        }
        if not required.issubset(normalized):
            raise BaziBridgeError(
                "bazi_bridge_invalid_output", "Birth response is missing normalized time fields"
            )
        if normalized["timezone"] != "Asia/Shanghai":
            raise BaziBridgeError(
                "bazi_bridge_invalid_output", "Birth response has invalid timezone"
            )
        if normalized["dayBoundaryPolicy"] != "lunar_javascript_sect1":
            raise BaziBridgeError(
                "bazi_bridge_invalid_output", "Birth response has invalid day boundary policy"
            )
        if normalized["qiyunMethod"] != "lunar_javascript_yun_sect1":
            raise BaziBridgeError(
                "bazi_bridge_invalid_output", "Birth response has invalid qiyun method"
            )
        expected_basis = request["arguments"].get("timeBasis", "clock")
        if normalized["requested"] != expected_basis:
            raise BaziBridgeError(
                "bazi_bridge_invalid_output", "Birth response time basis does not match input"
            )
        place = normalized["placeResolution"]
        if normalized["requested"] == "true_solar":
            self._validate_place(place)
        elif normalized["requested"] == "clock" and place is not None:
            raise BaziBridgeError(
                "bazi_bridge_invalid_output", "Clock response has unexpected place resolution"
            )
        if fingerprint != self._fingerprint_birth(request["arguments"], normalized):
            raise BaziBridgeError(
                "bazi_bridge_invalid_output", "Birth response fingerprint does not match input"
            )

    @staticmethod
    def _fingerprint_birth(arguments: Mapping[str, object], normalized: Mapping[str, object]) -> str:
        place = normalized.get("placeResolution")
        place = place if isinstance(place, dict) else {}
        payload = {
            "schemaVersion": "bazi.input.v1",
            "gender": arguments.get("gender"),
            "sourceCalendarType": normalized.get("sourceCalendarType"),
            "sourceIsLeapMonth": normalized.get("sourceIsLeapMonth"),
            "sourceTimeStandard": normalized.get("sourceTimeStandard"),
            "sourceUtcOffsetMinutes": normalized.get("sourceUtcOffsetMinutes"),
            "dstAdjustmentMinutes": normalized.get("dstAdjustmentMinutes"),
            "effectiveBirthDateTime": normalized.get("effectiveBirthDateTime"),
            "timeBasis": normalized.get("requested"),
            "timezone": normalized.get("timezone"),
            "placeProvider": place.get("provider"),
            "placeResolverVersion": place.get("resolverVersion"),
            "placeAdcode": place.get("adcode"),
            "placeLevel": place.get("level"),
            "coordinateSystem": place.get("coordinateSystem"),
            "resolvedLongitude": place.get("resolvedLongitude"),
            "trueSolarAlgorithm": normalized.get("trueSolarAlgorithm"),
            "dayBoundaryPolicy": normalized.get("dayBoundaryPolicy"),
            "qiyunMethod": normalized.get("qiyunMethod"),
        }
        return BaziBridgeManager._fingerprint(payload)

    @staticmethod
    def _fingerprint_resolve(arguments: Mapping[str, object]) -> str:
        return BaziBridgeManager._fingerprint(
            {
                "schemaVersion": "bazi.resolve-input.v1",
                "yearPillar": arguments.get("yearPillar"),
                "monthPillar": arguments.get("monthPillar"),
                "dayPillar": arguments.get("dayPillar"),
                "hourPillar": arguments.get("hourPillar"),
            }
        )

    @staticmethod
    def _fingerprint(payload: Mapping[str, object]) -> str:
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(canonical).hexdigest()}"

    @staticmethod
    def _validate_error_response(response: dict) -> None:
        error = response.get("error")
        if not isinstance(error, dict):
            raise BaziBridgeError("bazi_bridge_invalid_output", "Bazi bridge error is missing")
        if not isinstance(error.get("code"), str) or not error["code"]:
            raise BaziBridgeError("bazi_bridge_invalid_output", "Bazi bridge error code is invalid")
        if not isinstance(error.get("message"), str) or not isinstance(error.get("retryable"), bool):
            raise BaziBridgeError("bazi_bridge_invalid_output", "Bazi bridge error payload is invalid")
        if response.get("inputFingerprint") is not None:
            raise BaziBridgeError(
                "bazi_bridge_invalid_output", "Failed bridge response has a fingerprint"
            )

    @staticmethod
    def _validate_place(place: object) -> None:
        if not isinstance(place, dict):
            raise BaziBridgeError(
                "bazi_bridge_invalid_output", "True-solar response has invalid place resolution"
            )
        expected_strings = {
            "provider": PLACE_PROVIDER,
            "resolverVersion": PLACE_RESOLVER_VERSION,
            "coordinateSystem": "gcj02",
        }
        for field, value in expected_strings.items():
            if place.get(field) != value:
                raise BaziBridgeError(
                    "bazi_bridge_invalid_output", f"Place resolution has invalid {field}"
                )
        for field in ("formattedAddress", "adcode", "level"):
            if not isinstance(place.get(field), str) or not place[field]:
                raise BaziBridgeError(
                    "bazi_bridge_invalid_output", f"Place resolution has invalid {field}"
                )
        longitude = place.get("resolvedLongitude")
        latitude = place.get("resolvedLatitude")
        if isinstance(longitude, bool) or not isinstance(longitude, (int, float)) or not -180 <= longitude <= 180:
            raise BaziBridgeError(
                "bazi_bridge_invalid_output", "Place resolution has invalid longitude"
            )
        if isinstance(latitude, bool) or not isinstance(latitude, (int, float)) or not -90 <= latitude <= 90:
            raise BaziBridgeError(
                "bazi_bridge_invalid_output", "Place resolution has invalid latitude"
            )

    def _place_cache(self, tool_context: dict | None) -> dict:
        if tool_context is None:
            return {}
        state = tool_context.get("turn_tool_state")
        if not isinstance(state, dict):
            return {}
        cache = state.setdefault(PLACE_CACHE_NAMESPACE, {})
        if not isinstance(cache, dict):
            raise ValueError(f"tool_context turn state {PLACE_CACHE_NAMESPACE} must be a dictionary")
        return cache

    @staticmethod
    def _place_cache_key(action: str, arguments: Mapping[str, object]) -> str | None:
        if action not in {"chart", "dayun"} or arguments.get("timeBasis", "clock") != "true_solar":
            return None
        place = arguments.get("birthPlace")
        if not isinstance(place, str):
            return f"{PLACE_PROVIDER}:{PLACE_RESOLVER_VERSION}:"
        normalized = " ".join(unicodedata.normalize("NFKC", place).split())
        return f"{PLACE_PROVIDER}:{PLACE_RESOLVER_VERSION}:{normalized}"

    @staticmethod
    def _cached_error_response(*, request_id: str, action: str, cached: dict) -> dict:
        return {
            "ok": False,
            "protocolVersion": PROTOCOL_VERSION,
            "requestId": request_id,
            "action": action,
            "resultSchemaVersion": RESULT_SCHEMAS[action],
            "engine": dict(ENGINE),
            "inputFingerprint": None,
            "error": dict(cached["error"]),
            "degradedDiagnostics": list(cached.get("degradedDiagnostics") or []),
        }

    def _build_child_env(self, *, include_amap_key: bool) -> dict[str, str]:
        child = {"TZ": "UTC", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
        for key in _CHILD_ENV_KEYS:
            value = str(self.env.get(key) or "").strip()
            if value:
                child[key] = value
        if include_amap_key:
            key = str(self.env.get("AMAP_WEB_SERVICE_KEY") or "").strip()
            if key:
                child["AMAP_WEB_SERVICE_KEY"] = key
        return child

    def _effective_timeout(self, tool_context: dict | None, started: float) -> float:
        timeout = self.timeout_seconds
        deadline = (tool_context or {}).get("deadline_monotonic")
        if deadline is not None:
            timeout = min(timeout, max(0.0, float(deadline) - started))
        override = (tool_context or {}).get("timeout_seconds_override")
        if override is not None:
            timeout = min(timeout, max(0.0, float(override)))
        return timeout

    def _require_available(self) -> None:
        if self.node_path is None or not self.node_path.is_file():
            raise BaziBridgeError("bazi_bridge_unavailable", "Node runtime is unavailable")
        if not self.bridge_path.is_file():
            raise BaziBridgeError("bazi_bridge_unavailable", "Bazi bridge is unavailable")

    def _resolve_node_path(self, node_path: str | Path | None) -> Path | None:
        if node_path is not None:
            return Path(node_path).expanduser().resolve()
        found = shutil.which("node", path=self.env.get("PATH") or os.environ.get("PATH"))
        return Path(found).resolve() if found else None

    def _node_version(self) -> str | None:
        if self.node_path is None:
            return None
        try:
            result = subprocess.run(
                [str(self.node_path), "--version"],
                capture_output=True,
                check=False,
                env=self._build_child_env(include_amap_key=False),
                timeout=2.0,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0 or len(result.stdout) > 100:
            return None
        version = result.stdout.decode("ascii", errors="ignore").strip()
        return version or None

    @staticmethod
    def _kill_process_group(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            process.wait()
            return
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            # The short-lived bridge can exit between poll() and killpg(). On
            # macOS that race may surface as EPERM instead of ESRCH.
            try:
                process.kill()
            except ProcessLookupError:
                pass
        process.wait()

    def _redact(self, value: str, *, request: Mapping[str, object] | None = None) -> str:
        secrets = [
            str(self.env.get("AMAP_WEB_SERVICE_KEY") or ""),
            *(str(self.env.get(key) or "") for key in _CHILD_ENV_KEYS),
        ]
        redacted = value
        for secret in sorted((item for item in secrets if item), key=len, reverse=True):
            redacted = redacted.replace(secret, "[REDACTED]")
        arguments = (request or {}).get("arguments")
        if isinstance(arguments, dict):
            for field in (
                "birthPlace",
                "birthYear",
                "birthMonth",
                "birthDay",
                "birthHour",
                "birthMinute",
                "yearPillar",
                "monthPillar",
                "dayPillar",
                "hourPillar",
            ):
                if field not in arguments:
                    continue
                encoded = re.escape(
                    json.dumps(arguments[field], ensure_ascii=False, separators=(",", ":"))
                )
                redacted = re.sub(
                    rf'("{field}"\s*:\s*){encoded}',
                    rf'\1"[REDACTED]"',
                    redacted,
                )
                if field == "birthPlace" and isinstance(arguments[field], str):
                    redacted = redacted.replace(arguments[field], "[REDACTED]")
        redacted = re.sub(r"\b(?:19|20|21)\d{2}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?\b", "[REDACTED]", redacted)
        return redacted

    @staticmethod
    def _failure_message(code: str) -> str:
        return {
            "bazi_bridge_timeout": "Bazi bridge execution timed out",
            "bazi_bridge_cancelled": "Bazi bridge execution was cancelled",
            "bazi_bridge_invalid_output": "Bazi bridge output exceeded its byte limit",
        }[code]

    @staticmethod
    def _invalid_output(reason: str, diagnostics: BaziBridgeDiagnostics) -> BaziBridgeError:
        return BaziBridgeError(
            "bazi_bridge_invalid_output",
            "Bazi bridge returned invalid output",
            diagnostics=BaziBridgeDiagnostics(
                diagnostics.elapsed_ms,
                diagnostics.exit_code,
                diagnostics.stderr,
                diagnostics.stderr_truncated,
                reason,
            ),
        )
