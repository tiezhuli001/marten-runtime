from __future__ import annotations

import re


_SECTION_TITLES = (
    "命盘",
    "原局格局喜用",
    "大运",
    "健康注意",
    "学历",
    "事业",
    "婚姻",
    "六亲",
    "财富等级",
    "过三关",
    "参考依据",
)
_YEAR_PATTERN = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_RELATION_PATTERN = re.compile(r"生|克|合|冲|刑|害|伏吟|引动")
_BODY_PATTERN = re.compile(
    r"头|胆|肝|眼|心|血|口|舌|牙|鼻|脾|胃|皮肤|肌肉|肺|胸|"
    r"骨|肾|泌尿|妇科|生殖|腿|脚|手"
)
_EVENT_CATEGORIES = {
    "education_or_work": ("学业", "升学", "考试", "工作", "事业", "入职", "转岗"),
    "relationship": ("感情", "恋爱", "婚恋", "姻缘", "结婚", "婚姻", "对象"),
    "self_health": ("本人健康", "本人身体", "检查", "治疗", "住院", "开刀", "手术"),
    "parent_health": ("父亲", "母亲", "父母", "长辈"),
}
_MULTI_EVENT_MARKERS = ("或", "也可能", "以及", "且", "伴随", "同步")
_GENERIC_EVENT_TEXTS = {
    "学业", "工作", "事业", "婚恋", "恋爱", "婚姻",
    "健康", "本人健康", "父亲", "母亲", "父母", "六亲",
}
_VAGUE_EVENT_PATTERN = re.compile(
    r"(?:工作平台|居住环境|工作环境|家中长辈事务|长辈|父母事务|家宅事务|"
    r"感情与事业|感情和事业|关系与工作|关系和工作)\s*$"
)
_VERIFIABLE_EVENT_PATTERN = re.compile(
    r"升学|毕业|转学|求学|离家|转专业|考试|入职|入行|离职|辞职|失业|转岗|调动|"
    r"换工作|换行业|换平台|换城市|换住处|切换|变化|调整|变动|职责|重排|创业|签约|"
    r"晋升|降职|考核|搬迁|搬家|办公地点|买房|卖房|置业|恋爱|分手|订婚|结婚|离婚|生育|怀孕|波动|"
    r"住院|手术|开刀|体检|检查|治疗|受伤|事故|确诊|收入|压力显著"
)
_DIRECT_FATHER_IDENTITY_PATTERN = re.compile(
    r"[甲乙丙丁戊己庚辛壬癸](?:木|火|土|金|水)?(?:为|是|属)?偏财(?:到位)?[，,]?"
    r"(?:可指|可作|即为|就是|代表|视为|作|指)父星[，,]?(?:且|并)?"
)
_DIRECT_MOTHER_IDENTITY_PATTERN = re.compile(
    r"[甲乙丙丁戊己庚辛壬癸](?:木|火|土|金|水)?(?:为|是|属)?正印(?:到位)?[，,]?"
    r"(?:可指|可作|即为|就是|代表|视为|作|指)母星[，,]?(?:且|并)?"
)
_UNSUPPORTED_RELATIONSHIP_RISK_PATTERN = re.compile(
    r"二婚.{0,16}(?:不高|不重|不大|不能|无法|不属|没有|不足|不支持)"
    r"|(?:不足以|不足|不能|无法|不宜|不作|未能|没有|不支持).{0,16}二婚"
    r"|外缘(?:风险)?.{0,16}(?:不高|不重|不大|不明显|不能|无法|没有|不足|不支持)"
    r"|(?:不足以|不足|不能|无法|不宜|不作|未能|没有|不支持).{0,16}外缘"
)


