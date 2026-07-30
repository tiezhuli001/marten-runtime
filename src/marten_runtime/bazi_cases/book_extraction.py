from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from marten_runtime.bazi_cases.models import utc_now_iso


_GANZHI = r"[甲乙丙丁戊己庚辛壬癸][子丑寅卯辰巳午未申酉戌亥]"
_NARRATIVE_CHART = re.compile(
    rf"(?P<gender>男命|女命)\s*[：:]\s*"
    rf"(?P<year>{_GANZHI})(?:年)?[，,、\s]+"
    rf"(?P<month>{_GANZHI})(?:月)?[，,、\s]+"
    rf"(?P<day>{_GANZHI})(?:日)?[，,、\s]+"
    rf"(?P<hour>{_GANZHI})(?:时)?"
)
_COMPACT_CHART = re.compile(
    rf"(?P<gender>乾造|坤造|男命|女命)\s*[：:]\s*"
    rf"(?P<year>{_GANZHI})\s+(?P<month>{_GANZHI})\s+"
    rf"(?P<day>{_GANZHI})\s+(?P<hour>{_GANZHI})"
)
_CHAPTER = re.compile(
    r"^\s*第\s*[一二三四五六七八九十百千万零〇\d]+\s*章"
    r"\s*[：:、.．\-—]?\s*.+\s*$"
)
_EXPLICIT_FEEDBACK = re.compile(r"命主反馈|反馈|事实|实际|果然|的确|应验|后来证实")
_NEGATED_FEEDBACK = re.compile(r"(?:没有|未|无)[^。]{0,12}(?:反馈|事实|实际经历|应验)")
_OBSERVED_STATE = re.compile(
    r"(?:命主|此人|该命|该造|他|她|其人)[^。]{0,30}"
    r"(?:已经|曾经|目前|现在|后来|最终|开始|从事|担任|拥有|结婚|离婚|去世|死亡|住院|破产|发家)"
    r"|(?:拥有|现有|身价|资产达到|结婚于|于\d{4}年结婚|在\d{4}年结婚)"
    r"|(?:命主|此人|该命|该造|他|她)[^。]{0,80}(?:急转直下|濒临破产|差点[^。]{0,12}破产)"
)
_PREDICTION_MARKERS = re.compile(r"推断|判断|预测|应当|应该|必然|可能|将会|哪一年|应期")
_NON_BAZI_MARKERS = re.compile(r"六爻|卦象|奇门|风水|手相|面相")
_YEAR = re.compile(r"(?P<year>(?:19|20)\d{2})年")
_DAYUN_CONTEXT = re.compile(r"大运|起运")


@dataclass(frozen=True)
class BookProfile:
    title: str
    author: str = ""
    chapter_pattern: re.Pattern[str] = _CHAPTER
    max_case_lines: int = 360
    excluded_markers: tuple[str, ...] = ("六爻", "卦象", "奇门", "风水")


@dataclass(frozen=True)
class SourceParagraph:
    text: str
    line_start: int
    line_end: int
    chapter: str


@dataclass
class CaseCandidate:
    gender: str
    pillars: list[str]
    dayun: list[str]
    raw_text: str
    source_ref: dict[str, object]
    analysis: str
    predictions: list[dict[str, object]] = field(default_factory=list)
    events: list[dict[str, object]] = field(default_factory=list)
    reviews: list[dict[str, object]] = field(default_factory=list)
    grade: str = "D"
    completeness: float = 0.0
    confidence: float = 0.0
    rejection_reasons: list[str] = field(default_factory=list)

    def as_import_item(self) -> dict[str, object]:
        fingerprint = hashlib.sha256(
            ("|".join(self.pillars) + "|" + str(self.source_ref.get("content_sha256"))
             + "|" + str(self.source_ref.get("line_start"))).encode("utf-8")
        ).hexdigest()
        return {
            "gender": self.gender,
            "pillars": list(self.pillars),
            "dayun": list(self.dayun),
            "raw_case_text": self.raw_text,
            "input_fingerprint": f"sha256:{fingerprint}",
            "analysis_summary": self.analysis[:4000],
            "interpretation": {
                "method": "书籍案例确定性抽取",
                "confidence": self.confidence,
                "source_excerpt": self.analysis[:2000],
            },
            "topic_conclusions": [],
            "predictions": self.predictions,
            "events": self.events,
            "reviews": self.reviews,
            "source_ref": dict(self.source_ref),
            "extraction_quality": {
                "extractor_version": "book.case.extractor.v4",
                "grade": self.grade,
                "completeness": self.completeness,
                "confidence": self.confidence,
                "rejection_reasons": list(self.rejection_reasons),
            },
        }


