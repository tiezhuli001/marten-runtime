from pydantic import BaseModel, Field


class Note(BaseModel):
    note_id: str
    session_key: str
    content: str


class Persona(BaseModel):
    persona_id: str
    summary: str


class MemoryEntry(BaseModel):
    entry_id: str
    session_key: str
    memory_type: str
    text: str
    tags: list[str] = Field(default_factory=list)
