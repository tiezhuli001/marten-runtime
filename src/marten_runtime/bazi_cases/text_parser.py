from __future__ import annotations

import hashlib
import re


_STEMS = set("甲乙丙丁戊己庚辛壬癸")
_BRANCHES = set("子丑寅卯辰巳午未申酉戌亥")
_TOPICS = {
    "事业": "career", "财运": "wealth", "婚姻": "marriage", "健康": "health",
    "学历": "education", "子女": "children", "家庭": "family", "迁移": "relocation",
    "命主反馈": "other", "反馈": "other", "原局": "other", "从吗": "other",
    "适合去哪里": "relocation", "明后年": "other", "另外": "other",
    "职业": "career", "行业": "career", "工作": "career", "财富": "wealth",
    "财富等级": "wealth", "孩子": "children", "学习": "education", "身体": "health",
    "背景": "other", "整体": "other", "总结": "other", "官司": "legal",
    "家境": "family", "父母": "family", "妻子": "marriage", "婚姻宫": "marriage",
    "建议": "other", "问题": "other", "答": "other", "格局": "other", "旺衰": "other",
    "调候": "other", "病药": "other", "用神": "other", "忌神": "other", "六亲": "family",
}


def parse_case_text(text: str) -> list[dict[str, object]]:
    normalized = str(text or "").replace("：", ":").strip()
    if not normalized:
        return []
    markdown_starts = list(re.finditer(r"(?m)^\s*###\s+[^\n]+", normalized))
    starts = markdown_starts or list(
        re.finditer(r"(?m)^\s*(男|女)\s*:\s*([^\n]*)", normalized)
    )
    blocks = [
        normalized[match.start() : starts[index + 1].start() if index + 1 < len(starts) else len(normalized)]
        for index, match in enumerate(starts)
    ]
    return [parsed for block in blocks if (parsed := _parse_block(block)) is not None]


def _parse_block(block: str) -> dict[str, object] | None:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if len(lines) < 3:
        return None
    header = _header(lines)
    if header is None:
        return None
    gender_text, label, content_start = header
    pillars, pillar_index, pillar_end = _find_pillars(lines, start=content_start)
    if not pillars:
        return None
    dayun, dayun_index, dayun_end = _find_dayun(lines, start=pillar_end + 1)
    sections = _sections(lines[max(pillar_end, dayun_end) + 1 :])
    feedbacks = [item for item in sections if item[0] in {"命主反馈", "反馈"}]
    observed = _observed_items([item for item in sections if item not in feedbacks])
    predictions = _prediction_items([item for item in sections if item not in feedbacks])
    conclusions = [item for item in sections if item not in feedbacks]
    raw_digest = hashlib.sha256(block.encode("utf-8")).hexdigest()
    return {
        "label": label,
        "gender": "male" if gender_text == "男" else "female",
        "pillars": pillars,
        "dayun": dayun,
        "raw_case_text": block.strip(),
        "input_fingerprint": f"sha256:{raw_digest}",
        "analysis_summary": "\n".join(f"{label}：{content}" for label, content in conclusions),
        "interpretation": _interpretation(conclusions),
        "topic_conclusions": [
            {
                "topic": _TOPICS.get(label, "other"),
                "conclusion": content,
                "basis": [],
                "source_excerpt": f"{label}：{content}",
            }
            for label, content in conclusions
        ],
        "predictions": [
            {
                "topic": _TOPICS.get(label, "other"),
                "conclusion": content,
                "time_start": _first_year(content),
                "time_precision": "exact_year" if _first_year(content) else "unknown",
                "triggers": [],
                "status": "pending",
                "source_excerpt": f"{label}：{content}",
            }
            for label, content in predictions
        ],
        "events": [
            {
                "category": _TOPICS.get(label, "other"),
                "description": content,
                "evidence_type": "user_reported",
                "time_start": _first_year(content),
                "time_precision": "exact_year" if _first_year(content) else "unknown",
                "source_excerpt": f"{label}：{content}",
            }
            for label, content in feedbacks + observed
        ],
    }


def _header(lines: list[str]) -> tuple[str, str, int] | None:
    first = re.sub(r"^###\s*", "", lines[0]).strip()
    gender = re.search(r"(男|女)", first)
    if gender is not None:
        label = re.sub(r"[男女]\s*: ?", "", first).strip(" :-")
        return gender.group(1), label, 1
    for index in range(1, min(4, len(lines))):
        match = re.match(r"^(男|女)\s*:\s*(.*)$", lines[index])
        if match is not None:
            return match.group(1), first or match.group(2).strip(), index + 1
    match = re.match(r"^(男|女)\s*:\s*(.*)$", first)
    return (match.group(1), match.group(2).strip(), 1) if match is not None else None


def _find_pillars(lines: list[str], *, start: int) -> tuple[list[str], int, int]:
    pairs, index = _find_pairs(
        lines, start=start, first=_STEMS, second=_BRANCHES, exact_count=4
    )
    if pairs:
        return pairs, index, index + 1
    for index in range(start, len(lines) - 3):
        values = [_single_ganzhi(lines[index + offset]) for offset in range(4)]
        if all(values):
            return [str(item) for item in values], index, index + 3
    return [], -1, -1