def extract_book_cases(path: str | Path, profile: BookProfile) -> list[CaseCandidate]:
    source_path = Path(path)
    raw = source_path.read_text(encoding="utf-8")
    normalized = _normalize(raw)
    lines = normalized.splitlines()
    digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    chapters = _chapter_by_line(lines, profile)
    starts = _chart_starts(lines)
    candidates: list[CaseCandidate] = []
    for index, (line_index, match) in enumerate(starts):
        next_start = starts[index + 1][0] if index + 1 < len(starts) else len(lines)
        end = _case_end(
            lines,
            start=line_index,
            next_chart=next_start,
            maximum=line_index + profile.max_case_lines,
            profile=profile,
        )
        block = "\n".join(lines[line_index:end]).strip()
        if not block or _excluded(block[:800], profile):
            continue
        pillars = [match.group(name) for name in ("year", "month", "day", "hour")]
        gender = "male" if match.group("gender") in {"乾造", "男命"} else "female"
        chapter = chapters[line_index]
        source_ref = {
            "title": profile.title,
            "author": profile.author,
            "chapter": chapter,
            "path": str(source_path.resolve()),
            "uri": source_path.resolve().as_uri(),
            "line_start": line_index + 1,
            "line_end": end,
            "content_sha256": digest,
        }
        events, predictions, reviews = _extract_timed_statements(block)
        dayun = _extract_dayun(block)
        grade, completeness, confidence, reasons = _quality(
            dayun=dayun, analysis=block, events=events
        )
        candidates.append(
            CaseCandidate(
                gender=gender,
                pillars=pillars,
                dayun=dayun,
                raw_text=block,
                source_ref=source_ref,
                analysis=_analysis_excerpt(block),
                predictions=predictions,
                events=events,
                reviews=reviews,
                grade=grade,
                completeness=completeness,
                confidence=confidence,
                rejection_reasons=reasons,
            )
        )
    return _deduplicate(candidates)


def extraction_report(candidates: list[CaseCandidate]) -> dict[str, object]:
    grades = {grade: sum(item.grade == grade for item in candidates) for grade in "ABCD"}
    accepted = [item for item in candidates if item.grade in {"A", "B"}]
    return {
        "candidate_count": len(candidates),
        "grade_counts": grades,
        "accepted_count": len(accepted),
        "accepted": [
            {
                "pillars": item.pillars,
                "gender": item.gender,
                "grade": item.grade,
                "chapter": item.source_ref.get("chapter"),
                "line_start": item.source_ref.get("line_start"),
                "event_count": len(item.events),
                "prediction_count": len(item.predictions),
            }
            for item in accepted
        ],
    }


