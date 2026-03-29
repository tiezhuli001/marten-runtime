import tomllib
from pathlib import Path

from marten_runtime.agents.bindings import AgentBinding


def load_agent_bindings(path: str) -> list[AgentBinding]:
    file_path = Path(path)
    if not file_path.exists():
        return []
    data = tomllib.loads(file_path.read_text(encoding="utf-8"))
    return [AgentBinding(**item) for item in data.get("bindings", [])]
