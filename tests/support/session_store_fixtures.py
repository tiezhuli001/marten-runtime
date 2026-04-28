from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator, TypeVar

from marten_runtime.session.sqlite_store import SQLiteSessionStore

StoreT = TypeVar("StoreT", bound=SQLiteSessionStore)


@contextmanager
def temporary_sqlite_session_store(
    *,
    store_cls: type[StoreT] = SQLiteSessionStore,
    filename: str = "sessions.sqlite3",
) -> Iterator[StoreT]:
    with TemporaryDirectory() as tmpdir:
        yield store_cls(Path(tmpdir) / filename)