def _normalize(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").replace("戍", "戌")


def _chapter_by_line(lines: list[str], profile: BookProfile) -> list[str]:
    current = ""
    result: list[str] = []
    for line in lines:
        if profile.chapter_pattern.match(line):
            current = line.strip()
        result.append(current)
    return result


def _chart_starts(lines: list[str]) -> list[tuple[int, re.Match[str]]]:
    starts: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        compact = " ".join(line.split())
        match = _NARRATIVE_CHART.search(compact) or _COMPACT_CHART.search(compact)
        if match is not None:
            starts.append((index, match))
    return starts


def _case_end(
    lines: list[str], *, start: int, next_chart: int, maximum: int, profile: BookProfile
) -> int:
    chapter_boundaries = 0
    hard_end = min(next_chart, maximum, len(lines))
    for index in range(start + 1, hard_end):
        if profile.chapter_pattern.match(lines[index]):
            chapter_boundaries += 1
            if chapter_boundaries >= 2:
                return index
    return hard_end


def _excluded(text: str, profile: BookProfile) -> bool:
    return any(marker in text for marker in profile.excluded_markers) and not re.search(r"八字|四柱|命局", text)


def _extract_dayun(block: str) -> list[str]:
    result: list[str] = []
    for line in block.splitlines():
        if not _DAYUN_CONTEXT.search(line):
            continue
        result.extend(re.findall(_GANZHI, line))
    return list(dict.fromkeys(result))[:12]


def _extract_timed_statements(
    block: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    events: list[dict[str, object]] = []
    predictions: list[dict[str, object]] = []
    sentences = [item.strip(" \n\t“”") for item in re.split(r"[。！？!?]\s*", block) if item.strip()]
    for sentence in sentences:
        if len(sentence) < 8:
            continue
        years = [match.group("year") for match in _YEAR.finditer(sentence)]
        is_feedback = bool(
            not _NEGATED_FEEDBACK.search(sentence)
            and (_EXPLICIT_FEEDBACK.search(sentence) or _OBSERVED_STATE.search(sentence))
        )
        is_prediction = bool(_PREDICTION_MARKERS.search(sentence))
        topic = _topic(sentence)
        payload = {
            "topic": topic,
            "subject": _subject(sentence, topic=topic),
            "source_excerpt": sentence[:1000],
        }
        if is_feedback and not (is_prediction and not _EXPLICIT_FEEDBACK.search(sentence)):
            event_id = "bevt_book_" + hashlib.sha256(sentence.encode("utf-8")).hexdigest()[:16]
            events.append({
                "category": payload.pop("topic"),
                "event_id": event_id,
                "description": sentence[:1000],
                "evidence_type": "document_verified",
                "time_start": years[-1] if years else "",
                "time_precision": "exact_year" if years else "unknown",
                **payload,
            })
        elif is_prediction and years:
            prediction_id = "bpred_book_" + hashlib.sha256(sentence.encode("utf-8")).hexdigest()[:16]
            prediction_year = years[-1] if len(years) > 1 and re.search(r"推迟|而是|改在", sentence) else years[0]
            predictions.append({
                **payload,
                "prediction_id": prediction_id,
                "time_start": prediction_year,
                "time_precision": "exact_year",
                "conclusion": sentence[:2000],
                "status": "pending",
                "triggers": [],
            })
    events, predictions = events[:20], predictions[:20]
    reviews: list[dict[str, object]] = []
    for event in events:
        related = [
            prediction for prediction in predictions
            if prediction.get("topic") == event.get("category")
            and prediction.get("subject") == event.get("subject")
        ]
        if not related:
            continue
        prediction = related[-1]
        event["linked_prediction_ids"] = [prediction["prediction_id"]]
        same_year = bool(
            event.get("time_start")
            and event.get("time_start") == prediction.get("time_start")
        )
        reviews.append(
            {
                "prediction_id": prediction["prediction_id"],
                "event_id": event["event_id"],
                "outcome": "confirmed" if same_year else "partial",
                "notes": "书中后续反馈与前述判断的结构化关联。",
                "created_at": utc_now_iso(),
            }
        )
    return events, predictions, reviews


def _topic(text: str) -> str:
    for marker, category in (
        ("婚", "marriage"), ("妻", "marriage"), ("夫", "marriage"),
        ("财", "wealth"), ("资产", "wealth"), ("破产", "wealth"),
        ("病", "health"), ("健康", "health"), ("死亡", "health"), ("去世", "health"),
        ("工作", "career"), ("事业", "career"), ("经商", "career"),
        ("学", "education"), ("子女", "children"), ("官司", "legal"),
    ):
        if marker in text:
            return category
    return "other"


def _subject(text: str, *, topic: str) -> str:
    if topic == "marriage" and re.search(r"结婚|离婚|婚姻", text):
        return "self"
    if re.search(r"父亲|父命|父", text):
        return "father"
    if re.search(r"母亲|母命|老母", text):
        return "mother"
    if re.search(r"妻子|老婆|丈夫|老公|配偶", text):
        return "spouse"
    if re.search(r"子女|儿子|女儿|孩子", text):
        return "child"
    if re.search(r"公司|单位|岗位|事业平台", text):
        return "career_platform"
    if re.search(r"房屋|房产|资产", text):
        return "asset"
    return "self"


def _analysis_excerpt(block: str) -> str:
    lines = [line.strip(" \t“”") for line in block.splitlines() if line.strip()]
    return "\n".join(lines[:30])[:4000]


def _quality(
    *, dayun: list[str], analysis: str, events: list[dict[str, object]]
) -> tuple[str, float, float, list[str]]:
    has_analysis = len(analysis) >= 120
    has_feedback = bool(events)
    completeness = (0.35 + 0.15 * bool(dayun) + 0.25 * has_analysis + 0.25 * has_feedback)
    if has_analysis and has_feedback:
        grade = "A" if dayun else "B"
    elif has_analysis:
        grade = "C"
    else:
        grade = "D"
    reasons: list[str] = []
    if not dayun:
        reasons.append("missing_dayun")
    if not has_feedback:
        reasons.append("missing_feedback")
    if not has_analysis:
        reasons.append("insufficient_analysis")
    confidence = min(0.98, 0.55 + 0.15 * bool(dayun) + 0.20 * has_feedback)
    return grade, round(completeness, 3), round(confidence, 3), reasons


def _deduplicate(candidates: list[CaseCandidate]) -> list[CaseCandidate]:
    selected: dict[tuple[object, ...], CaseCandidate] = {}
    rank = {"A": 4, "B": 3, "C": 2, "D": 1}
    for item in candidates:
        event_key = tuple(
            (event.get("category"), event.get("time_start"), event.get("subject"))
            for event in item.events
        )
        key = (*item.pillars, item.gender, event_key, item.source_ref.get("chapter"))
        current = selected.get(key)
        if current is None or rank[item.grade] > rank[current.grade]:
            selected[key] = item
    return list(selected.values())
