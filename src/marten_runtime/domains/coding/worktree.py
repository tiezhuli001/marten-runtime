from pathlib import Path
import subprocess


class WorktreeService:
    backend_id: str = "subprocess"

    def __init__(self) -> None:
        self._repo: Path | None = None

    def prepare(self, repo: str) -> str:
        self._repo = Path(repo)
        if not self._repo.exists():
            raise FileNotFoundError(repo)
        return repo

    def collect_changes(self) -> list[str]:
        if self._repo is None:
            return []
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=self._repo,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        changed_files: list[str] = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            changed_files.append(line[3:].strip())
        return changed_files
