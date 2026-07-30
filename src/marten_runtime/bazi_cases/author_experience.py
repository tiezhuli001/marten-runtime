from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from marten_runtime.bazi_cases.book_extraction import BookProfile


_DOMAIN_MARKERS = re.compile(
    r"八字|四柱|命局|日主|月令|十神|用神|喜神|忌神|格局|天干|地支|"
    r"大运|流年|应期|婚姻|配偶|财星|官星|印星|食伤|神煞|健康|疾病|伤灾"
)
_METHOD_MARKERS = re.compile(
    r"如果|若|当|逢|见|遇|只有|必须|不能|不宜|可以|应该|判断|推断|"
    r"代表|说明|条件|关键|规律|经验|应验|准确率|取象"
)
_TRIGGER_MARKERS = re.compile(r"大运|流年|岁运|伏吟|三合|三会|六合|冲|刑|害|破|克|生|合")
_EXCEPTION_MARKERS = re.compile(r"但是|但|否则|不能|不宜|不论|并非|不是|没有|除非|前提")
_NON_BAZI = re.compile(r"六爻|卦象|奇门|风水|手相|面相")
_SHENSHA = (
    "天乙贵人", "天德贵人", "月德贵人", "国印贵人", "文昌贵人", "禄神",
    "羊刃", "天医", "将星", "华盖", "金舆", "马星", "驿马", "桃花",
    "空亡", "魁罡", "灾煞", "阴阳差错日", "天罗地网", "丧门", "吊客",
)


@dataclass(frozen=True)
class AuthorChapter:
    title: str
    text: str
    line_start: int
    line_end: int
    topics: tuple[str, ...]


@dataclass(frozen=True)
class AuthorExperienceCard:
    card_id: str
    chapter: str
    topic: str
    conditions: str
    five_element_direction: str
    timing_triggers: tuple[str, ...]
    shensha_support: tuple[str, ...]
    conclusion_scope: str
    exceptions: str
    source_excerpt: str
    line_start: int
    line_end: int


def extract_author_material(
    path: str | Path, profile: BookProfile
) -> tuple[list[AuthorChapter], list[AuthorExperienceCard]]:
    lines = Path(path).read_text(encoding="utf-8").replace("\r\n", "\n").splitlines()
    chapters = _chapters(lines, profile)
    selected = [chapter for chapter in chapters if _is_domain_chapter(chapter)]
    cards: list[AuthorExperienceCard] = []
    seen: set[str] = set()
    for chapter in selected:
        sentences = _sentences_with_lines(chapter)
        for index, (sentence, start, end) in enumerate(sentences):
            if not _is_experience(sentence):
                continue
            context = "".join(item[0] for item in sentences[max(0, index - 1) : index + 2])
            digest = hashlib.sha256(f"{chapter.title}|{context}".encode("utf-8")).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            cards.append(
                AuthorExperienceCard(
                    card_id=f"author_method_{digest[:20]}",
                    chapter=chapter.title,
                    topic=_topic(context),
                    conditions=_conditions(context),
                    five_element_direction=_five_element_direction(context),
                    timing_triggers=tuple(_unique(_TRIGGER_MARKERS.findall(context))),
                    shensha_support=tuple(item for item in _SHENSHA if item in context),
                    conclusion_scope=_conclusion_scope(context),
                    exceptions=_exceptions(context),
                    source_excerpt=context,
                    line_start=start,
                    line_end=end,
                )
            )
    return selected, cards


def render_author_chapters(chapters: list[AuthorChapter]) -> str:
    blocks: list[str] = []
    for chapter in chapters:
        coordinate = f"原文行：{chapter.line_start}-{chapter.line_end}"
        paragraphs = [
            f"[{coordinate}]\n{paragraph.strip()}"
            for paragraph in re.split(r"\n\s*\n", chapter.text)
            if paragraph.strip()
        ]
        blocks.extend(
            [
                f"# {chapter.title}",
                "",
                f"主题：{'、'.join(chapter.topics)}｜{coordinate}",
                "",
                "\n\n".join(paragraphs),
                "",
            ]
        )
    return "\n".join(blocks).strip()