def _find_dayun(lines: list[str], *, start: int) -> tuple[list[str], int, int]:
    index = next(
        (i for i in range(start, min(len(lines), start + 4)) if lines[i].startswith("大运")),
        -1,
    )
    if index < 0:
        return [], -1, -1
    inline = re.findall(r"[甲乙丙丁戊己庚辛壬癸][子丑寅卯辰巳午未申酉戌亥]", lines[index])
    if inline:
        return inline, index, index
    top = re.findall(r"[甲乙丙丁戊己庚辛壬癸]", lines[index].partition(":")[2])
    if top and index + 1 < len(lines):
        bottom = re.findall(r"[子丑寅卯辰巳午未申酉戌亥]", lines[index + 1])
        if len(top) == len(bottom):
            return [stem + branch for stem, branch in zip(top, bottom)], index, index + 1
    for candidate in range(index + 1, min(len(lines), index + 4)):
        values = re.findall(r"[甲乙丙丁戊己庚辛壬癸][子丑寅卯辰巳午未申酉戌亥]", lines[candidate])
        if len(values) >= 2:
            return values, index, candidate
    pairs, pair_index = _find_pairs(
        lines, start=index + 1, first=_STEMS, second=_BRANCHES
    )
    return (pairs, index, pair_index + 1) if pairs else ([], index, index)


def _single_ganzhi(line: str) -> str:
    match = re.fullmatch(r"\s*([甲乙丙丁戊己庚辛壬癸][子丑寅卯辰巳午未申酉戌亥])\s*", line)
    return match.group(1) if match else ""


def _find_pairs(
    lines: list[str], *, start: int, first: set[str], second: set[str],
    exact_count: int | None = None,
) -> tuple[list[str], int]:
    for index in range(start, len(lines) - 1):
        top = _tokens(lines[index])
        bottom = _tokens(lines[index + 1])
        count_is_valid = len(top) == exact_count if exact_count is not None else len(top) >= 4
        if len(top) == len(bottom) and count_is_valid and set(top) <= first and set(bottom) <= second:
            return [top[position] + bottom[position] for position in range(len(top))], index
    return [], -1


def _tokens(line: str) -> list[str]:
    return [token for token in re.split(r"\s+", line.strip()) if token]


def _sections(lines: list[str]) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_label = "原局"
    current: list[str] = []
    for line in lines:
        match = re.match(r"^([^:]{1,12}):\s*(.*)$", line)
        if match and match.group(1).strip() in _TOPICS:
            if current:
                sections.append((current_label, " ".join(current)))
            current_label = match.group(1).strip()
            current = [match.group(2).strip()] if match.group(2).strip() else []
        else:
            current.append(line)
    if current:
        sections.append((current_label, " ".join(current)))
    return [(label, content) for label, content in sections if content]


def _looks_predictive(text: str) -> bool:
    return bool(re.search(r"(?:(?:19|20)?\d{2})年|未来|明年|后年|下个大运|会|可能|迹象", text))


def _looks_observed(label: str, text: str) -> bool:
    if label == "背景":
        return True
    return bool(
        re.search(
            r"命主反馈|反馈|目前|已经|实际|身价|资产|录取|离婚|已离异|结婚|"
            r"(?:学历|教育)[^。]{0,30}毕业|学历是|开始创业|"
            r"(?:做|搞)[^，。]{0,20}(?:行业|工作|的)|干[^，。]{0,20}(?:公司|行业|工作)|"
            r"有[一二三四五六七八九两\d]+个(?:孩子|小孩|小朋友)|"
            r"[一二三四五六七八九两\d]+个?(?:孩子|女儿|儿子)",
            text,
        )
    )


def _observed_items(sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
    observed: list[tuple[str, str]] = []
    for label, content in sections:
        for sentence in _sentences(content):
            explicit_feedback = bool(
                re.search(r"命主反馈|反馈|目前|已经|实际|身价|资产", sentence)
            )
            if _looks_observed(label, sentence) and (
                explicit_feedback or not _looks_predictive(sentence)
            ):
                observed.append((label, sentence))
    return observed


def _prediction_items(sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
    predictions: list[tuple[str, str]] = []
    for label, content in sections:
        for sentence in _sentences(content):
            if label == "明后年" or _looks_predictive(sentence):
                predictions.append((label, sentence))
    return predictions


def _sentences(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"(?<=[。！？?])\s*", text) if item.strip()]


def _first_year(text: str) -> str:
    match = re.search(r"((?:19|20)\d{2})年", text)
    return match.group(1) if match else ""


def _interpretation(conclusions: list[tuple[str, str]]) -> dict[str, object]:
    original = " ".join(
        content for label, content in conclusions
        if label in {"原局", "从吗", "格局", "旺衰", "调候", "病药", "用神", "忌神"}
    )
    useful = re.findall(r"(?:用|喜)([木火土金水])", original)
    unfavorable = re.findall(r"(?:忌|不喜)([木火土金水])", original)
    return {
        "method": "文本案例抽取",
        "strength": next((word for word in ("身弱", "身旺", "从格", "偏弱", "偏旺") if word in original), ""),
        "pattern": "",
        "useful_elements": list(dict.fromkeys(useful)),
        "unfavorable_elements": list(dict.fromkeys(unfavorable)),
        "basis": [],
        "confidence": 0.5,
        "source_excerpt": original[:2000],
    }
