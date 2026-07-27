import unittest
from pathlib import Path

from marten_runtime.agents.assets import load_agent_system_prompt
from marten_runtime.config.agents_loader import load_agent_specs
from marten_runtime.config.bindings_loader import load_agent_bindings
from marten_runtime.runtime.history import InMemoryRunHistory
from marten_runtime.runtime.llm_client import LLMReply, ScriptedLLMClient
from marten_runtime.runtime.loop import RuntimeLoop
from marten_runtime.skills.service import SkillService
from marten_runtime.tools.registry import ToolRegistry
from tests.support.finalization_contracts import contracted_final_reply


class BaziAgentAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.specs = {item.agent_id: item for item in load_agent_specs(str(cls.root / "config" / "agents.toml"))}

    def test_bazi_agent_has_only_required_tools_and_explicit_sensitive_scope(self) -> None:
        spec = self.specs["bazi"]

        self.assertEqual(spec.allowed_tools, ["bazi", "knowledge", "time"])
        self.assertEqual(spec.allowed_knowledge_namespaces, ["bazi-theory", "bazi-cases"])
        self.assertEqual(spec.allowed_knowledge_actions, ["search", "get_chunk", "model_status"])
        self.assertEqual(spec.observation_policy, "sensitive_bazi")
        self.assertNotIn("mcp", spec.allowed_tools)
        self.assertNotIn("memory", spec.allowed_tools)
        self.assertIn("八字排盘", spec.routing_description)

    def test_main_agent_routes_only_to_registered_bazi_specialist(self) -> None:
        main = self.specs["main"]

        self.assertEqual(main.allowed_handoff_agents, ["bazi"])
        self.assertIn("通用问答", main.routing_description)

    def test_all_enabled_knowledge_agents_have_explicit_scope_without_bazi_writes(self) -> None:
        writes = {"ingest_text", "ingest_file", "cancel_ingest", "delete_source", "reindex", "unload_models"}
        for spec in self.specs.values():
            if not spec.enabled or "knowledge" not in spec.allowed_tools:
                continue
            with self.subTest(agent_id=spec.agent_id):
                self.assertIsNotNone(spec.allowed_knowledge_namespaces)
                self.assertIsNotNone(spec.allowed_knowledge_actions)
                if {"bazi-theory", "bazi-cases"} & set(spec.allowed_knowledge_namespaces or []):
                    self.assertFalse(writes & set(spec.allowed_knowledge_actions or []))

    def test_agent_assets_and_always_on_skill_load_through_existing_bootstrap(self) -> None:
        spec = self.specs["bazi"]
        prompt = load_agent_system_prompt(repo_root=self.root, spec=spec)
        skill_runtime = SkillService([str(self.root / "skills")]).build_runtime(
            agent_id="bazi",
            channel_id="http",
        )

        self.assertIn("文化研究", prompt)
        self.assertIn("birthPlace", prompt)
        self.assertIn("fingerprint", prompt)
        self.assertIn("bazi_analysis", [item.meta.skill_id for item in skill_runtime.visible_skills])
        self.assertIn("排盘", skill_runtime.always_on_text)
        self.assertIn("source_title", skill_runtime.always_on_text)
        self.assertIn("子平格局法", skill_runtime.always_on_text)
        self.assertIn("盲派", skill_runtime.always_on_text)
        self.assertIn("原局格局喜用", skill_runtime.always_on_text)
        self.assertIn("财富等级", skill_runtime.always_on_text)
        self.assertIn("过三关", skill_runtime.always_on_text)
        self.assertIn("高中、大专、本科、顶级本科", skill_runtime.always_on_text)
        self.assertIn("没有明确证据时完全省略", skill_runtime.always_on_text)
        self.assertIn("年支桃花只能作为一般社交信号", skill_runtime.always_on_text)
        self.assertIn("低于 300 万元普通积累", skill_runtime.always_on_text)
        self.assertIn("食伤生财或无财而暗成财局", skill_runtime.always_on_text)
        self.assertIn("官杀、印、禄不得直接改称财星", skill_runtime.always_on_text)
        self.assertIn("财富结构分：X/9", skill_runtime.always_on_text)
        self.assertIn("命理年收入能力区间", skill_runtime.always_on_text)
        self.assertIn("不等同现实收入", skill_runtime.always_on_text)
        self.assertIn("月令本气、司令", skill_runtime.always_on_text)
        self.assertIn("丁火以壬为正官、癸为七杀", skill_runtime.always_on_text)
        self.assertIn("健康", skill_runtime.always_on_text)
        self.assertIn("自刑只包括辰辰、午午、酉酉、亥亥", skill_runtime.always_on_text)
        self.assertIn("巳巳属于伏吟", skill_runtime.always_on_text)
        self.assertIn("部位映射 + 原局作用 + 行运引动", skill_runtime.always_on_text)
        self.assertIn("申、酉缺少稳定身体部位归纳", skill_runtime.always_on_text)
        self.assertIn("寅午戌见卯、申子辰见酉、巳酉丑见午、亥卯未见子", skill_runtime.always_on_text)
        self.assertIn("检查、治疗、住院或开刀", skill_runtime.always_on_text)
        self.assertIn("父星、母星、年柱", skill_runtime.always_on_text)
        self.assertIn("应期逐年表", skill_runtime.always_on_text)
        self.assertIn("从排盘返回的首个流年扫描到当前年", skill_runtime.always_on_text)
        self.assertIn("十神 + 宫位 + 身体取象", skill_runtime.always_on_text)
        self.assertIn("流年干作用谁、对应什么十神", skill_runtime.always_on_text)
        self.assertIn("相同者补记伏吟", skill_runtime.always_on_text)
        self.assertIn("排序后复查全部干支", skill_runtime.always_on_text)
        self.assertIn("`结构组合`", skill_runtime.always_on_text)
        self.assertIn("`成年后结构组合摘要`", skill_runtime.always_on_text)
        self.assertIn("任何单一十神组合都不享有固定优先级", prompt)
        self.assertIn("先记录全部候选", skill_runtime.always_on_text)
        self.assertIn("升学、入职、转岗、换行业、搬家、买房", skill_runtime.always_on_text)
        self.assertIn("不为满足主题数量加入较弱事件", skill_runtime.always_on_text)
        self.assertIn('"calendarType":"lunar"', skill_runtime.always_on_text)
        self.assertIn('"action":"resolve_pillars"', skill_runtime.always_on_text)
        self.assertIn('"gender":"male"', skill_runtime.always_on_text)
        self.assertIn("唯一已出生候选", skill_runtime.always_on_text)
        self.assertIn("chart=1", skill_runtime.always_on_text)
        self.assertIn("dayun=1", skill_runtime.always_on_text)
        self.assertIn("resolve_pillars=1", skill_runtime.always_on_text)
        self.assertIn("knowledge.search=1", skill_runtime.always_on_text)
        self.assertIn("knowledge.get_chunk=0", skill_runtime.always_on_text)
        self.assertIn("立即综合输出", skill_runtime.always_on_text)
        self.assertIn("同一 action 和同一 payload", skill_runtime.always_on_text)

    def test_binding_config_keeps_main_as_the_only_default_for_each_channel(self) -> None:
        bindings = load_agent_bindings(str(self.root / "config" / "bindings.toml"))
        defaults: dict[str, int] = {}
        for binding in bindings:
            if binding.default:
                defaults[str(binding.channel_id)] = defaults.get(str(binding.channel_id), 0) + 1
        self.assertEqual(defaults, {"http": 1, "feishu": 1})
        self.assertEqual([item.agent_id for item in bindings], ["main", "main"])

    def test_runtime_loop_propagates_agent_knowledge_scope_to_tool_context(self) -> None:
        captured: dict[str, object] = {}
        tools = ToolRegistry()

        def handler(_payload: dict, *, tool_context: dict | None = None) -> dict:
            captured.update(tool_context or {})
            return {"ok": True, "result_text": "done"}

        tools.register("knowledge", handler)
        runtime = RuntimeLoop(
            ScriptedLLMClient(
                [
                    LLMReply(tool_name="knowledge", tool_payload={"action": "model_status"}),
                    contracted_final_reply("done"),
                ]
            ),
            tools,
            InMemoryRunHistory(),
        )

        runtime.run(session_id="session", message="status", agent=self.specs["bazi"])

        self.assertEqual(captured["allowed_knowledge_actions"], ["search", "get_chunk", "model_status"])
        self.assertEqual(captured["allowed_knowledge_namespaces"], ["bazi-theory", "bazi-cases"])

    def test_explicit_lunar_birth_input_is_complete_for_chart(self) -> None:
        spec = self.specs["bazi"]
        prompt = load_agent_system_prompt(repo_root=self.root, spec=spec)
        skill_runtime = SkillService([str(self.root / "skills")]).build_runtime(
            agent_id="bazi",
            channel_id="feishu",
        )

        combined = prompt + "\n" + skill_runtime.always_on_text
        self.assertIn("calendarType=lunar", combined)
        self.assertIn("isLeapMonth=false", combined)
        self.assertIn("农历转公历由排盘引擎完成", combined)
        self.assertIn("sourceTimeStandard=recorded_civil", combined)
        self.assertIn("timeBasis=true_solar", combined)


if __name__ == "__main__":
    unittest.main()
