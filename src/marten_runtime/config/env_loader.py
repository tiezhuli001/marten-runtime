from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel


class EnvLoadResult(BaseModel):
    loaded: bool
    path: str | None = None


def load_env_file(path: str | Path, *, override: bool = False) -> EnvLoadResult:
    resolved = Path(path)
    if not resolved.exists():
        return EnvLoadResult(loaded=False, path=str(resolved))
    load_dotenv(resolved, override=override)
    return EnvLoadResult(loaded=True, path=str(resolved))


def load_repo_env(repo_root: str | Path, *, filename: str = ".env", override: bool = False) -> EnvLoadResult:
    return load_env_file(Path(repo_root) / filename, override=override)
