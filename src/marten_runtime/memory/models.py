from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field


class MemoryDocument(BaseModel):
    user_id: str
    path: Path
    available: bool = True
    text: str = ""
    sections: dict[str, list[str]] = Field(default_factory=dict)
