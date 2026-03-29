from marten_runtime.memory.models import MemoryEntry, Note, Persona


class MemoryStore:
    def __init__(self) -> None:
        self._notes: dict[str, Note] = {}
        self._personas: dict[str, Persona] = {}
        self._entries: dict[str, MemoryEntry] = {}

    def save_note(self, note: Note) -> None:
        self._notes[note.note_id] = note

    def get_note(self, note_id: str) -> Note:
        return self._notes[note_id]

    def save_persona(self, persona: Persona) -> None:
        self._personas[persona.persona_id] = persona

    def get_persona(self, persona_id: str) -> Persona:
        return self._personas[persona_id]

    def save_entry(self, entry: MemoryEntry) -> None:
        self._entries[entry.entry_id] = entry

    def list_entries(self, session_key: str) -> list[MemoryEntry]:
        return [item for item in self._entries.values() if item.session_key == session_key]
