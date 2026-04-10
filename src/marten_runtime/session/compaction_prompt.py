from __future__ import annotations


def build_compaction_prompt() -> str:
    return (
        "你正在执行一次**上下文检查点压缩（Context Checkpoint Compaction）**。\n"
        "请为另一个将继续此任务的 LLM 创建一份交接摘要。\n\n"
        "这个摘要的用途是：\n"
        "- 替换过长的旧会话历史\n"
        "- 帮助后续模型无缝继续当前任务\n"
        "- 不是用来替换 system prompt、skill 描述、MCP 工具描述或 app/bootstrap 提示词\n\n"
        "需要包含：\n"
        "- 当前进展以及已做出的关键决策\n"
        "- 重要的上下文、约束条件或用户偏好\n"
        "- 剩余需要完成的工作（明确的下一步）\n"
        "- 为继续任务所需的关键数据、示例或参考信息\n\n"
        "要求：\n"
        "- 内容要简洁、有结构，并以帮助下一个 LLM 无缝继续工作为目标\n"
        "- 只保留继续工作真正需要的信息，不要复述所有历史\n"
        "- 不要虚构未发生的事实\n"
        "- 不要保留纯噪音工具日志\n"
        "- 如果最近几条消息仍会被保留，请不要重复展开这些最近尾部细节\n"
    )


def render_compact_summary_block(summary_text: str) -> str:
    return (
        "Earlier conversation was compacted into the following continuation checkpoint.\n"
        "Use it as a summary of older history only; keep current runtime instructions unchanged.\n\n"
        f"{summary_text.strip()}"
    )
