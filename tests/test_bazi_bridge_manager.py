from __future__ import annotations

import hashlib
import json
import os
import signal
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from marten_runtime.runtime.bazi_bridge import (
    BaziBridgeError,
    BaziBridgeManager,
    ENGINE,
    PLACE_RESOLVER_VERSION,
)


FAKE_BRIDGE = r'''
import hashlib
import json
import os
import pathlib
import signal
import subprocess
import sys
import time

request = json.loads(sys.stdin.readline())
mode = os.environ.get("FAKE_MODE", "success")
record_path = os.environ.get("FAKE_RECORD_PATH")
if record_path:
    path = pathlib.Path(record_path)
    records = json.loads(path.read_text()) if path.exists() else []
    records.append({
        "request": request,
        "env": dict(os.environ),
        "providerCalled": "resolvedPlace" not in request,
    })
    path.write_text(json.dumps(records))

if mode == "sleep":
    time.sleep(30)
if mode == "grandchild":
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    pathlib.Path(os.environ["FAKE_PID_PATH"]).write_text(str(child.pid))
    time.sleep(30)
if mode == "nonzero":
    sys.exit(7)
if mode == "signal":
    os.kill(os.getpid(), signal.SIGTERM)
if mode == "leak":
    print(json.dumps(request, ensure_ascii=False), file=sys.stderr)
    print(os.environ.get("AMAP_WEB_SERVICE_KEY"), file=sys.stderr)
    print(os.environ.get("HTTPS_PROXY"), file=sys.stderr)
    sys.exit(9)
if mode == "empty":
    sys.exit(0)
if mode == "multiline":
    print("{}")
    print("{}")
    sys.exit(0)
if mode == "corrupt":
    print("not-json")
    sys.exit(0)
if mode == "stdout_large":
    print("x" * 4096)
    sys.exit(0)
if mode == "stderr_large":
    print("x" * 4096, file=sys.stderr)
    time.sleep(30)

action = request["tool"]
schemas = {
    "chart": "bazi.chart.v1",
    "dayun": "bazi.dayun.v1",
    "resolve_pillars": "bazi.resolve_pillars.v1",
}
engine = {
    "name": "taibu-core-marten",
    "version": "3.4.0-marten.1",
    "sourceCommit": "1f7f8920ef2c2b032401427623ac0b9a7496c68d",
    "patchId": "sect1-v1",
}
base = {
    "protocolVersion": "1",
    "requestId": request["requestId"],
    "action": action,
    "resultSchemaVersion": schemas[action],
    "engine": engine,
    "inputFingerprint": None,
    "degradedDiagnostics": [],
}
if mode == "place_error":
    response = {"ok": False, **base, "error": {
        "code": "bazi_place_resolution_failed",
        "message": "Place not found",
        "retryable": False,
    }}
else:
    normalized = None
    if action != "resolve_pillars":
        true_solar = request["arguments"].get("timeBasis") == "true_solar"
        place = request.get("resolvedPlace") if true_solar else None
        if true_solar and place is None:
            place = {
                "provider": "amap",
                "resolverVersion": "taibu-14860a2-marten-v1",
                "formattedAddress": "四川省成都市武侯区",
                "adcode": "510107",
                "level": "区县",
                "coordinateSystem": "gcj02",
                "resolvedLongitude": 104.04,
                "resolvedLatitude": 30.64,
            }
        normalized = {
            "requested": "true_solar" if true_solar else "clock",
            "timezone": "Asia/Shanghai",
            "sourceTimeStandard": "beijing_standard",
            "sourceUtcOffsetMinutes": 480,
            "dstAdjustmentMinutes": 0,
            "placeResolution": place,
            "sourceCalendarType": "solar",
            "sourceIsLeapMonth": False,
            "effectiveCalendarType": "solar",
            "effectiveBirthDateTime": "1988-02-15T22:12:00",
            "trueSolarAlgorithm": "taibu_true_solar_v1" if true_solar else None,
            "dayBoundaryPolicy": "lunar_javascript_sect1",
            "qiyunMethod": "lunar_javascript_yun_sect1",
        }
    if action == "resolve_pillars":
        fingerprint_payload = {
            "schemaVersion": "bazi.resolve-input.v1",
            "yearPillar": request["arguments"].get("yearPillar"),
            "monthPillar": request["arguments"].get("monthPillar"),
            "dayPillar": request["arguments"].get("dayPillar"),
            "hourPillar": request["arguments"].get("hourPillar"),
        }
    else:
        place = normalized["placeResolution"] or {}
        fingerprint_payload = {
            "schemaVersion": "bazi.input.v1",
            "gender": request["arguments"].get("gender"),
            "sourceCalendarType": normalized["sourceCalendarType"],
            "sourceIsLeapMonth": normalized["sourceIsLeapMonth"],
            "sourceTimeStandard": normalized["sourceTimeStandard"],
            "sourceUtcOffsetMinutes": normalized["sourceUtcOffsetMinutes"],
            "dstAdjustmentMinutes": normalized["dstAdjustmentMinutes"],
            "effectiveBirthDateTime": normalized["effectiveBirthDateTime"],
            "timeBasis": normalized["requested"],
            "timezone": normalized["timezone"],
            "placeProvider": place.get("provider"),
            "placeResolverVersion": place.get("resolverVersion"),
            "placeAdcode": place.get("adcode"),
            "placeLevel": place.get("level"),
            "coordinateSystem": place.get("coordinateSystem"),
            "resolvedLongitude": place.get("resolvedLongitude"),
            "trueSolarAlgorithm": normalized["trueSolarAlgorithm"],
            "dayBoundaryPolicy": normalized["dayBoundaryPolicy"],
            "qiyunMethod": normalized["qiyunMethod"],
        }
    canonical = json.dumps(
        fingerprint_payload, ensure_ascii=False, separators=(",", ":")
    ).encode()
    fingerprint = "sha256:" + hashlib.sha256(canonical).hexdigest()
    response = {
        "ok": True,
        **base,
        "inputFingerprint": fingerprint,
        "structuredContent": {"action": action},
        "normalizedTime": normalized,
    }

if mode == "protocol_mismatch":
    response["protocolVersion"] = "2"
if mode == "request_mismatch":
    response["requestId"] = "wrong"
if mode == "engine_mismatch":
    response["engine"] = {**engine, "patchId": "wrong"}
if mode == "fingerprint_mismatch":
    response["inputFingerprint"] = "bad"
if mode == "normalized_mismatch" and response.get("normalizedTime"):
    del response["normalizedTime"]["dayBoundaryPolicy"]
print(json.dumps(response, ensure_ascii=False))
'''


class BaziBridgeManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.bridge = self.root / "fake_bridge.py"
        self.bridge.write_text(FAKE_BRIDGE, encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def manager(self, *, mode: str = "success", **kwargs) -> BaziBridgeManager:
        env = {
            "FAKE_MODE": mode,
            "PATH": "/must/not/leak",
            "AMAP_WEB_SERVICE_KEY": "amap-secret",
            "UNRELATED_SECRET": "must-not-leak",
            **kwargs.pop("env", {}),
        }
        # Fake-only controls are allowlisted through an executable wrapper.
        wrapper = self.root / f"wrapper-{mode}-{uuid4().hex}.sh"
        controls = [f"FAKE_MODE={mode!r}"]
        for key in ("FAKE_RECORD_PATH", "FAKE_PID_PATH"):
            if key in env:
                controls.append(f"{key}={env[key]!r}")
        wrapper.write_text(
            "#!/bin/sh\n" + " ".join(controls) + f" exec {sys.executable!r} \"$@\"\n",
            encoding="utf-8",
        )
        wrapper.chmod(0o755)
        return BaziBridgeManager(
            node_path=wrapper,
            bridge_path=self.bridge,
            env=env,
            **kwargs,
        )

    @staticmethod
    def clock_arguments() -> dict:
        return {
            "gender": "male",
            "birthYear": 1988,
            "birthMonth": 2,
            "birthDay": 15,
            "birthHour": 23,
            "birthMinute": 30,
            "calendarType": "solar",
            "timeBasis": "clock",
        }

    @classmethod
    def true_solar_arguments(cls, place: str = "四川省 成都市 武侯区") -> dict:
        return {**cls.clock_arguments(), "timeBasis": "true_solar", "birthPlace": place}

    def test_real_bridge_success_validates_full_contract(self) -> None:
        manager = BaziBridgeManager(env={})

        response = manager.invoke(
            "chart", self.clock_arguments(), request_id="req_real_bridge"
        )

        self.assertTrue(response["ok"])
        self.assertEqual(response["engine"], ENGINE)
        self.assertEqual(response["requestId"], "req_real_bridge")

    def test_missing_node_and_bridge_are_stable_unavailable_errors(self) -> None:
        for node, bridge in (
            (self.root / "missing-node", self.bridge),
            (Path(sys.executable), self.root / "missing-bridge"),
        ):
            with self.subTest(node=node, bridge=bridge):
                manager = BaziBridgeManager(node_path=node, bridge_path=bridge)
                with self.assertRaises(BaziBridgeError) as raised:
                    manager.invoke("chart", self.clock_arguments())
                self.assertEqual(raised.exception.error_code, "bazi_bridge_unavailable")

    def test_timeout_and_cancellation_return_stable_errors(self) -> None:
        manager = self.manager(mode="sleep", timeout_seconds=0.08)
        with self.assertRaises(BaziBridgeError) as timed_out:
            manager.invoke("chart", self.clock_arguments())
        self.assertEqual(timed_out.exception.error_code, "bazi_bridge_timeout")

        stop_event = threading.Event()
        timer = threading.Timer(0.05, stop_event.set)
        timer.start()
        try:
            with self.assertRaises(BaziBridgeError) as cancelled:
                self.manager(mode="sleep", timeout_seconds=2).invoke(
                    "chart", self.clock_arguments(), tool_context={"stop_event": stop_event}
                )
        finally:
            timer.cancel()
        self.assertEqual(cancelled.exception.error_code, "bazi_bridge_cancelled")

    def test_tool_deadline_caps_manager_timeout(self) -> None:
        manager = self.manager(mode="sleep", timeout_seconds=2)
        started = time.monotonic()
        with self.assertRaises(BaziBridgeError) as raised:
            manager.invoke(
                "chart",
                self.clock_arguments(),
                tool_context={"deadline_monotonic": time.monotonic() + 0.06},
            )
        self.assertEqual(raised.exception.error_code, "bazi_bridge_timeout")
        self.assertLess(time.monotonic() - started, 0.5)

    def test_timeout_kills_child_and_grandchild_process_group(self) -> None:
        pid_path = self.root / "grandchild.pid"
        manager = self.manager(
            mode="grandchild",
            timeout_seconds=2.0,
            env={"FAKE_PID_PATH": str(pid_path)},
        )
        with self.assertRaises(BaziBridgeError) as raised:
            manager.invoke("chart", self.clock_arguments())
        self.assertEqual(raised.exception.error_code, "bazi_bridge_timeout")
        self.assertTrue(pid_path.exists())
        pid = int(pid_path.read_text())
        for _ in range(100):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.01)
        else:
            self.fail(f"grandchild process {pid} survived process-group termination")

    def test_nonzero_and_signal_exit_are_distinguished_in_diagnostics(self) -> None:
        for mode, reason in (("nonzero", "nonzero_exit"), ("signal", "signal_exit")):
            with self.subTest(mode=mode):
                with self.assertRaises(BaziBridgeError) as raised:
                    self.manager(mode=mode).invoke("chart", self.clock_arguments())
                self.assertEqual(raised.exception.error_code, "bazi_bridge_process_failed")
                self.assertEqual(raised.exception.diagnostics.reason, reason)

    def test_failure_diagnostics_redact_birth_fields_and_secrets(self) -> None:
        manager = self.manager(
            mode="leak", env={"HTTPS_PROXY": "http://proxy-user:proxy-password@example"}
        )

        with self.assertRaises(BaziBridgeError) as raised:
            manager.invoke("chart", self.true_solar_arguments())

        diagnostics = raised.exception.diagnostics.stderr
        for sensitive in (
            "amap-secret",
            "proxy-password",
            "四川省 成都市 武侯区",
            "1988",
            '"birthMonth": 2',
            '"birthDay": 15',
            '"birthHour": 23',
            '"birthMinute": 30',
        ):
            self.assertNotIn(sensitive, diagnostics)
        self.assertIn("[REDACTED]", diagnostics)

    def test_empty_multiline_corrupt_and_oversized_output_are_rejected(self) -> None:
        cases = {
            "empty": "stdout_empty",
            "multiline": "stdout_multiline",
            "corrupt": "stdout_invalid_json",
            "stdout_large": "stdout_limit_exceeded",
            "stderr_large": "stderr_limit_exceeded",
        }
        for mode, reason in cases.items():
            with self.subTest(mode=mode):
                with self.assertRaises(BaziBridgeError) as raised:
                    self.manager(
                        mode=mode,
                        max_stdout_bytes=512,
                        max_stderr_bytes=512,
                        timeout_seconds=1,
                    ).invoke("chart", self.clock_arguments())
                self.assertEqual(raised.exception.error_code, "bazi_bridge_invalid_output")
                self.assertEqual(raised.exception.diagnostics.reason, reason)

    def test_protocol_request_engine_fingerprint_and_normalized_time_are_validated(self) -> None:
        cases = {
            "protocol_mismatch": "bazi_bridge_protocol_mismatch",
            "request_mismatch": "bazi_bridge_invalid_output",
            "engine_mismatch": "bazi_bridge_invalid_output",
            "fingerprint_mismatch": "bazi_bridge_invalid_output",
            "normalized_mismatch": "bazi_bridge_invalid_output",
        }
        for mode, code in cases.items():
            with self.subTest(mode=mode):
                with self.assertRaises(BaziBridgeError) as raised:
                    self.manager(mode=mode).invoke("chart", self.clock_arguments())
                self.assertEqual(raised.exception.error_code, code)

    def test_child_environment_is_allowlisted_and_key_only_reaches_provider_call(self) -> None:
        record_path = self.root / "records.json"
        manager = self.manager(
            env={
                "FAKE_RECORD_PATH": str(record_path),
                "HTTPS_PROXY": "http://proxy-secret",
            }
        )
        state: dict = {}
        context = {"turn_tool_state": state}

        first = manager.invoke("chart", self.true_solar_arguments(), tool_context=context)
        second = manager.invoke("dayun", self.true_solar_arguments(), tool_context=context)

        self.assertTrue(first["ok"] and second["ok"])
        records = json.loads(record_path.read_text())
        self.assertEqual([item["providerCalled"] for item in records], [True, False])
        self.assertEqual(records[0]["env"]["AMAP_WEB_SERVICE_KEY"], "amap-secret")
        self.assertNotIn("AMAP_WEB_SERVICE_KEY", records[1]["env"])
        self.assertNotIn("UNRELATED_SECRET", records[0]["env"])
        self.assertNotIn("PATH", records[0]["env"])
        self.assertEqual(records[0]["env"]["TZ"], "UTC")
        self.assertEqual(records[0]["env"]["LANG"], "C.UTF-8")
        self.assertNotIn("proxy-secret", json.dumps(first))
        cache = state["bazi.place_resolution"]
        key = f"amap:{PLACE_RESOLVER_VERSION}:四川省 成都市 武侯区"
        self.assertEqual(cache[key]["kind"], "success")

    def test_place_failures_are_cached_for_the_current_run(self) -> None:
        record_path = self.root / "failed-records.json"
        manager = self.manager(
            mode="place_error", env={"FAKE_RECORD_PATH": str(record_path)}
        )
        context = {"turn_tool_state": {}}

        first = manager.invoke("chart", self.true_solar_arguments(), tool_context=context)
        second = manager.invoke("dayun", self.true_solar_arguments(), tool_context=context)

        self.assertFalse(first["ok"] or second["ok"])
        self.assertEqual(second["action"], "dayun")
        self.assertEqual(second["resultSchemaVersion"], "bazi.dayun.v1")
        self.assertEqual(len(json.loads(record_path.read_text())), 1)

    def test_concurrent_runs_have_isolated_place_caches(self) -> None:
        record_path = self.root / "concurrent-records.json"
        write_lock = threading.Lock()
        # Separate files avoid making the fake process counter itself a race source.
        def run(index: int) -> tuple[dict, dict]:
            local_record = self.root / f"run-{index}.json"
            manager = self.manager(env={"FAKE_RECORD_PATH": str(local_record)})
            state: dict = {}
            result = manager.invoke(
                "chart", self.true_solar_arguments(), tool_context={"turn_tool_state": state}
            )
            with write_lock:
                records = json.loads(local_record.read_text())
                existing = json.loads(record_path.read_text()) if record_path.exists() else []
                record_path.write_text(json.dumps(existing + records))
            return result, state

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(run, (1, 2)))

        self.assertTrue(all(result["ok"] for result, _ in outcomes))
        self.assertIsNot(outcomes[0][1], outcomes[1][1])
        records = json.loads(record_path.read_text())
        self.assertEqual([item["providerCalled"] for item in records], [True, True])


if __name__ == "__main__":
    unittest.main()