def normalize_bazi_timing_contract_text(text: str) -> str:
    normalized_lines: list[str] = []
    current_section: str | None = None
    for raw_line in str(text or "").splitlines():
        line = raw_line
        heading = next(
            (
                section
                for section in _SECTION_TITLES
                if _has_bazi_section_heading(line, section)
            ),
            None,
        )
        if heading is not None:
            current_section = heading
        if current_section == "婚姻" and (
            _UNSUPPORTED_RELATIONSHIP_RISK_PATTERN.search(line)
            or "二婚" in line
            or "外缘" in line
        ):
            continue
        if current_section == "过三关" and _YEAR_PATTERN.search(line):
            parts = re.split(r"[｜|]", line, maxsplit=2)
            if len(parts) >= 2:
                parts[1] = _concrete_verification_event_text(parts[1])
                line = "｜".join(parts)
        if re.search(r"流年.{0,40}偏财.{0,16}父星", line):
            line = _DIRECT_FATHER_IDENTITY_PATTERN.sub("", line)
        if re.search(r"流年.{0,40}正印.{0,16}母星", line):
            line = _DIRECT_MOTHER_IDENTITY_PATTERN.sub("", line)
        line = line.replace("引出", "引动").replace("发动", "引动")
        line = re.sub(r"[，,]\s*(?=[；;。])", "", line)
        line = re.sub(r"([；;])\s*[，,]", r"\1", line)
        normalized_lines.append(line)
    return _ensure_bounded_parent_health("\n".join(normalized_lines).strip())


def _ensure_bounded_parent_health(text: str) -> str:
    kinship = section_text(text, "六亲")
    if not kinship:
        return text
    missing = [
        relative
        for relative in ("父亲", "母亲")
        if not _has_relative_health_timing(kinship, relative)
    ]
    if not missing:
        return text
    span = _section_span(text, "六亲")
    if span is None:
        return text
    additions = "\n".join(
        f"- {relative}：本轮未形成可靠高信号健康应期。"
        for relative in missing
    )
    replacement = f"{text[span[0]:span[1]].rstrip()}\n{additions}\n\n"
    return f"{text[:span[0]]}{replacement}{text[span[1]:].lstrip()}".strip()


def bazi_timing_contract_violations(text: str) -> list[str]:
    marriage = section_text(text, "婚姻")
    health = section_text(text, "健康注意")
    kinship = section_text(text, "六亲")
    wealth = section_text(text, "财富等级")
    verification = section_text(text, "过三关")
    violations: list[str] = []
    if _has_invalid_peach_blossom_year(text, marriage):
        violations.append("婚姻栏宣称的桃花流年与命局日支公式不一致")
    if re.search(
        r"二婚.{0,16}(?:不高|不重|不大|不能|无法|不属|没有)"
        r"|(?:不足以|不能|无法|不宜|不作|未能|没有).{0,16}二婚",
        marriage,
    ):
        violations.append("婚姻栏在无明确风险结论时仍讨论二婚")
    if re.search(
        r"虽有外缘|外缘(?:风险)?.{0,12}(?:不高|不重|不大|不明显|不能|无法|没有)"
        r"|(?:不足以|不能|无法|不宜|不作|未能|没有).{0,16}外缘",
        marriage,
    ):
        violations.append("婚姻栏在无明确风险结论时仍讨论外缘")
    if _uses_year_branch_combine_as_marriage_signal(marriage):
        violations.append("婚姻栏把只合年支误作夫妻宫信号")
    if not _has_health_timing(health):
        violations.append("健康栏缺少具体年份、身体部位、干支作用和检查治疗类事件")
    for relative in ("父亲", "母亲"):
        if not _has_relative_health_timing(kinship, relative):
            violations.append(f"六亲栏缺少{relative}独立的年份、部位和岁运触发关系")
    if re.search(r"流年.{0,24}(?:偏财.{0,12}父星|正印.{0,12}母星)", kinship):
        violations.append("六亲栏按流年自身十神直接指定父母身份")
    if _has_generic_verification_event(verification):
        violations.append("过三关包含栏目名称，缺少可核验的具体事件")
    if _has_multi_topic_verification_event(verification):
        violations.append("过三关同一行混入多个事件主题")
    if _has_dangling_verification_event(verification):
        violations.append("过三关包含未完成的事件描述")
    wealth_has_projection = bool(
        re.search(r"[×*]|年均可积累|累计.{0,8}\d+\s*万", wealth)
        or re.search(r"\d+(?:\.\d+)?\s*(?:[-~—至到]\s*\d+(?:\.\d+)?\s*)?万(?:元)?", wealth)
        and re.search(r"预计|估算|推算|可达|总资产|净积累|资产等级|普通积累|小康|小富|中富", wealth)
    )
    wealth_has_real_baseline = _has_real_wealth_baseline(wealth)
    wealth_has_bazi_estimate = _has_bazi_wealth_estimate(wealth)
    if wealth and not wealth_has_bazi_estimate:
        violations.append("财富栏缺少多路径结构评分与命理年收入能力区间")
    if wealth_has_projection and not wealth_has_real_baseline and not wealth_has_bazi_estimate:
        violations.append("财富栏使用了用户未提供的现实收入或资产基线")
    if not wealth_has_real_baseline and re.search(
        r"总资产.{0,20}\d+(?:\.\d+)?\s*(?:[-~—至到]\s*\d+(?:\.\d+)?\s*)?万",
        wealth,
    ):
        violations.append("财富栏在缺少资产负债基线时推算总资产")
    return violations