def render_author_experience_cards(cards: list[AuthorExperienceCard]) -> str:
    blocks: list[str] = []
    for card in cards:
        blocks.extend(
            [
                f"# {card.chapter} · {card.topic} · {card.card_id}",
                "",
                f"适用条件：{card.conditions or '结合原文上下文判断'}",
                f"五行方向：{card.five_element_direction or '由原文中的用忌与生克确定'}",
                f"岁运触发：{'、'.join(card.timing_triggers) or '未限定具体岁运触发'}",
                f"神煞辅助：{'、'.join(card.shensha_support) or '无'}",
                f"结论范围：{card.conclusion_scope}",
                f"例外条件：{card.exceptions or '不得脱离原文条件独立使用'}",
                f"原文坐标：{card.line_start}-{card.line_end}",
                "",
                f"原文：{card.source_excerpt}",
                "",
            ]
        )
    return "\n".join(blocks).strip()


def author_material_report(
    chapters: list[AuthorChapter], cards: list[AuthorExperienceCard]
) -> dict[str, object]:
    return {
        "chapter_count": len(chapters),
        "card_count": len(cards),
        "topics": sorted({topic for chapter in chapters for topic in chapter.topics}),
        "card_topics": {
            topic: sum(card.topic == topic for card in cards)
            for topic in sorted({card.topic for card in cards})
        },
    }


def _chapters(lines: list[str], profile: BookProfile) -> list[AuthorChapter]:
    starts = [index for index, line in enumerate(lines) if profile.chapter_pattern.match(line)]
    result: list[AuthorChapter] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        text = "\n".join(lines[start + 1 : end]).strip()
        if not text:
            continue
        result.append(
            AuthorChapter(
                title=lines[start].strip(),
                text=text,
                line_start=start + 1,
                line_end=end,
                topics=tuple(_chapter_topics(text)),
            )
        )
    return result


def _is_domain_chapter(chapter: AuthorChapter) -> bool:
    matches = _DOMAIN_MARKERS.findall(chapter.text)
    if len(matches) < 8:
        return False
    non_bazi = len(_NON_BAZI.findall(chapter.text))
    return non_bazi <= max(3, len(matches) // 3) or "八字" in chapter.title


def _is_experience(sentence: str) -> bool:
    return (
        25 <= len(sentence) <= 800
        and bool(_DOMAIN_MARKERS.search(sentence))
        and bool(_METHOD_MARKERS.search(sentence))
        and (bool(_TRIGGER_MARKERS.search(sentence)) or "用神" in sentence or "神煞" in sentence)
    )


def _sentences_with_lines(chapter: AuthorChapter) -> list[tuple[str, int, int]]:
    result: list[tuple[str, int, int]] = []
    for offset, line in enumerate(chapter.text.splitlines()):
        line_number = chapter.line_start + offset + 1
        for sentence in re.split(r"(?<=[。！？!?])", line):
            normalized = sentence.strip(" \t“”")
            if normalized:
                result.append((normalized, line_number, line_number))
    return result


def _chapter_topics(text: str) -> list[str]:
    return _unique(
        topic
        for marker, topic in (
            ("婚", "婚姻"), ("配偶", "婚姻"), ("病", "健康"), ("健康", "健康"),
            ("财", "财富"), ("事业", "事业"), ("工作", "事业"), ("父", "六亲"),
            ("母", "六亲"), ("子女", "六亲"), ("神煞", "神煞"), ("应期", "应期"),
            ("格局", "格局"), ("用神", "用神"), ("学", "学业"),
        )
        if marker in text
    ) or ["综合方法"]


def _topic(text: str) -> str:
    if "神煞" in text or any(item in text for item in _SHENSHA):
        return "神煞"
    return _chapter_topics(text)[0]


def _conditions(text: str) -> str:
    matched = re.findall(r"[^。！？]{0,80}(?:如果|若|当|逢|见|遇|只有|必须|前提)[^。！？]{0,120}", text)
    return "；".join(_unique(item.strip("，,；; ") for item in matched))[:500]


def _five_element_direction(text: str) -> str:
    matched = re.findall(r"[^。！？]{0,80}(?:用神|喜神|忌神|五行|生克|旺|弱|克|生)[^。！？]{0,120}", text)
    return "；".join(_unique(item.strip() for item in matched))[:500]


def _conclusion_scope(text: str) -> str:
    topics = _chapter_topics(text)
    return f"仅用于{'、'.join(topics)}主题，在原文条件满足时作为作者经验证据"


def _exceptions(text: str) -> str:
    matched = re.findall(r"[^。！？]{0,80}(?:但是|但|否则|不能|不宜|并非|不是|没有|除非|前提)[^。！？]{0,120}", text)
    return "；".join(_unique(item.strip() for item in matched))[:500]


def _unique(values) -> list[str]:  # noqa: ANN001
    return list(dict.fromkeys(value for value in values if value))
