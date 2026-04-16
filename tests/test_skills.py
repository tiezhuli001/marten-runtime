import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from marten_runtime.skills.filter import filter_skills
from marten_runtime.skills import loader as loader_module
from marten_runtime.skills.loader import SkillLoader
from marten_runtime.skills.render import build_skill_heads, render_always_on_skills, render_skill_heads
from marten_runtime.skills.selector import select_activated_skills
from marten_runtime.skills.service import SkillService
from marten_runtime.skills.snapshot import SkillSnapshot
from tests.support.skill_builders import write_skill


class SkillTests(unittest.TestCase):
    def _build_single_skill_heads(
        self,
        body: str,
        *,
        skill_id: str = "repo_helper",
    ) -> list:
        with tempfile.TemporaryDirectory() as tmp:
            skills_root = Path(tmp) / "skills"
            write_skill(skills_root, skill_id, body)
            return build_skill_heads(SkillLoader([str(skills_root)]).load_all())

    def test_repo_feishu_formatting_skill_constrains_trending_order_and_rank_markers(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent
        skill_body = (repo_root / "skills" / "feishu_channel_formatting" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("preserve the original repository order returned by the MCP result", skill_body)
        self.assertIn("do not re-rank, sort, or regroup trending items", skill_body)
        self.assertIn("do not use alphabetical markers like `a.` / `b.` / `c.`", skill_body)

    def test_loader_reads_single_level_skills_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            skills = base / "skills"
            write_skill(
                skills,
                "repo_helper",
                """
                ---
                skill_id: repo_helper
                name: Repo Helper
                description: repo version
                enabled: true
                agents: [main]
                channels: [http]
                tags: [repo]
                ---
                Repo body
                """,
            )
            nested = skills / "nested" / "ignored"
            nested.mkdir(parents=True, exist_ok=True)
            (nested / "SKILL.md").write_text(
                textwrap.dedent(
                    """
                    ---
                    skill_id: ignored_nested
                    name: Ignored Nested
                    description: should not be discovered
                    enabled: true
                    agents: [main]
                    channels: [http]
                    ---
                    Ignored body
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )
            loader = SkillLoader([str(skills)])

            skills = loader.load_all()

            self.assertEqual([skill.meta.skill_id for skill in skills], ["repo_helper"])
            self.assertIsNone(skills[0].body)
            self.assertEqual(skills[0].meta.source_scope, "skills")

    def test_loader_can_load_one_skill_body_on_demand(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            skills = base / "skills"
            write_skill(
                skills,
                "repo_helper",
                """
                ---
                skill_id: repo_helper
                name: Repo Helper
                description: repo version
                enabled: true
                agents: [main]
                channels: [http]
                tags: [repo]
                ---
                Repo body
                """,
            )
            loader = SkillLoader([str(skills)])

            skill = loader.load_skill("repo_helper")

            self.assertEqual(skill.meta.skill_id, "repo_helper")
            self.assertEqual(skill.body, "Repo body")

    def test_loader_load_all_uses_head_only_parse_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            skills = base / "skills"
            write_skill(
                skills,
                "repo_helper",
                """
                ---
                skill_id: repo_helper
                name: Repo Helper
                description: repo version
                enabled: true
                agents: [main]
                channels: [http]
                tags: [repo]
                ---
                Repo body
                """,
            )
            loader = SkillLoader([str(skills)])

            with (
                patch.object(loader_module, "parse_skill_head_markdown", wraps=loader_module.parse_skill_head_markdown) as parse_head,
                patch.object(loader_module, "parse_skill_body_markdown", wraps=loader_module.parse_skill_body_markdown) as parse_body,
            ):
                skills = loader.load_all()

            self.assertEqual([skill.meta.skill_id for skill in skills], ["repo_helper"])
            self.assertEqual(parse_head.call_count, 1)
            self.assertEqual(parse_body.call_count, 0)

    def test_loader_load_skill_uses_full_body_parse_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            skills = base / "skills"
            write_skill(
                skills,
                "repo_helper",
                """
                ---
                skill_id: repo_helper
                name: Repo Helper
                description: repo version
                enabled: true
                agents: [main]
                channels: [http]
                tags: [repo]
                ---
                Repo body
                """,
            )
            loader = SkillLoader([str(skills)])

            with (
                patch.object(loader_module, "parse_skill_head_markdown", wraps=loader_module.parse_skill_head_markdown) as parse_head,
                patch.object(loader_module, "parse_skill_body_markdown", wraps=loader_module.parse_skill_body_markdown) as parse_body,
            ):
                skill = loader.load_skill("repo_helper")

            self.assertEqual(skill.body, "Repo body")
            self.assertEqual(parse_head.call_count, 0)
            self.assertEqual(parse_body.call_count, 1)

    def test_filter_render_and_snapshot_keep_only_visible_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            system = base / "system"
            write_skill(
                system,
                "example_time",
                """
                ---
                skill_id: example_time
                name: Example Time
                description: visible skill
                enabled: true
                always_on: true
                agents: [main]
                channels: [http]
                tags: [time]
                ---
                Always on body
                """,
            )
            write_skill(
                system,
                "repo_helper",
                """
                ---
                skill_id: repo_helper
                name: Repo Helper
                description: hidden from http
                enabled: true
                agents: [main]
                channels: [cli]
                tags: [repo]
                requires_env: [REPO_TOKEN]
                ---
                Helper body
                """,
            )
            loader = SkillLoader([str(system)])
            visible = filter_skills(
                agent_id="main",
                channel_id="http",
                items=loader.load_all(),
                env={},
                config={},
            )
            heads = build_skill_heads(visible)
            snapshot = SkillSnapshot.from_skills("skill_snapshot_1", visible)
            self.assertEqual([item.meta.skill_id for item in visible], ["example_time"])
            self.assertEqual(render_always_on_skills(visible), "")
            self.assertEqual(heads, [])
            self.assertEqual(snapshot.always_on_ids, ["example_time"])

    def test_skill_service_builds_startup_snapshot_and_loads_always_on_body_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            system = base / "skills"
            write_skill(
                system,
                "example_time",
                """
                ---
                skill_id: example_time
                name: Example Time
                description: visible skill
                enabled: true
                always_on: true
                agents: [main]
                channels: [http]
                tags: [time]
                ---
                Always on body
                """,
            )
            write_skill(
                system,
                "repo_helper",
                """
                ---
                skill_id: repo_helper
                name: Repo Helper
                description: repo assistance
                enabled: true
                agents: [main]
                channels: [http]
                tags: [repo]
                ---
                Repo helper body
                """,
            )
            service = SkillService([str(system)])

            with (
                patch.object(service.loader, "load_all", wraps=service.loader.load_all) as load_all,
                patch.object(service.loader, "load_skill", wraps=service.loader.load_skill) as load_skill,
            ):
                runtime = service.build_runtime(agent_id="main", channel_id="http", env={}, config={})

            self.assertEqual(runtime.snapshot.always_on_ids, ["example_time"])
            self.assertEqual([head.skill_id for head in runtime.snapshot.heads], ["repo_helper"])
            self.assertEqual(runtime.always_on_text, "Always on body")
            self.assertIsNone(runtime.visible_skills[0].body)
            self.assertIsNone(runtime.visible_skills[1].body)
            self.assertEqual(load_all.call_count, 1)
            self.assertEqual(load_skill.call_count, 1)
            self.assertEqual(load_skill.call_args.args[0], "example_time")

    def test_skill_service_runtime_prefers_compact_skill_heads_under_default_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            system = base / "skills"
            for skill_id in ["alpha_skill", "beta_skill", "gamma_skill"]:
                write_skill(
                    system,
                    skill_id,
                    f"""
                    ---
                    skill_id: {skill_id}
                    name: {skill_id}
                    description: this is a deliberately long description for {skill_id} to force compact rendering in runtime startup payloads
                    enabled: true
                    agents: [main]
                    channels: [http]
                    ---
                    Body for {skill_id}
                    """,
                )
            service = SkillService([str(system)])

            runtime = service.build_runtime(agent_id="main", channel_id="http", env={}, config={})

            self.assertEqual(
                runtime.skill_heads_text,
                "Visible skills:\n- alpha_skill\n- beta_skill\n- gamma_skill",
            )

    def test_render_skill_heads_switches_between_full_and_compact_formats(self) -> None:
        cases = [
            {
                "body": """
                ---
                skill_id: repo_helper
                name: Repo Helper
                description: repo assistance
                enabled: true
                agents: [main]
                channels: [http]
                aliases: [repo]
                ---
                Repo helper body
                """,
                "max_chars": 500,
                "expected_compact": False,
                "expected_truncated": False,
                "expected_text": "Visible skills:\n- repo_helper: repo assistance Aliases: repo.",
            },
            {
                "body": """
                ---
                skill_id: repo_helper
                name: Repo Helper
                description: repo assistance with longer description text
                enabled: true
                agents: [main]
                channels: [http]
                aliases: [repo]
                ---
                Repo helper body
                """,
                "max_chars": 50,
                "expected_compact": True,
                "expected_truncated": False,
                "expected_text": "Visible skills:\n- repo_helper",
            },
        ]

        for case in cases:
            with self.subTest(max_chars=case["max_chars"]):
                heads = self._build_single_skill_heads(case["body"])
                rendered = render_skill_heads(heads, max_chars=case["max_chars"], max_items=10)
                self.assertEqual(rendered.compact, case["expected_compact"])
                self.assertEqual(rendered.truncated, case["expected_truncated"])
                self.assertEqual(rendered.text, case["expected_text"])

    def test_render_skill_heads_truncates_compact_format_when_still_over_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            skills_root = base / "skills"
            write_skill(
                skills_root,
                "repo_helper",
                """
                ---
                skill_id: repo_helper
                name: Repo Helper
                description: repo assistance
                enabled: true
                agents: [main]
                channels: [http]
                ---
                Repo helper body
                """,
            )
            write_skill(
                skills_root,
                "time_helper",
                """
                ---
                skill_id: time_helper
                name: Time Helper
                description: time assistance
                enabled: true
                agents: [main]
                channels: [http]
                ---
                Time helper body
                """,
            )
            heads = build_skill_heads(SkillLoader([str(skills_root)]).load_all())

            rendered = render_skill_heads(heads, max_chars=20, max_items=10)

            self.assertTrue(rendered.compact)
            self.assertTrue(rendered.truncated)
            self.assertEqual(rendered.truncated_reason, "max_chars")
            self.assertEqual(rendered.text, "Visible skills:\n- re")

    def test_render_skill_heads_keeps_stable_order_and_item_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            skills_root = base / "skills"
            write_skill(
                skills_root,
                "b_skill",
                """
                ---
                skill_id: b_skill
                name: B Skill
                description: second
                enabled: true
                agents: [main]
                channels: [http]
                ---
                B body
                """,
            )
            write_skill(
                skills_root,
                "a_skill",
                """
                ---
                skill_id: a_skill
                name: A Skill
                description: first
                enabled: true
                agents: [main]
                channels: [http]
                ---
                A body
                """,
            )
            heads = build_skill_heads(SkillLoader([str(skills_root)]).load_all())

            rendered = render_skill_heads(heads, max_chars=500, max_items=1)

            self.assertFalse(rendered.compact)
            self.assertTrue(rendered.truncated)
            self.assertEqual(rendered.truncated_reason, "max_items")
            self.assertEqual(rendered.text, "Visible skills:\n- a_skill: first")

    def test_selector_only_activates_explicit_skill_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            system = base / "skills"
            write_skill(
                system,
                "repo_helper",
                """
                ---
                skill_id: repo_helper
                name: Repo Helper
                description: repo assistance
                enabled: true
                agents: [main]
                channels: [http]
                tags: [repo, git]
                ---
                Repo helper body
                """,
            )
            loader = SkillLoader([str(system)])
            visible = filter_skills(
                agent_id="main",
                channel_id="http",
                items=loader.load_all(),
                env={},
                config={},
            )

            activated = select_activated_skills(visible, "Use repo_helper to inspect the git repo.")

            self.assertEqual(activated, [])

    def test_selector_explicitly_activates_skill_by_id_for_automation_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            shared = base / "skills"
            write_skill(
                shared,
                "github_trending_digest",
                """
                ---
                skill_id: github_trending_digest
                name: GitHub Hot Repos Digest
                description: daily hot repositories digest
                enabled: true
                agents: [main]
                channels: [feishu, http]
                tags: [github, trending]
                ---
                Digest body
                """,
            )
            loader = SkillLoader([str(shared)])
            visible = filter_skills(
                agent_id="main",
                channel_id="feishu",
                items=loader.load_all(),
                env={},
                config={},
            )

            activated = select_activated_skills(
                visible,
                "Run the scheduled digest.",
                explicit_skill_ids=["github_trending_digest"],
            )

            self.assertEqual([item.meta.skill_id for item in activated], ["github_trending_digest"])

    def test_selector_does_not_activate_skill_by_alias_for_natural_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            shared = base / "skills"
            write_skill(
                shared,
                "github_trending_digest",
                """
                ---
                skill_id: github_trending_digest
                name: GitHub Hot Repos Digest
                description: build a concise daily digest for fast-moving GitHub repositories
                enabled: true
                agents: [main]
                channels: [feishu, http]
                tags: [github, trending, digest]
                aliases: ["GitHub 热门项目摘要", "GitHub 热门仓库", "GitHub trending", "今日开源热榜"]
                ---
                Digest body
                """,
            )
            loader = SkillLoader([str(shared)])
            visible = filter_skills(
                agent_id="main",
                channel_id="feishu",
                items=loader.load_all(),
                env={},
                config={},
            )

            activated = select_activated_skills(
                visible,
                "请给我一份今日开源热榜，关注今天讨论度高的仓库。",
            )

            self.assertEqual(activated, [])

    def test_self_improve_management_skill_content_allows_candidate_delete_only(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        skill_path = repo_root / "skills/self_improve_management/SKILL.md"

        self.assertTrue(skill_path.exists())
        body = skill_path.read_text(encoding="utf-8")

        self.assertIn("action=list_candidates", body)
        self.assertIn("action=candidate_detail", body)
        self.assertIn("action=delete_candidate", body)
        self.assertIn("must not delete active lessons", body)

    def test_self_improve_skill_content_stays_narrow_and_does_not_allow_agents_rewrite(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        skill_path = repo_root / "skills/self_improve/SKILL.md"

        self.assertTrue(skill_path.exists())
        body = skill_path.read_text(encoding="utf-8")

        self.assertIn("action=list_evidence", body)
        self.assertIn("action=save_candidate", body)
        self.assertIn("list_system_lessons", body)
        self.assertIn("repeated failures and later recoveries", body)
        self.assertIn("Do not edit AGENTS.md", body)

    def test_self_improve_review_skill_stays_classification_only(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        skill_path = repo_root / "skills/self_improve_review/SKILL.md"

        self.assertTrue(skill_path.exists())
        body = skill_path.read_text(encoding="utf-8")

        self.assertIn("classification-only", body)
        self.assertIn("structured JSON only", body)
        self.assertIn("Do not edit AGENTS.md", body)
        self.assertIn("Do not directly notify the user", body)
        self.assertIn("Do not directly promote official skills", body)
        self.assertIn("Do not open nested subagents", body)

    def test_feishu_channel_formatting_skill_is_repo_bundled_and_feishu_only(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        skill_path = repo_root / "skills/feishu_channel_formatting/SKILL.md"

        self.assertTrue(skill_path.exists())
        body = skill_path.read_text(encoding="utf-8")

        self.assertIn("always_on: true", body)
        self.assertIn("channels: [feishu]", body)
        self.assertIn("Only a one-line direct answer may stay plain text", body)
        self.assertIn("Everything else must end with one trailing `feishu_card`", body)
        self.assertIn("exactly one trailing fenced `feishu_card` block", body)
        self.assertIn("do not use ```json", body)
        self.assertIn("2+ lines", body)
        self.assertIn("2+ bullets", body)
        self.assertIn("lists, grouped items, status summaries, checks, candidate sets, ranked results, or multi-record output", body)
        self.assertIn("When you emit `feishu_card`, keep the visible answer to one short summary line", body)
        self.assertIn("Do not keep any visible bullet list or second paragraph outside `feishu_card`", body)
        self.assertIn("Do not append separators, extra paragraphs, or closing notes after `feishu_card`", body)
        self.assertIn("Do not repeat the same bullet list both in the visible text and in `feishu_card`", body)
        self.assertIn("Never use Markdown tables, HTML, or code fences", body)
        self.assertIn("Prefer 2-5 flat bullets", body)
        self.assertIn("`**名称**｜状态：...｜时间：...`", body)
        self.assertIn("Use `title`, `summary`, and `sections` only", body)
        self.assertIn("Do not emit keys like `type`, `template`, `items`, or other alternate card schemas", body)
        self.assertIn("If you are not confident you can produce valid JSON, do not emit `feishu_card`", body)
        self.assertIn("Never mention raw field names like `delivery_target`, `skill_id`, `automation_id`, or `trace_id`", body)
        self.assertIn('{"title":"任务概览","summary":"共 2 项","sections":[{"items":["', body)
        self.assertIn("`sections[].items` must be plain strings", body)
        self.assertIn("Do not expose internal ids", body)
        self.assertIn("For GitHub trending answers, prefer `stars_period` over `stars_total`", body)
        self.assertIn("mention the trend window and fetched time", body)
        self.assertIn("Do not write vague summaries like `Top 10 如下`", body)
        self.assertIn("official GitHub Trending page order", body)
        self.assertIn("not a local re-sort by `stars_period` or `stars_total`", body)
        self.assertIn("explicitly include one short user-facing note", body)
        self.assertIn("榜单顺序遵循 GitHub Trending 页面", body)
        self.assertIn("do not repeat the fetched time again inside the ordering note", body)
        self.assertIn("include numeric rank prefixes like `1.`", body)
        self.assertIn("show the fetched date and time", body)
        self.assertIn("exactly as `YYYY-MM-DD HH:MM`", body)
        self.assertIn("do not shorten it to `HH:MM` only", body)
        self.assertIn("use `已启用` and `已暂停` as the only status labels", body)
        self.assertIn("do not summarize shared category labels like `均为 GitHub 热榜推荐`", body)

    def test_skill_service_includes_feishu_channel_formatting_only_for_feishu_runtime(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        service = SkillService([str(repo_root / "skills")])

        feishu_runtime = service.build_runtime(
            agent_id="main",
            channel_id="feishu",
            env={},
            config={},
        )
        http_runtime = service.build_runtime(
            agent_id="main",
            channel_id="http",
            env={},
            config={},
        )

        self.assertIn("feishu_channel_formatting", feishu_runtime.snapshot.always_on_ids)
        self.assertIn("Avoid Markdown tables", feishu_runtime.always_on_text or "")
        self.assertNotIn("feishu_channel_formatting", http_runtime.snapshot.always_on_ids)
        self.assertEqual(http_runtime.always_on_text, None)


if __name__ == "__main__":
    unittest.main()