def _has_real_wealth_baseline(text: str) -> bool:
    marker = r"用户(?:已)?提供|现实基线|当前(?:年)?收入|现有资产|负债|储蓄率"
    for clause in re.split(r"[。；;\n]", str(text or "")):
        if re.search(rf"(?:未提供|没有提供|缺少|无法提供).{{0,40}}(?:{marker})", clause):
            continue
        if re.search(
            rf"(?:{marker}).{{0,20}}\d+(?:\.\d+)?\s*(?:万(?:元)?|%|％)",
            clause,
        ):
            return True
    return False


def _has_bazi_wealth_estimate(text: str) -> bool:
    normalized = re.sub(r"[*_`]+", "", str(text or ""))
    score_match = re.search(
        r"财富结构分\s*[：:]?\s*(?P<score>\d+)\s*/\s*9"
        r".{0,40}?成局路径\s*(?P<path>\d+)\s*\+\s*承载\s*(?P<capacity>\d+)"
        r"\s*\+\s*大运\s*(?P<dayun>\d+)\s*-\s*制约\s*(?P<constraint>\d+)",
        normalized,
    )
    if score_match is None:
        return False
    values = {key: int(value) for key, value in score_match.groupdict().items()}
    if not (
        0 <= values["path"] <= 3
        and 0 <= values["capacity"] <= 2
        and 0 <= values["dayun"] <= 3
        and 0 <= values["constraint"] <= 3
    ):
        return False
    calculated = max(
        0,
        min(
            9,
            values["path"] + values["capacity"] + values["dayun"] - values["constraint"],
        ),
    )
    if values["score"] != calculated:
        return False
    expected_range = {
        0: (5, 15), 1: (5, 15), 2: (5, 15),
        3: (15, 30), 4: (15, 30),
        5: (30, 60), 6: (30, 60),
        7: (50, 100), 8: (50, 100),
        9: (80, 150),
    }[calculated]
    range_match = re.search(
        r"命理年收入能力区间.{0,16}?(?P<low>\d+)\s*[-~—至到]\s*"
        r"(?P<high>\d+)\s*万",
        normalized,
    )
    has_income_range = bool(
        range_match
        and (int(range_match.group("low")), int(range_match.group("high"))) == expected_range
    )
    visible_ranges = [
        (int(low), int(high))
        for low, high in re.findall(
            r"(?<!\d)(\d+)\s*[-~—至到]\s*(\d+)\s*万",
            normalized,
        )
    ]
    ranges_are_consistent = bool(visible_ranges) and all(
        item == expected_range for item in visible_ranges
    )
    has_boundary = bool(re.search(r"不等同(?:于)?现实收入|不是现实收入事实", normalized))
    return has_income_range and ranges_are_consistent and has_boundary


