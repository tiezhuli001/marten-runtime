from __future__ import annotations


def run_label(value: str, *, empty: str = "-") -> str:
    if not value or value == empty:
        return empty
    if value == "latest_passed":
        return "最近通过基线"
    if value.startswith("named:"):
        return f"命名基线 {value.removeprefix('named:')}"
    if value == "explicit_run":
        return "指定基线"
    if value.startswith("eval_"):
        parts = value.split("_")
        if len(parts) >= 5 and parts[-1].isdigit() and parts[-3].isdigit():
            suite = "_".join(parts[1:-3])
            timestamp = parts[-3]
            sha = parts[-2]
            sequence = parts[-1]
            return f"{suite_label(suite)} · {format_eval_timestamp(timestamp)} · {sha[:7]} · 第{int(sequence) + 1}次"
    return short_id(value, empty=empty)


def suite_label(value: str) -> str:
    return {
        "main_chain_core": "主链黄金链路",
        "main_chain_mcp": "MCP 链路",
        "main_chain_subagent": "子代理链路",
        "memory_long_horizon": "记忆链路",
        "subagent_task_progress": "子代理进度链路",
        "subagent_external_mcp_completion": "子代理外部 MCP 完成链路",
        "ops_smoke": "运维冒烟链路",
    }.get(value, value)


def format_eval_timestamp(value: str) -> str:
    if len(value) < 14 or not value[:14].isdigit():
        return value
    return f"{value[:4]}-{value[4:6]}-{value[6:8]} {value[8:10]}:{value[10:12]}:{value[12:14]}"


def short_id(value: str, *, empty: str = "-") -> str:
    if not value or value == empty:
        return value or empty
    if len(value) <= 34:
        return value
    return f"{value[:18]}…{value[-10:]}"


def int_value(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def provider_health_status(
    *,
    retry_count: int,
    fallback_count: int,
    provider_error_count: int,
    empty_output_count: int,
) -> tuple[str, str]:
    if provider_error_count > 0 or empty_output_count > 0:
        return ("有错误", "存在 provider 错误或空输出")
    if retry_count > 0 or fallback_count > 0:
        return ("有波动", "出现重试或 provider 回退")
    return ("健康", "无重试、无回退、无错误、无空输出")
