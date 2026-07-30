from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from marten_runtime.bazi_cases.book_extraction import BookProfile


_METHOD_MARKERS = re.compile(r"应期|取象|流年|大运|岁运|伏吟|反吟|合冲刑害|刑冲合害")
_CONDITION_MARKERS = re.compile(r"逢|见|遇|当|如果|若|则|因为|所以|冲|合|刑|害|克|生|引动")
_INSTRUCTION_MARKERS = re.compile(r"要看|需要|应该|可以|方法|规律|代表|说明|判断|推断|原则|条件|关键")
_EXCLUDED = re.compile(r"六爻|卦象|奇门|风水|面相|手相")


@dataclass(frozen=True)
class TimingMethodSection:
    chapter: str
    text: str
    line_start: int
    line_end: int
    method: str


def extract_timing_methods(path: str | Path, profile: BookProfile) -> list[TimingMethodSection]:
    lines = Path(path).read_text(encoding="utf-8").replace("\r\n", "\n").splitlines()
    chapter = ""
    paragraphs: list[tuple[str, int, int, str]] = []
    buffer: list[str] = []
    start = 1
    for number, line in enumerate([*lines, ""], start=1):
        if profile.chapter_pattern.match(line):
            if buffer:
                paragraphs.append(("\n".join(buffer).strip(), start, number - 1, chapter))
                buffer = []
            chapter = line.strip()
            start = number + 1
            continue
        if line.strip():
            if not buffer:
                start = number
            buffer.append(line.strip())
        elif buffer:
            paragraphs.append(("\n".join(buffer).strip(), start, number - 1, chapter))
            buffer = []

    sections: list[TimingMethodSection] = []
    seen: set[str] = set()
    for text, line_start, line_end, paragraph_chapter in paragraphs:
        sentences = [
            item.strip(" \n\t“”")
            for item in re.split(r"(?<=[。！？!?])", text)
            if item.strip(" \n\t“”")
        ]
        for index, sentence in enumerate(sentences):
            if not _is_method(sentence):
                continue
            context = sentences[max(0, index - 1) : min(len(sentences), index + 2)]
            combined = "".join(context)
            digest = hashlib.sha256(combined.encode("utf-8")).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            sections.append(
                TimingMethodSection(
                    chapter=paragraph_chapter,
                    text=combined,
                    line_start=line_start,
                    line_end=line_end,
                    method=_method_label(combined),
                )
            )
    return sections


def render_timing_method_markdown(sections: list[TimingMethodSection]) -> str:
    rendered: list[str] = []
    for section in sections:
        heading = section.chapter or "未命名章节"
        rendered.extend(
            [
                f"# {heading} · {section.method} · 行 {section.line_start}-{section.line_end}",
                "",
                section.text,
                "",
            ]
        )
    return "\n".join(rendered).strip()


def _is_method(text: str) -> bool:
    if len(text) < 25 or len(text) > 600:
        return False
    if _EXCLUDED.search(text) and not re.search(r"八字|四柱|命局", text):
        return False
    if re.search(r"应期|取象", text):
        return bool(_CONDITION_MARKERS.search(text))
    has_time_layer = bool(re.search(r"流年|大运|岁运", text))
    has_relation = bool(re.search(r"伏吟|反吟|三合|三会|六合|冲|刑|害|破|克|合", text))
    return bool(has_time_layer and has_relation and _INSTRUCTION_MARKERS.search(text))


def _method_label(text: str) -> str:
    if re.search(r"婚|夫妻|配偶", text):
        return "婚姻应期"
    if re.search(r"病|健康|死亡|寿命", text):
        return "健康应期"
    if re.search(r"财|破产|发财", text):
        return "财富应期"
    if re.search(r"事业|工作|官", text):
        return "事业应期"
    if re.search(r"父|母|子女|六亲", text):
        return "六亲应期"
    if "取象" in text:
        return "干支取象"
    return "综合应期"