def past_event_timing_categories(text: str) -> int:
    categories: set[str] = set()
    for line in str(text or "").splitlines():
        if not _YEAR_PATTERN.search(line):
            continue
        if line.count("｜") < 2 and line.count("|") < 2:
            continue
        if not all(marker in line for marker in ("流年", "大运", "原局")):
            continue
        parts = re.split(r"[｜|]", line, maxsplit=2)
        event_text = parts[1].strip() if len(parts) >= 2 else ""
        if event_text in _GENERIC_EVENT_TEXTS:
            continue
        event_text = normalize_verification_event_text(event_text)
        if any(marker in event_text for marker in _EVENT_CATEGORIES["parent_health"]):
            matched = ["parent_health"]
        else:
            matched = [
                category
                for category, markers in _EVENT_CATEGORIES.items()
                if category != "parent_health"
                and any(marker in event_text for marker in markers)
            ]
        if len(matched) == 1:
            categories.add(matched[0])
    return len(categories)


def _has_generic_verification_event(text: str) -> bool:
    for line in str(text or "").splitlines():
        if not _YEAR_PATTERN.search(line):
            continue
        parts = re.split(r"[｜|]", line, maxsplit=2)
        if len(parts) >= 2:
            event = parts[1].strip()
            if (
                event in _GENERIC_EVENT_TEXTS
                or _VAGUE_EVENT_PATTERN.search(event)
                or not _VERIFIABLE_EVENT_PATTERN.search(event)
            ):
                return True
    return False


def _has_multi_topic_verification_event(text: str) -> bool:
    for line in str(text or "").splitlines():
        if not _YEAR_PATTERN.search(line):
            continue
        parts = re.split(r"[｜|]", line, maxsplit=2)
        if len(parts) < 2:
            continue
        event = parts[1].strip()
        matched_categories = {
            category
            for category, markers in _EVENT_CATEGORIES.items()
            if any(marker in event for marker in markers)
        }
        if "parent_health" in matched_categories:
            matched_categories.discard("self_health")
        if len(matched_categories) > 1:
            return True
    return False


def normalize_verification_event_text(text: str) -> str:
    normalized = str(text or "").strip()
    positions = [
        position
        for marker in _MULTI_EVENT_MARKERS
        if (position := normalized.find(marker)) >= 0
    ]
    if positions:
        normalized = normalized[: min(positions)]
    normalized = normalized.rstrip("，、；;。 ")
    normalized = re.sub(r"(?:但|并|且|和|与|或|及)+$", "", normalized).rstrip("，、；;。 ")
    replacements = {
        "感情": "感情关系出现明显变化",
        "关系": "关系状态出现明显变化",
        "学业": "学业阶段出现明显变化",
        "工作": "工作方向出现明显变化",
        "工作平台": "工作平台发生明显变化",
        "工作环境": "工作环境发生明显变化",
        "职责加重": "工作职责发生明显变化",
        "事业": "事业方向出现明显变化",
        "婚恋": "婚恋关系出现明显变化",
        "恋爱": "恋爱关系出现明显变化",
        "居住环境": "居住环境发生明显变化",
        "家宅事务": "家宅发生明显变化",
        "家中长辈事务": "长辈健康出现需核验事项",
        "长辈": "长辈健康出现需核验事项",
        "父母事务": "父母健康出现需核验事项",
        "父亲": "父亲健康出现需核验事项",
        "母亲": "母亲健康出现需核验事项",
        "父母": "父母健康出现需核验事项",
        "本人健康": "本人健康出现需核验事项",
    }
    return replacements.get(normalized, normalized)


