from __future__ import annotations

from typing import Literal


def build_compaction_prompt(
    *,
    prompt_mode: Literal["history_summary", "context_pressure"] = "context_pressure",
) -> str:
    if prompt_mode == "history_summary":
        return (
            "你正在执行一次**历史摘要（History Summary）**。\n"
            "请为未来恢复这个会话的 LLM 创建一份历史摘要。\n\n"
            "这个摘要的用途是：\n"
            "- 在用户切换走当前会话后，为未来恢复提供稳定延续层\n"
            "- 总结较早历史，帮助后续模型无缝接回这个会话\n"
            "- 不是因为上下文窗口压力触发的压缩\n"
            "- 不是用来替换 system prompt、skill 描述、MCP 工具描述或 app/bootstrap 提示词\n\n"
            "需要包含：\n"
            "- 当前进展以及已做出的关键决策\n"
            "- 重要的上下文、约束条件或用户偏好\n"
            "- 剩余需要完成的工作（明确的下一步）\n"
            "- 为继续任务所需的关键数据、示例或参考信息\n\n"
            "要求：\n"
            "- 内容要简洁、有结构，并以帮助下一个 LLM 无缝恢复这个会话为目标\n"
            "- 只保留继续工作真正需要的信息，不要复述所有历史\n"
            "- 这是旧历史背景摘要，不是下一轮行动菜单\n"
            "- 不要写“建议下一步 / 优先做 / 可以先做三件事”这类回合级行动清单\n"
            "- 如果历史里并存多个主题，只记录它们各自的状态与结论，不要把它们并列成当前回合必须继续执行的任务\n"
            "- 不要虚构未发生的事实\n"
            "- 不要保留纯噪音工具日志\n"
            "- 如果最近几条消息仍会被保留，请不要重复展开这些最近尾部细节\n"
        )
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
        "- 这是旧历史背景摘要，不是下一轮行动菜单\n"
        "- 不要写“建议下一步 / 优先做 / 可以先做三件事”这类回合级行动清单\n"
        "- 如果历史里并存多个主题，只记录它们各自的状态与结论，不要把它们并列成当前回合必须继续执行的任务\n"
        "- 不要虚构未发生的事实\n"
        "- 不要保留纯噪音工具日志\n"
        "- 如果最近几条消息仍会被保留，请不要重复展开这些最近尾部细节\n"
    )


def render_compact_summary_block(summary_text: str, *, trigger_kind: str | None = None) -> str:
    if isinstance(trigger_kind, str) and trigger_kind.startswith("context_pressure"):
        intro = (
            "以下是更早历史压缩出的上下文检查点，只用于理解旧背景。\n"
            "当前这条用户消息优先级最高；不要把摘要里的旧主题、历史建议或未决项直接当成当前回合的执行清单。"
            "保持当前 runtime 指令不变。\n\n"
        )
    else:
        intro = (
            "以下是更早历史的摘要，只用于理解旧背景。\n"
            "当前这条用户消息优先级最高；不要把摘要里的旧主题、历史建议或未决项直接当成当前回合的执行清单。"
            "保持当前 runtime 指令不变。\n\n"
        )
    return f"{intro}{summary_text.strip()}"
