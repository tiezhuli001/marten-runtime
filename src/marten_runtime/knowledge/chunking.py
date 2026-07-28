from __future__ import annotations

from marten_runtime.knowledge.config import KnowledgeChunkingConfig
from marten_runtime.knowledge.models import KnowledgeChunk


def chunk_text(
    *,
    namespace: str,
    source_id: str,
    text: str,
    config: KnowledgeChunkingConfig,
    metadata: dict[str, object] | None = None,
) -> list[KnowledgeChunk]:
    normalized = str(text or "").strip()
    if not normalized:
        raise ValueError("text is required")
    chunks: list[KnowledgeChunk] = []
    heading = ""
    buffer = ""
    for block in _blocks(normalized):
        maybe_heading = _heading_from_block(block)
        if maybe_heading is not None:
            if buffer.strip():
                chunks.extend(_split_buffer(namespace, source_id, buffer, heading, config, metadata, start=len(chunks)))
                buffer = ""
            heading = maybe_heading
            continue
        if not buffer:
            buffer = block
        elif len(buffer) + 2 + len(block) <= config.target_chars:
            buffer = f"{buffer}\n\n{block}"
        else:
            chunks.extend(_split_buffer(namespace, source_id, buffer, heading, config, metadata, start=len(chunks)))
            buffer = block
    if buffer.strip():
        chunks.extend(_split_buffer(namespace, source_id, buffer, heading, config, metadata, start=len(chunks)))
    return [chunk.model_copy(update={"ordinal": index}) for index, chunk in enumerate(chunks)]


def _blocks(text: str) -> list[str]:
    blocks: list[str] = []
    for raw in text.split("\n\n"):
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        current: list[str] = []
        for line in lines:
            if line.startswith("#"):
                if current:
                    blocks.append("\n".join(current))
                    current = []
                blocks.append(line)
            else:
                current.append(line)
        if current:
            blocks.append("\n".join(current))
    return [block.strip() for block in blocks if block.strip()]


def _heading_from_block(block: str) -> str | None:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if len(lines) == 1 and lines[0].startswith("#"):
        return lines[0].lstrip("#").strip()
    return None


def _split_buffer(
    namespace: str,
    source_id: str,
    buffer: str,
    heading: str,
    config: KnowledgeChunkingConfig,
    metadata: dict[str, object] | None,
    *,
    start: int,
) -> list[KnowledgeChunk]:
    text = buffer.strip()
    chunk_metadata = {**dict(metadata or {})}
    if heading:
        chunk_metadata["chapter"] = heading
    if len(text) <= config.max_chars:
        return [
            KnowledgeChunk.new(
                namespace=namespace,
                source_id=source_id,
                ordinal=start,
                text=text,
                heading=heading,
                metadata=chunk_metadata,
                token_estimate=max(1, len(text) // 2),
            )
        ]
    chunks: list[KnowledgeChunk] = []
    cursor = 0
    while cursor < len(text):
        end = min(len(text), cursor + config.target_chars)
        part = text[cursor:end]
        if len(part) > config.max_chars:
            part = part[: config.max_chars]
            end = cursor + len(part)
        chunks.append(
            KnowledgeChunk.new(
                namespace=namespace,
                source_id=source_id,
                ordinal=start + len(chunks),
                text=part,
                heading=heading,
                metadata=chunk_metadata,
                token_estimate=max(1, len(part) // 2),
            )
        )
        if end >= len(text):
            break
        cursor = max(end - config.overlap_chars, cursor + 1)
    return chunks