def _concrete_verification_event_text(text: str) -> str:
    normalized = normalize_verification_event_text(text)
    matched_categories = {
        category
        for category, markers in _EVENT_CATEGORIES.items()
        if any(marker in normalized for marker in markers)
    }
    if "parent_health" in matched_categories:
        matched_categories.discard("self_health")
    if len(matched_categories) > 1:
        category_fallbacks = {
            "education_or_work": "岗位调整",
            "relationship": "恋爱关系变化",
            "self_health": "体检",
            "parent_health": "父母健康检查",
        }
        category_positions = {
            category: min(
                normalized.find(marker)
                for marker in _EVENT_CATEGORIES[category]
                if marker in normalized
            )
            for category in matched_categories
        }
        return category_fallbacks[min(category_positions, key=category_positions.get)]
    if _VERIFIABLE_EVENT_PATTERN.search(normalized):
        return normalized
    category_fallbacks = (
        (("学", "考", "专业", "学校"), "升学"),
        (("工作", "事业", "岗位", "职责", "职业", "平台"), "岗位调整"),
        (("感情", "恋爱", "婚", "关系", "对象"), "恋爱关系变化"),
        (("健康", "身体", "医院", "病", "伤", "炎症"), "体检"),
        (("家", "住", "房", "城市", "地点", "环境"), "搬家"),
    )
    for markers, fallback in category_fallbacks:
        if any(marker in normalized for marker in markers):
            return fallback
    return "生活安排调整"


def _has_dangling_verification_event(text: str) -> bool:
    for line in str(text or "").splitlines():
        if not _YEAR_PATTERN.search(line):
            continue
        parts = re.split(r"[｜|]", line, maxsplit=2)
        if len(parts) >= 2 and re.search(r"(?:但|并|且|和|与|或|及)\s*$", parts[1].strip()):
            return True
    return False


def section_text(text: str, section: str) -> str:
    start = _section_position(text, section)
    if start < 0:
        return ""
    following = [
        position
        for title in _SECTION_TITLES
        if title != section
        and (position := _section_position(text[start + 1 :], title)) >= 0
    ]
    end = start + 1 + min(following) if following else len(text)
    return text[start:end]


def bazi_violation_sections(violations: list[str]) -> list[str]:
    mapping = (
        ("婚姻栏", "婚姻"),
        ("健康栏", "健康注意"),
        ("六亲栏", "六亲"),
        ("财富栏", "财富等级"),
        ("过三关", "过三关"),
    )
    selected: list[str] = []
    for violation in violations:
        for prefix, section in mapping:
            if str(violation or "").startswith(prefix) and section not in selected:
                selected.append(section)
                break
    return [section for section in _SECTION_TITLES if section in selected]


def missing_bazi_sections(text: str) -> list[str]:
    return [section for section in _SECTION_TITLES if not _has_bazi_section_content(text, section)]


def _has_bazi_section_heading(text: str, section: str) -> bool:
    return bool(
        re.search(
            rf"(?m)^\s*(?:(?:#{{1,6}}\s*)"
            rf"(?:(?:[一二三四五六七八九十]+|\d+)[、.．]\s*)?|"
            rf"(?:(?:[一二三四五六七八九十]+|\d+)[、.．]\s*))"
            rf"(?:\*{{1,2}})?{re.escape(section)}(?:\*{{1,2}})?(?=\s|[（(:：]|$)",
            str(text or ""),
        )
    )


def _has_bazi_section_content(text: str, section: str) -> bool:
    if not _has_bazi_section_heading(text, section):
        return False
    rendered = section_text(text, section).strip()
    lines = rendered.splitlines()
    if len(lines) < 2:
        return False
    body = re.sub(r"[\s*_`#>\-•]+", "", "\n".join(lines[1:]))
    return len(body) >= 4


def bazi_repair_source_text(text: str, sections: list[str]) -> str:
    selected = [section_text(text, section).strip() for section in sections]
    rendered = "\n\n".join(item for item in selected if item)
    return rendered or str(text or "").strip()


def merge_bazi_repaired_sections(
    original_text: str,
    repaired_text: str,
    sections: list[str],
) -> str:
    merged = str(original_text or "")
    original_missing = set(missing_bazi_sections(merged))
    for section in sections:
        replacement = section_text(repaired_text, section).strip()
        span = _section_span(merged, section)
        if not replacement or span is None:
            continue
        candidate = f"{merged[:span[0]]}{replacement}\n\n{merged[span[1]:].lstrip()}"
        if set(missing_bazi_sections(candidate)) - original_missing:
            continue
        merged = candidate
    return merged.strip()


