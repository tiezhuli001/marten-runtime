import unittest

from marten_runtime.runtime.capabilities import (
    CapabilityDeclaration,
    get_capability_declarations,
    get_parameters_schema,
    render_capability_catalog,
    render_tool_description,
    render_tool_description_for_provider,
)


class RuntimeCapabilitiesTests(unittest.TestCase):
    def test_capability_declarations_cover_runtime_visible_tool_families(self) -> None:
        declarations = get_capability_declarations()

        self.assertEqual(
            set(declarations.keys()),
            {
                "automation",
                "cancel_subagent",
                "knowledge",
                "memory",
                "mcp",
                "runtime",
                "session",
                "self_improve",
                "skill",
                "spawn_subagent",
                "time",
            },
        )
        self.assertTrue(all(isinstance(item, CapabilityDeclaration) for item in declarations.values()))


    def test_provider_description_keeps_llm_first_rules_for_sensitive_routing_tools(self) -> None:
        declarations = get_capability_declarations()

        session_provider = render_tool_description_for_provider(declarations["session"])
        spawn_provider = render_tool_description_for_provider(declarations["spawn_subagent"])
        runtime_provider = render_tool_description_for_provider(declarations["runtime"])

        self.assertIn("session_ref", session_provider)
        self.assertIn("go directly to resume/show instead of listing first", session_provider)
        self.assertIn("do not repeat resume/show/list", session_provider)
        self.assertIn("explicitly requests delegation/background execution", spawn_provider)
        self.assertIn("answer from that attached state directly", spawn_provider)
        self.assertIn("Use spawn_subagent only for launching a new child task", spawn_provider)
        self.assertNotIn("Rules:", runtime_provider)

    def test_capability_declarations_render_catalog_and_descriptions_from_same_source(self) -> None:
        declarations = get_capability_declarations()

        catalog = render_capability_catalog(declarations)
        automation_description = render_tool_description(declarations["automation"])
        mcp_description = render_tool_description(declarations["mcp"])
        runtime_description = render_tool_description(declarations["runtime"])
        session_description = render_tool_description(declarations["session"])
        time_description = render_tool_description(declarations["time"])

        self.assertIn("Capability catalog:", catalog)
        self.assertIn("- automation:", catalog)
        self.assertIn("- runtime:", catalog)
        self.assertIn("- session:", catalog)
        self.assertIn("answer with that result and stop", catalog)
        self.assertIn("set finalize_response=true", catalog)
        self.assertIn("one tool result is already enough", catalog)
        self.assertIn("现在有哪些会话列表", catalog)
        self.assertIn("告诉我当前北京时间", catalog)
        self.assertIn("当前上下文窗口和 token 使用详情", catalog)
        self.assertIn("先告诉我当前时间，再查 GitHub 最近提交", catalog)
        self.assertIn("requested execution mode is part of the task contract", catalog)
        self.assertIn("Do not replace requested delegation/background execution", catalog)
        self.assertIn("Re-evaluate tool choice from the current user turn every time", catalog)
        self.assertIn("parked one concrete future task or topic for continuation", catalog)
        self.assertIn("在压缩后的上下文里继续执行", catalog)
        self.assertIn("continuation cues, not as session metadata or runtime-number queries", catalog)
        self.assertIn("Only confirm a durable-memory write after a successful memory tool result", catalog)
        self.assertIn("explicit durable-memory write requests still require a memory tool result", catalog)
        self.assertTrue(automation_description)
        self.assertTrue(mcp_description)
        self.assertTrue(runtime_description)
        self.assertTrue(session_description)
        self.assertTrue(time_description)
        self.assertIn("Actions:", automation_description)
        self.assertIn("automation", automation_description.lower())
        self.assertIn("定时任务", automation_description)
        self.assertIn("github", mcp_description.lower())
        self.assertIn("exact server_id", mcp_description)
        self.assertIn("exact tool_name", mcp_description)
        self.assertIn("上下文窗口", runtime_description)
        self.assertIn("token", runtime_description.lower())
        self.assertIn("会话列表", session_description)
        self.assertIn("sess_", session_description)
        self.assertIn("finalize_response=true", session_description)
        self.assertIn("session.resume", catalog)
        self.assertIn("runtime.context_status", catalog)
        self.assertIn("现在几点", time_description)
        self.assertTrue(
            "runtime" in runtime_description.lower() or "上下文" in runtime_description
        )


    def test_memory_tool_schema_marks_scope_and_type_required_for_model_payloads(self) -> None:
        declarations = get_capability_declarations()

        schema = get_parameters_schema(declarations["memory"])

        self.assertEqual(schema["required"], ["action"])
        self.assertIn("scope", schema["properties"])
        self.assertIn("type", schema["properties"])
        append_replace_requirements = [
            item.get("then", {}).get("required", [])
            for item in schema.get("allOf", [])
            if item.get("if", {}).get("properties", {}).get("action", {}).get("enum") == ["append", "replace"]
        ]
        self.assertEqual(
            append_replace_requirements,
            [["intent", "source_excerpt", "scope", "type", "section", "content"]],
        )
        delete_requirements = [
            item.get("then", {}).get("required", [])
            for item in schema.get("allOf", [])
            if item.get("if", {}).get("properties", {}).get("action", {}).get("enum") == ["delete"]
        ]
        self.assertEqual(
            delete_requirements,
            [["intent", "source_excerpt", "scope", "section"]],
        )

    def test_runtime_capability_description_requires_tool_for_natural_language_context_queries(self) -> None:
        declarations = get_capability_declarations()

        catalog = render_capability_catalog(declarations) or ""
        runtime_description = render_tool_description(declarations["runtime"])

        self.assertIn("current context window usage", catalog)
        self.assertIn("当前上下文窗口多大", catalog)
        self.assertIn("当前这轮 token 使用详情", catalog)
        self.assertIn("当前会话的上下文窗口使用情况", catalog)
        self.assertIn("live runtime context data", runtime_description)
        self.assertIn("Only family tool", runtime_description)
        self.assertIn("current session", runtime_description)
        self.assertIn("why the effective window is a certain size", runtime_description)
        self.assertIn("当前会话的上下文窗口使用情况", runtime_description)
        self.assertIn("这个会话", runtime_description)
        self.assertIn("继续旧会话", runtime_description)
        self.assertIn("do not belong here by themselves", runtime_description.lower())
        self.assertIn("previous reply showed a session catalog", runtime_description)
        self.assertIn("finalize_response=true", runtime_description)
        self.assertNotIn("先调用 `runtime`", catalog)
        self.assertNotIn("不要直接根据记忆回答", catalog)
        self.assertTrue(
            "context_status" in runtime_description or "上下文" in runtime_description
        )
        self.assertNotIn("先调用 `runtime`", runtime_description)
        self.assertNotIn("不要直接根据记忆回答", runtime_description)

    def test_time_capability_description_requires_tool_for_natural_language_current_time_queries(self) -> None:
        declarations = get_capability_declarations()

        catalog = render_capability_catalog(declarations) or ""
        time_description = render_tool_description(declarations["time"])

        self.assertIn("现在几点", catalog)
        self.assertIn("北京时间", catalog)
        self.assertIn("live clock data", time_description)
        self.assertIn("timezone", time_description)
        self.assertIn("only answer a live current-time/current-date/current-datetime request", time_description.lower())
        self.assertIn("finalize_response=true", time_description)
        self.assertNotIn("不要直接猜", catalog)
        self.assertNotIn("先调用 `time`", catalog)
        self.assertNotIn("不要直接猜", time_description)
        self.assertNotIn("先调用", time_description)

    def test_time_runtime_and_memory_capabilities_expose_live_source_and_write_field_rules(
        self,
    ) -> None:
        declarations = get_capability_declarations()

        catalog = render_capability_catalog(declarations) or ""
        time_description = render_tool_description(declarations["time"])
        runtime_description = render_tool_description(declarations["runtime"])
        memory_description = render_tool_description(declarations["memory"])
        memory_schema = get_parameters_schema(declarations["memory"])
        session_schema = get_parameters_schema(declarations["session"])
        skill_schema = get_parameters_schema(declarations["skill"])
        skill_description = render_tool_description(declarations["skill"])
        self_improve_description = render_tool_description(declarations["self_improve"])

        self.assertIn("current time/date/datetime", catalog.lower())
        self.assertIn("time tool result", catalog.lower())
        self.assertIn("current-session context/token/window", catalog.lower())
        self.assertIn("runtime tool result", catalog.lower())
        self.assertIn("first-turn plain questions", time_description.lower())
        self.assertIn("this-turn time tool result", time_description.lower())
        self.assertIn("this-turn runtime result", runtime_description.lower())
        self.assertIn("only produce concrete current-session context", runtime_description.lower())
        self.assertIn("prior replies or summaries mention token counts", runtime_description.lower())
        self.assertIn("append/replace/delete", memory_description.lower())
        self.assertIn("source_excerpt", memory_description.lower())
        self.assertIn("section", memory_description.lower())
        self.assertIn("scope", memory_description.lower())
        self.assertIn("agent", memory_description.lower())
        self.assertIn("workspace", memory_description.lower())
        self.assertIn("type", memory_description.lower())
        self.assertIn("preferences", memory_description.lower())
        self.assertIn("facts", memory_description.lower())
        self.assertIn("before confirming success", memory_description.lower())
        self.assertIn("prefer replace on section=preferences", memory_description.lower())
        self.assertIn("only confirm 已记住 / 已更新", memory_description.lower())
        self.assertIn("still requires a memory tool call in this turn", memory_description.lower())
        self.assertIn("attached memory state directly", memory_description.lower())
        self.assertIn("immediate read-after-write", memory_description.lower())
        self.assertIn("calling get again", memory_description.lower())
        self.assertIn("source_excerpt", memory_schema["properties"])
        self.assertIn("exact current-user-message span", memory_schema["properties"]["source_excerpt"]["description"].lower())
        self.assertIn("required for append/replace/delete", memory_schema["properties"]["section"]["description"].lower())
        self.assertIn("preferences", memory_schema["properties"]["section"]["description"].lower())
        self.assertIn("scope", memory_schema["properties"])
        self.assertIn("type", memory_schema["properties"])
        self.assertIn("agent_id", memory_schema["properties"])
        self.assertIn("workspace_id", memory_schema["properties"])
        self.assertIn("priority", memory_schema["properties"])
        self.assertIn("memory_id", memory_schema["properties"])
        self.assertNotIn("tags", memory_schema["properties"])
        self.assertNotIn("app_id", memory_schema["properties"])
        self.assertIn("required for append/replace", memory_schema["properties"]["content"]["description"].lower())
        self.assertIn("session_ref", session_schema["properties"])
        self.assertIn("visible session title", session_schema["properties"]["session_ref"]["description"].lower())
        self.assertIn("exact visible skill_id only", skill_schema["properties"]["skill_id"]["description"].lower())
        self.assertIn("plain continuation cues", skill_description.lower())
        self.assertIn("continue directly instead of loading a skill", skill_description.lower())
        self.assertIn("copy the exact skill_id from visible skills", skill_description.lower())
        self.assertIn("task-summary nouns", skill_description.lower())
        self.assertIn("missing skill body", skill_description.lower())
        self.assertIn("plain task continuation", self_improve_description.lower())

    def test_session_and_automation_capability_descriptions_define_builtin_boundaries(self) -> None:
        declarations = get_capability_declarations()

        catalog = render_capability_catalog(declarations) or ""
        session_description = render_tool_description(declarations["session"])
        automation_description = render_tool_description(declarations["automation"])
        memory_description = render_tool_description(declarations["memory"])

        self.assertIn("现在有哪些会话列表", catalog)
        self.assertIn("切换到 sess_dcce8f9c", catalog)
        self.assertIn("当前有哪些定时任务", catalog)
        self.assertIn("记住这个长期偏好：我默认使用 minimax", catalog)
        self.assertIn("action=list only for explicit catalog requests", session_description.lower())
        self.assertIn("action=show", session_description.lower())
        self.assertIn("scheduled job lists belong to automation", session_description.lower())
        self.assertIn("runtime context size belongs to runtime", session_description.lower())
        self.assertIn("do not use it for current-session context", session_description.lower())
        self.assertIn("do not repeat action=list unless the current turn explicitly asks", session_description.lower())
        self.assertIn("after a successful session.new or session.resume", session_description.lower())
        self.assertIn("plain task execution in the now-bound session", session_description.lower())
        self.assertIn("across later turns", session_description.lower())
        self.assertIn("do not repeat resume/show/list", session_description.lower())
        self.assertIn("brief continuation confirmation", session_description.lower())
        self.assertIn("message_count", session_description.lower())
        self.assertIn("session_id unless the user explicitly asked for session metadata", session_description.lower())
        self.assertIn("minimum task anchor needed", session_description.lower())
        self.assertIn("do not switch to session.show/list or runtime", session_description.lower())
        self.assertIn("compaction continuation requests", session_description.lower())
        self.assertIn("继续这个长线程任务", session_description)
        self.assertIn("words like 上下文, 长线程, or 当前会话", session_description.lower())
        self.assertIn("定时任务", automation_description)
        self.assertIn("cron", automation_description.lower())
        self.assertIn("durable memory", memory_description)
        self.assertIn("session history questions belong to session", memory_description.lower())
        self.assertIn("收到的话只回两个字", memory_description)
        self.assertIn("not durable memory writes", memory_description.lower())
        self.assertIn("new session request", session_description.lower())
        self.assertIn("finalize_response=true", session_description.lower())

    def test_runtime_and_session_descriptions_keep_current_turn_boundary_under_recent_history_noise(
        self,
    ) -> None:
        declarations = get_capability_declarations()

        runtime_description = render_tool_description(declarations["runtime"])
        session_description = render_tool_description(declarations["session"])

        self.assertIn("current turn", runtime_description.lower())
        self.assertIn("previous turns", runtime_description.lower())
        self.assertIn("previous reply showed a session catalog", runtime_description.lower())
        self.assertIn("session lists", runtime_description.lower())
        self.assertIn("current context window", runtime_description.lower())
        self.assertIn("previous turns", session_description.lower())
        self.assertIn("current turn asks about context", session_description.lower())
        self.assertIn("do not call session", session_description.lower())
        self.assertIn("current-session context window", runtime_description.lower())

    def test_runtime_and_session_parameter_schemas_disambiguate_switch_from_context_queries(
        self,
    ) -> None:
        declarations = get_capability_declarations()

        runtime_schema = get_parameters_schema(declarations["runtime"])
        session_schema = get_parameters_schema(declarations["session"])
        time_schema = get_parameters_schema(declarations["time"])
        runtime_action = runtime_schema["properties"]["action"]
        session_action = session_schema["properties"]["action"]
        session_id = session_schema["properties"]["session_id"]

        self.assertEqual(runtime_action["enum"], ["context_status"])
        self.assertIn("current-session context window", runtime_action["description"])
        self.assertEqual(runtime_schema["properties"]["finalize_response"]["type"], "boolean")
        self.assertIn("runtime status result itself should end the turn", runtime_schema["properties"]["finalize_response"]["description"])
        self.assertEqual(session_action["enum"], ["resume", "new", "show", "list"])
        self.assertIn("Use resume to switch/continue", session_action["description"])
        self.assertIn("Use list only for explicit session catalog requests", session_action["description"])
        self.assertIn("Copy the exact sess_xxx token", session_id["description"])
        self.assertIn("session_ref", session_schema["properties"])
        self.assertIn("visible session title", session_schema["properties"]["session_ref"]["description"].lower())
        self.assertEqual(time_schema["properties"]["finalize_response"]["type"], "boolean")
        self.assertIn("clock result itself should end the turn", time_schema["properties"]["finalize_response"]["description"])

    def test_mcp_capability_description_stays_declarative_for_github_queries(self) -> None:
        declarations = get_capability_declarations()

        catalog = render_capability_catalog(declarations) or ""
        mcp_description = render_tool_description(declarations["mcp"])

        self.assertIn("GitHub repository questions", catalog)
        self.assertIn("github", mcp_description.lower())
        self.assertIn("exact server_id", mcp_description)
        self.assertIn("exact tool_name", mcp_description)
        self.assertIn("arguments", mcp_description)
        self.assertIn("do not invent aliases", mcp_description.lower())
        self.assertIn("stop after the requested scope", mcp_description.lower())
        self.assertIn("README.md", mcp_description)
        self.assertIn("instead of spending a turn on mcp.detail", mcp_description)
        self.assertNotIn("progressive inspection", mcp_description.lower())
        self.assertNotIn("before one concrete call", mcp_description.lower())
        self.assertNotIn("search_repositories", mcp_description)
        self.assertNotIn("repo:owner/name", mcp_description)
        self.assertNotIn("list_commits", mcp_description)
        self.assertNotIn("不要先调用", mcp_description)
        self.assertNotIn("不要拿仓库 metadata 冒充 commit 信息", mcp_description)

    def test_mcp_capability_description_guides_latest_commit_queries_without_tool_name_hardcoding(
        self,
    ) -> None:
        declarations = get_capability_declarations()

        catalog = render_capability_catalog(declarations) or ""
        mcp_description = render_tool_description(declarations["mcp"])

        self.assertIn("最近一次提交", catalog)
        self.assertIn("最新提交", mcp_description)
        self.assertIn("latest commit", mcp_description)
        self.assertIn("exact visible MCP tools in the current catalog", mcp_description)
        self.assertIn("smallest visible tool sequence", mcp_description)
        self.assertIn("concrete commit sha is already known", mcp_description)
        self.assertNotIn("get_commit", mcp_description)
        self.assertNotIn("list_commits", mcp_description)

    def test_mcp_schema_guides_visible_commit_history_tool_selection_without_named_tools(self) -> None:
        declarations = get_capability_declarations()

        schema = get_parameters_schema(declarations["mcp"])
        tool_name_description = schema["properties"]["tool_name"]["description"]
        arguments_description = schema["properties"]["arguments"]["description"]

        self.assertIn("Exact visible MCP tool name", tool_name_description)
        self.assertIn("latest-commit", tool_name_description)
        self.assertIn("history/list tool", tool_name_description)
        self.assertIn("avoid invented convenience names", tool_name_description)
        self.assertIn("commit-history lookups", arguments_description)
        self.assertIn("owner and repo", arguments_description)
        self.assertIn("small result-limit", arguments_description)
        self.assertNotIn("get_commit", tool_name_description)
        self.assertNotIn("list_commits", tool_name_description)
        self.assertNotIn("get_commit", arguments_description)
        self.assertNotIn("list_commits", arguments_description)

    def test_capability_declarations_expose_expected_structured_fields(self) -> None:
        declarations = get_capability_declarations()

        self.assertIsInstance(declarations["mcp"], CapabilityDeclaration)
        self.assertEqual(
            set(CapabilityDeclaration.model_fields),
            {
                "name",
                "summary",
                "actions",
                "usage_rules",
                "examples",
                "parameters_schema",
            },
        )
        for declaration in declarations.values():
            self.assertIsInstance(get_parameters_schema(declaration), dict)
            self.assertTrue(render_tool_description(declaration))

    def test_spawn_subagent_capability_guides_profile_selection_for_external_live_data(
        self,
    ) -> None:
        declarations = get_capability_declarations()

        spawn_description = render_tool_description(declarations["spawn_subagent"])
        spawn_schema = get_parameters_schema(declarations["spawn_subagent"])
        tool_profile_schema = spawn_schema["properties"]["tool_profile"]
        context_mode_schema = spawn_schema["properties"]["context_mode"]
        agent_id_schema = spawn_schema["properties"]["agent_id"]

        self.assertIn("default when tool_profile is omitted", spawn_description)
        self.assertIn("开启子代理查询 github / mcp / 外部实时数据 belong here", spawn_description.lower())
        self.assertIn("previous session catalog reply is only background", spawn_description.lower())
        self.assertIn("explicitly requests delegation/background execution", spawn_description.lower())
        self.assertIn("stable across retries, failover, and repair turns", spawn_description.lower())
        self.assertIn("package the work into the child task", spawn_description.lower())
        self.assertIn("child task brief semantic and goal-first", spawn_description.lower())
        self.assertIn("do not pre-script exact mcp subtool names", spawn_description.lower())
        self.assertIn("one bound repository context", spawn_description.lower())
        self.assertIn("do not ask the child to request owner/repo again", spawn_description.lower())
        self.assertIn("split work into multiple child tasks", spawn_description.lower())
        self.assertIn("every requested child task has been dispatched", spawn_description.lower())
        self.assertIn("already includes a real prior child-task state or completion summary", spawn_description.lower())
        self.assertIn("answer from that attached state directly", spawn_description.lower())
        self.assertIn("preserving the child summary's concrete object phrase", spawn_description.lower())
        self.assertIn("coverage nouns", spawn_description.lower())
        self.assertIn("reuse the attached summary's own task objects", spawn_description.lower())
        self.assertIn("document/module names", spawn_description.lower())
        self.assertIn("structure layers", spawn_description.lower())
        self.assertIn("coverage terms", spawn_description.lower())
        self.assertIn("conclusion phrases", spawn_description.lower())
        self.assertNotIn("仓库结构、顶层目录、主要模块、关键配置、测试与文档", spawn_description)
        self.assertIn("restricted profile only has runtime, skill, and time", spawn_description)
        self.assertIn("MCP, web/API, or other external live data", spawn_description)
        self.assertIn("Omit optional fields", spawn_description)
        self.assertEqual(
            tool_profile_schema["enum"],
            ["restricted", "standard", "elevated", "mcp"],
        )
        self.assertIn("Omit the field to get the default standard behavior", tool_profile_schema["description"])
        self.assertIn("MCP", tool_profile_schema["description"])
        self.assertEqual(
            context_mode_schema["enum"],
            ["brief_only", "brief_plus_snapshot"],
        )
        self.assertIn("default brief_only behavior", context_mode_schema["description"])
        self.assertIn("do not send placeholder values", agent_id_schema["description"])


if __name__ == "__main__":
    unittest.main()
