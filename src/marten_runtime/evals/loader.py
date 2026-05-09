from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path

from marten_runtime.evals.models import EvalCaseSpec, EvalSuiteSpec

_FIXTURE_DIRS = {
    "session_history_fixture": "session_histories",
    "memory_fixture": "memory",
    "automation_fixture": "automation",
}


def _load_toml(path: Path) -> dict[str, object]:
    with path.open('rb') as fh:
        return tomllib.load(fh)


def _nearest_evals_root(path: Path) -> Path | None:
    for candidate in [path, *path.parents]:
        if candidate.name == 'evals':
            return candidate
    return None


def _resolve_fixture(case_path: Path, field_name: str, value: str) -> str | None:
    normalized = (value or 'none').strip()
    if normalized in {'', 'none'}:
        return None
    raw = Path(normalized)
    candidates: list[Path] = []
    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append(case_path.parent / raw)
        evals_root = _nearest_evals_root(case_path)
        if evals_root is not None:
            fixture_dir = _FIXTURE_DIRS.get(field_name)
            if fixture_dir is not None:
                candidates.append(evals_root / 'fixtures' / fixture_dir / raw)
        candidates.append(case_path.parent.parent / 'fixtures' / raw)
    for candidate in candidates:
        if candidate.exists():
            return candidate.as_posix()
    raise FileNotFoundError(normalized)


def _sha256_for_files(paths: list[Path]) -> str:
    hasher = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.as_posix()):
        hasher.update(path.as_posix().encode('utf-8'))
        hasher.update(b'\0')
        hasher.update(path.read_bytes())
        hasher.update(b'\0')
    return hasher.hexdigest()


def _default_grader_id(suite_id: str) -> str:
    normalized = (suite_id or "").strip()
    if normalized.startswith("main_chain"):
        return "main_chain_core"
    return normalized


def load_case_spec(path: Path) -> EvalCaseSpec:
    resolved = path.resolve()
    data = _load_toml(resolved)
    case = EvalCaseSpec.model_validate(data)
    fixture_map: dict[str, str] = {}
    for field_name in _FIXTURE_DIRS:
        value = getattr(case.setup, field_name)
        resolved_fixture = _resolve_fixture(resolved, field_name, value)
        if resolved_fixture is not None:
            fixture_map[field_name] = resolved_fixture
    return case.model_copy(update={
        'source_path': resolved.as_posix(),
        'resolved_fixtures': fixture_map,
    })


def load_suite_spec(path: Path) -> EvalSuiteSpec:
    resolved = path.resolve()
    data = _load_toml(resolved)
    suite_grader_id = str(data.get("grader_id") or _default_grader_id(str(data.get("suite_id") or "")))
    case_files = [Path(item) for item in data.get('case_files', [])]
    cases = []
    resolved_case_paths: list[Path] = []
    repo_root = resolved.parents[1] if len(resolved.parents) >= 2 and resolved.parent.name == 'suites' and resolved.parents[1].name == 'evals' else resolved.parent
    for case_file in case_files:
        if case_file.is_absolute():
            case_path = case_file
        else:
            direct_case_path = (resolved.parent / case_file).resolve()
            repo_case_path = (repo_root.parent / case_file).resolve() if repo_root.name == 'evals' else direct_case_path
            case_path = direct_case_path if direct_case_path.exists() else repo_case_path
        if not case_path.exists():
            raise FileNotFoundError(case_path.as_posix())
        resolved_case_paths.append(case_path)
        case = load_case_spec(case_path)
        if case.grader_id is None:
            case = case.model_copy(update={"grader_id": suite_grader_id})
        cases.append(case)
    suite = EvalSuiteSpec.model_validate({**data, 'cases': cases, 'grader_id': suite_grader_id})
    fingerprint_inputs = [resolved, *resolved_case_paths]
    for case in cases:
        for fixture_path in case.resolved_fixtures.values():
            fingerprint_inputs.append(Path(fixture_path))
    return suite.model_copy(update={
        'source_path': resolved.as_posix(),
        'suite_fingerprint': _sha256_for_files(fingerprint_inputs),
        'case_files': [path.as_posix() for path in resolved_case_paths],
    })