def _section_span(text: str, section: str) -> tuple[int, int] | None:
    start = _section_position(text, section)
    if start < 0:
        return None
    following = [
        start + 1 + position
        for title in _SECTION_TITLES
        if title != section
        and (position := _section_position(text[start + 1 :], title)) >= 0
    ]
    return start, min(following) if following else len(text)


def _has_invalid_peach_blossom_year(text: str, marriage: str) -> bool:
    natal_branches = _natal_branches(text)
    if len(natal_branches) < 3:
        return any(
            "桃花" in clause and _YEAR_PATTERN.search(clause)
            for clause in re.split(r"[；;。\n]", marriage)
        )
    peach_by_branch = {
        "寅": "卯", "午": "卯", "戌": "卯",
        "申": "酉", "子": "酉", "辰": "酉",
        "巳": "午", "酉": "午", "丑": "午",
        "亥": "子", "卯": "子", "未": "子",
    }
    expected = {peach_by_branch[natal_branches[2]]} if natal_branches[2] in peach_by_branch else set()
    for clause in re.split(r"[；;。\n]", marriage):
        if "桃花" not in clause:
            continue
        for year in _peach_blossom_claimed_years(clause):
            if _gregorian_year_branch(int(year)) not in expected:
                return True
    return False


def _peach_blossom_claimed_years(clause: str) -> list[str]:
    if re.search(r"桃花(?:年|年份|应期)", clause):
        return _YEAR_PATTERN.findall(clause)
    years: list[str] = []
    for segment in re.split(r"[、,，]", clause):
        if "桃花" in segment:
            years.extend(_YEAR_PATTERN.findall(segment))
    return years


def _uses_year_branch_combine_as_marriage_signal(marriage: str) -> bool:
    for clause in re.split(r"[；;。\n]", marriage):
        year_branch_combine = "合年支" in clause or bool(re.search(r"年支.{0,8}(?:相合|被合)", clause))
        marriage_claim = bool(re.search(r"恋爱|婚恋|结婚|夫妻宫|配偶", clause))
        spouse_palace_evidence = "日支" in clause or "夫妻宫" in clause
        if year_branch_combine and marriage_claim and not spouse_palace_evidence:
            return True
    return False


def _has_health_timing(text: str) -> bool:
    return bool(
        _YEAR_PATTERN.search(text)
        and _BODY_PATTERN.search(text)
        and _RELATION_PATTERN.search(text)
        and re.search(r"检查|治疗|住院|开刀|手术|体检", text)
        and re.search(r"住院|开刀|手术", text)
    )


def _has_relative_health_timing(text: str, relative: str) -> bool:
    concrete = any(
        _YEAR_PATTERN.search(line)
        and relative in line
        and _BODY_PATTERN.search(line)
        and _RELATION_PATTERN.search(line)
        for line in text.splitlines()
    )
    bounded = any(
        relative in line
        and re.search(r"未形成|缺少", line)
        and re.search(r"高信号|可靠", line)
        for line in text.splitlines()
    )
    return concrete or bounded


def _natal_branches(text: str) -> list[str]:
    match = re.search(r"地支\s*[：:]\s*(?P<branches>[^\n]+)", section_text(text, "命盘"))
    if match is None:
        return []
    return re.findall(r"[子丑寅卯辰巳午未申酉戌亥]", match.group("branches"))[:4]


def _gregorian_year_branch(year: int) -> str:
    return "子丑寅卯辰巳午未申酉戌亥"[(year - 1984) % 12]


def _section_position(text: str, section: str) -> int:
    match = re.search(
        rf"(?m)^\s*(?:#{{1,6}}\s*)?(?:\*{{1,2}})?"
        rf"(?:(?:[一二三四五六七八九十]+|\d+)[、.．]\s*)?"
        rf"{re.escape(section)}(?:\*{{1,2}})?(?=\s|[（(:：]|$)",
        text,
    )
    return match.start() if match is not None else -1
