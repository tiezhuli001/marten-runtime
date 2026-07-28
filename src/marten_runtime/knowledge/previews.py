from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from threading import RLock
from typing import Callable


_PREVIEW_ID_PATTERN = re.compile(r"^kprv_[0-9a-f]{12}$")


class KnowledgePreviewStore:
    def __init__(self, staging_root: str | Path, *, ttl_seconds: float = 24 * 60 * 60) -> None:
        self.staging_root = Path(staging_root)
        self.records_root = self.staging_root.parent / "previews"
        self.records_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.records_root.chmod(0o700)
        self.ttl_seconds = float(ttl_seconds)
        self._lock = RLock()
        self.cleanup_expired()

    def record(
        self,
        *,
        preview_id: str,
        namespace: str,
        staged_file_path: str,
        source: dict[str, object],
        preview: dict[str, object],
    ) -> dict[str, object]:
        directory = self._directory(preview_id)
        payload = {
            "preview_id": preview_id,
            "namespace": namespace,
            "status": "ready",
            "staged_file_path": staged_file_path,
            "source": source,
            "preview": preview,
            "created_at_epoch": time.time(),
            "job_id": "",
        }
        self._write(directory, payload)
        return self.public(payload)

    def get(self, *, namespace: str, preview_id: str) -> dict[str, object]:
        with self._lock:
            payload = self._load(preview_id)
            if str(payload.get("namespace") or "") != namespace:
                raise KeyError(preview_id)
            self._ensure_fresh(payload)
            return payload

    def publish(
        self,
        *,
        namespace: str,
        preview_id: str,
        publisher: Callable[..., dict[str, object]],
    ) -> dict[str, object]:
        with self._lock:
            payload = self.get(namespace=namespace, preview_id=preview_id)
            if str(payload.get("status") or "") == "published":
                return self.public(payload)
            staged_file_path = str(payload.get("staged_file_path") or "")
            file_path = self.staging_root / staged_file_path
            source = dict(payload.get("source") or {})
            expected_digest = str(dict(source.get("metadata") or {}).get("content_sha256") or "")
            actual_digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
            if not expected_digest or actual_digest != expected_digest:
                raise ValueError("preview content digest changed before publish")
            result = publisher(
                namespace=namespace,
                file_path=str(file_path),
                staged_file_path=staged_file_path,
                source=source,
            )
            payload["status"] = "published"
            payload["job_id"] = str(result.get("job_id") or "")
            payload["publish_result"] = result
            self._write(self._directory(preview_id), payload)
            return self.public(payload)

    def delete(self, *, namespace: str, preview_id: str) -> bool:
        with self._lock:
            payload = self.get(namespace=namespace, preview_id=preview_id)
            if str(payload.get("status") or "") == "published":
                return False
            shutil.rmtree(self._directory(preview_id))
            shutil.rmtree(self._staged_directory(preview_id), ignore_errors=True)
            return True

    def cleanup_expired(self) -> int:
        removed = 0
        cutoff = time.time() - self.ttl_seconds
        with self._lock:
            for directory in self.records_root.iterdir():
                if not directory.is_dir() or directory.is_symlink() or not _PREVIEW_ID_PATTERN.fullmatch(directory.name):
                    continue
                try:
                    payload = self._load(directory.name)
                    created = float(payload.get("created_at_epoch") or 0.0)
                except (OSError, TypeError, ValueError, json.JSONDecodeError, KeyError):
                    continue
                if created <= 0 or created > cutoff:
                    continue
                shutil.rmtree(directory, ignore_errors=True)
                shutil.rmtree(self._staged_directory(directory.name), ignore_errors=True)
                removed += 1
        return removed

    @staticmethod
    def public(payload: dict[str, object]) -> dict[str, object]:
        result = {
            "ok": True,
            "preview_id": str(payload.get("preview_id") or ""),
            "namespace": str(payload.get("namespace") or ""),
            "status": str(payload.get("status") or ""),
            **dict(payload.get("preview") or {}),
        }
        job_id = str(payload.get("job_id") or "")
        if job_id:
            result["job_id"] = job_id
        publish_result = payload.get("publish_result")
        if isinstance(publish_result, dict):
            result["publish_result"] = dict(publish_result)
        return result

    def _load(self, preview_id: str) -> dict[str, object]:
        path = self._directory(preview_id) / "preview.json"
        if not path.exists():
            raise KeyError(preview_id)
        return dict(json.loads(path.read_text(encoding="utf-8")))

    def _directory(self, preview_id: str) -> Path:
        if not _PREVIEW_ID_PATTERN.fullmatch(preview_id):
            raise KeyError(preview_id)
        root = self.records_root.resolve()
        directory = (root / preview_id).resolve()
        if directory.parent != root:
            raise KeyError(preview_id)
        return directory

    def _staged_directory(self, preview_id: str) -> Path:
        if not _PREVIEW_ID_PATTERN.fullmatch(preview_id):
            raise KeyError(preview_id)
        root = self.staging_root.resolve()
        directory = (root / preview_id).resolve()
        if directory.parent != root:
            raise KeyError(preview_id)
        return directory

    def _ensure_fresh(self, payload: dict[str, object]) -> None:
        created = float(payload.get("created_at_epoch") or 0.0)
        if created <= 0 or time.time() - created > self.ttl_seconds:
            preview_id = str(payload.get("preview_id") or "")
            directory = self._directory(preview_id)
            if directory.exists():
                shutil.rmtree(directory, ignore_errors=True)
            shutil.rmtree(self._staged_directory(preview_id), ignore_errors=True)
            raise TimeoutError(preview_id)

    @staticmethod
    def _write(directory: Path, payload: dict[str, object]) -> None:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        path = directory / "preview.json"
        temporary = directory / "preview.json.tmp"
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(path)
