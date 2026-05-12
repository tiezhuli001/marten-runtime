from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from marten_runtime.interfaces.http.app import create_app
from tests.support.event_loop import close_idle_event_loop


REPO_ROOT = Path(__file__).resolve().parents[1]


class EvalHTTPRoutesTests(unittest.TestCase):
    def _build_eval_app(self):
        temp_dir = tempfile.TemporaryDirectory()
        repo_root = Path(temp_dir.name)
        shutil.copytree(REPO_ROOT / "config", repo_root / "config")
        shutil.copytree(REPO_ROOT / "apps", repo_root / "apps")
        shutil.copytree(REPO_ROOT / "skills", repo_root / "skills")
        if (REPO_ROOT / "mcps.example.json").exists():
            shutil.copy2(REPO_ROOT / "mcps.example.json", repo_root / "mcps.example.json")
            shutil.copy2(REPO_ROOT / "mcps.example.json", repo_root / "mcps.json")
        self._write_smoke_suite(repo_root)
        app = create_app(
            repo_root=repo_root,
            env={
                "OPENAI_API_KEY": "test-key",
                "MINIMAX_API_KEY": "test-key",
                "MARTEN_REPO_SLUG": "tiezhuli001/marten-runtime",
                "MARTEN_REPO_URL": "https://github.com/tiezhuli001/marten-runtime",
                "MARTEN_REPO_BRANCH": "main",
            },
            load_env_file=False,
        )
        runtime = app.state.runtime
        runtime.channels_config = runtime.channels_config.model_copy(
            update={
                "feishu": runtime.channels_config.feishu.model_copy(
                    update={"enabled": False, "auto_start": False}
                )
            }
        )
        return app, temp_dir

    def _write_smoke_suite(self, repo_root: Path) -> None:
        suites_root = repo_root / "evals" / "suites"
        cases_root = repo_root / "evals" / "cases" / "ops_smoke"
        suites_root.mkdir(parents=True, exist_ok=True)
        cases_root.mkdir(parents=True, exist_ok=True)
        (suites_root / "ops_smoke.toml").write_text(
            '\n'.join(
                [
                    'suite_id = "ops_smoke"',
                    'description = "Eval ops HTTP smoke suite"',
                    'default_mode = "scripted"',
                    'scripted_supported = true',
                    'required_dependencies = ["provider"]',
                    'baseline_policy = "latest_passed_auto"',
                    'grader_id = "main_chain_core"',
                    'case_files = ["evals/cases/ops_smoke/direct_answer_cn.toml"]',
                    '',
                ]
            ),
            encoding="utf-8",
        )
        (cases_root / "direct_answer_cn.toml").write_text(
            '\n'.join(
                [
                    'case_id = "direct_answer_cn"',
                    'suite_id = "ops_smoke"',
                    'family = "direct_answer"',
                    'enabled = true',
                    'required = true',
                    'description = "direct answer smoke"',
                    'agent_id = "main"',
                    'profile_name = "openai_gpt_5_4"',
                    'tags = ["cn", "direct"]',
                    '',
                    '[[turns]]',
                    'role = "user"',
                    'content = "你好"',
                    '',
                    '[setup]',
                    'session_history_fixture = "none"',
                    'memory_fixture = "none"',
                    'automation_fixture = "none"',
                    '',
                    '[expectations.final_text]',
                    'contains_any = ["你好"]',
                    '',
                    '[expectations.efficiency]',
                    'max_llm_requests = 1',
                    'max_tool_calls = 0',
                    '',
                    '[expectations.context]',
                    'expect_compaction = false',
                    '',
                    '[expectations.diagnostics]',
                    'expect_provider_ref = "openai"',
                    '',
                    '[weights]',
                    'outcome = 80',
                    'tool_path = 0',
                    'efficiency = 15',
                    'context = 5',
                    '',
                ]
            ),
            encoding="utf-8",
        )

    def _cleanup_app(self, app, temp_dir: tempfile.TemporaryDirectory) -> None:  # noqa: ANN001
        runtime = app.state.runtime
        worker = getattr(runtime, "compaction_worker", None)
        if worker is not None:
            worker.stop()
        runtime.subagent_service.shutdown()
        close_idle_event_loop()
        temp_dir.cleanup()

    def test_eval_ops_lists_suites_and_renders_home(self) -> None:
        app, temp_dir = self._build_eval_app()
        try:
            with TestClient(app) as client:
                suites_response = client.get("/evals/suites", headers={"accept": "application/json"})
                suites_html_response = client.get("/evals/suites")
                home_response = client.get("/evals")
                runs_response = client.get("/evals/runs", headers={"accept": "application/json"})
                runs_html_response = client.get("/evals/runs")

            self.assertEqual(suites_response.status_code, 200)
            self.assertEqual(suites_html_response.status_code, 200)
            self.assertEqual(home_response.status_code, 200)
            self.assertEqual(runs_response.status_code, 200)
            self.assertEqual(runs_html_response.status_code, 200)
            self.assertIn("application/json", suites_response.headers["content-type"])
            self.assertIn("application/json", runs_response.headers["content-type"])
            self.assertIn("ops_smoke", {item["suite_id"] for item in suites_response.json()["items"]})
            self.assertIn("text/html", suites_html_response.headers["content-type"])
            self.assertIn("评测套件", suites_html_response.text)
            self.assertIn("套件清单", suites_html_response.text)
            self.assertIn("text/html", runs_html_response.headers["content-type"])
            self.assertIn("历史运行记录", runs_html_response.text)
            self.assertIn("text/html", home_response.headers["content-type"])
            self.assertIn("评测总览", home_response.text)
            self.assertIn("运行记录", home_response.text)
            self.assertIn("总分变化", home_response.text)
            self.assertIn("报告", home_response.text)
            self.assertEqual(runs_response.json()["items"], [])
        finally:
            self._cleanup_app(app, temp_dir)

    def test_eval_ops_runs_scripted_suite_and_serves_artifacts(self) -> None:
        app, temp_dir = self._build_eval_app()
        try:
            with TestClient(app) as client:
                create_response = client.post(
                    "/evals/runs",
                    json={
                        "suite_id": "ops_smoke",
                        "mode": "scripted",
                        "profile": "openai_gpt_5_4",
                        "baseline": "latest_passed",
                    },
                )
                self.assertEqual(create_response.status_code, 200, create_response.text)
                job_id = create_response.json()["job_id"]
                job_payload = self._wait_for_job(client, job_id)
                eval_run_id = job_payload["eval_run_id"]
                run_response = client.get(f"/evals/runs/{eval_run_id}")
                view_response = client.get(f"/evals/runs/{eval_run_id}/view")
                report_response = client.get(f"/evals/reports/{eval_run_id}")
                recent_response = client.get("/evals/runs?include_report=true", headers={"accept": "application/json"})
                recent_html_response = client.get("/evals/runs")

            self.assertEqual(job_payload["status"], "passed")
            self.assertEqual(run_response.status_code, 200)
            self.assertEqual(view_response.status_code, 200)
            self.assertEqual(report_response.status_code, 200)
            run_payload = run_response.json()
            self.assertEqual(run_payload["summary"]["suite_id"], "ops_smoke")
            self.assertEqual(run_payload["case_count"], 1)
            self.assertTrue(run_payload["artifacts"]["summary_exists"])
            self.assertIn("compare_result", run_payload)
            self.assertIn("stability_result", run_payload)
            self.assertIn("provider_reliability", run_payload)
            self.assertIn("retry_count", run_payload["provider_reliability"])
            self.assertIn("text/html", view_response.headers["content-type"])
            self.assertIn("direct_answer_cn", view_response.text)
            self.assertIn("对比结果", view_response.text)
            self.assertIn("用例明细", view_response.text)
            self.assertIn("查看完整报告", view_response.text)
            self.assertIn("Provider 评估", view_response.text)
            self.assertIn("Provider 状态", view_response.text)
            self.assertIn("健康", view_response.text)
            self.assertIn("运维冒烟链路", view_response.text)
            self.assertIn("原始 ID", view_response.text)
            self.assertIn("重试", view_response.text)
            self.assertIn("回退", view_response.text)
            self.assertIn("空输出", view_response.text)
            self.assertIn("text/html", report_response.headers["content-type"])
            self.assertIn("text/html", recent_html_response.headers["content-type"])
            self.assertIn("application/json", recent_response.headers["content-type"])
            self.assertIn("历史运行记录", recent_html_response.text)
            self.assertIn("Provider 评估", recent_html_response.text)
            self.assertIn("Provider 状态", recent_html_response.text)
            self.assertIn("Provider 重试", recent_html_response.text)
            self.assertIn("重试", recent_html_response.text)
            self.assertIn("回退", recent_html_response.text)
            self.assertIn("空输出", recent_html_response.text)
            self.assertIn("查看报告", recent_html_response.text)
            recent_item = recent_response.json()["items"][0]
            self.assertEqual(recent_item["eval_run_id"], eval_run_id)
            self.assertEqual(recent_item["report_url"], f"/evals/reports/{eval_run_id}")
            self.assertIn("compare_result", recent_item)
            self.assertIn("provider_reliability", recent_item)
            self.assertIn("retry_count", recent_item)
            self.assertIn("fallback_count", recent_item)
            self.assertIn("empty_output_count", recent_item)
        finally:
            self._cleanup_app(app, temp_dir)

    def test_eval_ops_rejects_unknown_suite_and_preserves_messages_path(self) -> None:
        app, temp_dir = self._build_eval_app()
        try:
            with TestClient(app) as client:
                missing_response = client.post(
                    "/evals/runs",
                    json={"suite_id": "missing", "mode": "scripted", "profile": "openai_gpt_5_4"},
                )
                traversal_response = client.post(
                    "/evals/runs",
                    json={"suite_id": "../ops_smoke", "mode": "scripted", "profile": "openai_gpt_5_4"},
                )
                empty_suite_response = client.post(
                    "/evals/runs",
                    json={"suite_id": "", "mode": "scripted", "profile": "openai_gpt_5_4"},
                )
                message_response = client.post(
                    "/messages",
                    json={
                        "channel_id": "http",
                        "user_id": "demo",
                        "conversation_id": "conv-eval-ops-smoke",
                        "message_id": "msg-eval-ops-smoke-1",
                        "body": "hello",
                    },
                )

            self.assertEqual(missing_response.status_code, 404)
            self.assertEqual(traversal_response.status_code, 404)
            self.assertEqual(empty_suite_response.status_code, 422)
            self.assertEqual(message_response.status_code, 200)
            payload = message_response.json()
            self.assertIn("session_id", payload)
            self.assertIn(payload["events"][-1]["event_type"], {"final", "error"})
            self.assertIsNotNone(payload.get("text"))
        finally:
            self._cleanup_app(app, temp_dir)

    def test_eval_ops_resolves_relative_artifact_paths_against_repo_root(self) -> None:
        app, temp_dir = self._build_eval_app()
        try:
            with TestClient(app) as client:
                create_response = client.post(
                    "/evals/runs",
                    json={
                        "suite_id": "ops_smoke",
                        "mode": "scripted",
                        "profile": "openai_gpt_5_4",
                    },
                )
                self.assertEqual(create_response.status_code, 200, create_response.text)
                job_payload = self._wait_for_job(client, create_response.json()["job_id"])
                eval_run_id = job_payload["eval_run_id"]
                repo_root = Path(temp_dir.name)
                relative_root = Path("reports/evals") / eval_run_id
                absolute_root = repo_root / relative_root
                for child in absolute_root.iterdir():
                    target = relative_root / child.name
                    child.rename(repo_root / target)
                from marten_runtime.evals.store import SQLiteEvalStore

                SQLiteEvalStore(repo_root / "data/evals.sqlite3").record_run_start(
                    SQLiteEvalStore(repo_root / "data/evals.sqlite3").get_run(eval_run_id).model_copy(
                        update={"artifact_root": str(relative_root)}
                    )
                )
                run_response = client.get(f"/evals/runs/{eval_run_id}")
                report_response = client.get(f"/evals/reports/{eval_run_id}")

            self.assertEqual(run_response.status_code, 200)
            self.assertTrue(run_response.json()["artifacts"]["html_exists"])
            self.assertTrue(run_response.json()["artifacts"]["markdown_exists"])
            self.assertEqual(report_response.status_code, 200)
            self.assertIn("text/html", report_response.headers["content-type"])
        finally:
            self._cleanup_app(app, temp_dir)

    def _wait_for_job(self, client: TestClient, job_id: str) -> dict[str, object]:
        terminal = {"passed", "failed", "blocked"}
        deadline = time.monotonic() + 30
        payload: dict[str, object] = {}
        while time.monotonic() < deadline:
            response = client.get(f"/evals/jobs/{job_id}")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            if payload["status"] in terminal:
                return payload
            time.sleep(0.1)
        self.fail(f"eval job did not finish: {payload}")


if __name__ == "__main__":
    unittest.main()
