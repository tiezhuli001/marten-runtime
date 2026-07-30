from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations


_STEM_ELEMENT = {
    "甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
    "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水",
}
_CONTROLS = {("木", "土"), ("土", "水"), ("水", "火"), ("火", "金"), ("金", "木")}
_GENERATES = {("木", "火"), ("火", "土"), ("土", "金"), ("金", "水"), ("水", "木")}
_STEM_COMBINES = {frozenset(pair) for pair in ("甲己", "乙庚", "丙辛", "丁壬", "戊癸")}
_SIX_COMBINES = {frozenset(pair) for pair in ("子丑", "寅亥", "卯戌", "辰酉", "巳申", "午未")}
_SIX_COMBINE_ELEMENTS = {
    frozenset(pair): element
    for pair, element in (
        ("子丑", "土"), ("寅亥", "木"), ("卯戌", "火"),
        ("辰酉", "金"), ("巳申", "水"), ("午未", "土"),
    )
}
_CLASHES = {frozenset(pair) for pair in ("子午", "丑未", "寅申", "卯酉", "辰戌", "巳亥")}
_HARMS = {frozenset(pair) for pair in ("子未", "丑午", "寅巳", "卯辰", "申亥", "酉戌")}
_BREAKS = {frozenset(pair) for pair in ("子酉", "午卯", "辰丑", "未戌", "寅亥", "巳申")}
_PUNISHMENT_PAIRS = {
    frozenset(pair)
    for pair in ("寅巳", "巳申", "申寅", "丑未", "未戌", "戌丑", "子卯")
}
_SELF_PUNISHMENTS = set("辰午酉亥")
_THREE_HARMONIES = {
    frozenset("申子辰"): "水", frozenset("亥卯未"): "木",
    frozenset("寅午戌"): "火", frozenset("巳酉丑"): "金",
}
_THREE_MEETINGS = {
    frozenset("寅卯辰"): "木", frozenset("巳午未"): "火",
    frozenset("申酉戌"): "金", frozenset("亥子丑"): "水",
}
_THREE_PUNISHMENTS = {
    frozenset("寅巳申"): "无恩之刑",
    frozenset("丑未戌"): "恃势之刑",
}
_BRANCH_HIDDEN_STEMS = {
    "子": ("癸",), "丑": ("己", "癸", "辛"), "寅": ("甲", "丙", "戊"),
    "卯": ("乙",), "辰": ("戊", "乙", "癸"), "巳": ("丙", "戊", "庚"),
    "午": ("丁", "己"), "未": ("己", "丁", "乙"), "申": ("庚", "壬", "戊"),
    "酉": ("辛",), "戌": ("戊", "辛", "丁"), "亥": ("壬", "甲"),
}
_HIDDEN_STEM_LEVELS = ("本气", "中气", "余气")
_BRANCH_ELEMENT = {
    branch: _STEM_ELEMENT[stems[0]] for branch, stems in _BRANCH_HIDDEN_STEMS.items()
}
_ELEMENT_STEMS = {
    element: tuple(stem for stem, value in _STEM_ELEMENT.items() if value == element)
    for element in ("木", "火", "土", "金", "水")
}


@dataclass(frozen=True)
class TimingRelationFacts:
    stem_relations: list[str]
    hidden_stem_relations: list[str]
    branch_relations: list[str]
    multi_relations: list[str]
    repeated_branches: list[str]
    transformation_relations: list[dict[str, object]] = field(default_factory=list)
    impact_relations: list[dict[str, object]] = field(default_factory=list)

    @property
    def all_branch_relations(self) -> list[str]:
        return list(dict.fromkeys([*self.branch_relations, *self.multi_relations]))


def timing_relation_facts(
    moving_pillar: str,
    *,
    moving_label: str,
    natal_pillars: list[str],
    dayun_pillar: str = "",
) -> TimingRelationFacts:
    if len(moving_pillar) < 2:
        return TimingRelationFacts([], [], [], [], [])
    labels = ("年", "月", "日", "时")
    targets = [
        (pillar, f"{label}柱")
        for label, pillar in zip(labels, natal_pillars, strict=False)
        if len(pillar) >= 2
    ]
    if len(dayun_pillar) >= 2 and moving_label != "大运":
        targets.append((dayun_pillar, "大运"))

    moving_stem, moving_branch = moving_pillar[:2]
    stem_relations: list[str] = []
    hidden_stem_relations: list[str] = []
    branch_relations: list[str] = []
    repeated: list[str] = []
    for target, label in targets:
        target_stem, target_branch = target[:2]
        target_prefix = label[0] if label.endswith("柱") else label
        stem_relations.extend(
            _stem_pair(
                moving_stem,
                target_stem,
                f"{moving_label}干",
                f"{target_prefix}干",
            )
        )
        for hidden_index, hidden_stem in enumerate(
            _BRANCH_HIDDEN_STEMS.get(target_branch, ())
        ):
            level = _HIDDEN_STEM_LEVELS[hidden_index]
            hidden_stem_relations.extend(
                _stem_pair(
                    moving_stem,
                    hidden_stem,
                    f"{moving_label}干",
                    f"{target_prefix}支{level}{hidden_stem}",
                )
            )
        for hidden_index, hidden_stem in enumerate(
            _BRANCH_HIDDEN_STEMS.get(moving_branch, ())
        ):
            level = _HIDDEN_STEM_LEVELS[hidden_index]
            hidden_stem_relations.extend(
                _stem_pair(
                    hidden_stem,
                    target_stem,
                    f"{moving_label}支{level}{hidden_stem}",
                    f"{target_prefix}干",
                )
            )
        pair_relations, is_repeated = _branch_pair(
            moving_branch, target_branch, moving_label, f"{target_prefix}支"
        )
        branch_relations.extend(pair_relations)
        if is_repeated:
            repeated.append(f"{moving_branch}伏吟{target_prefix}支")

    participants = [
        (pillar[1], f"{label}支")
        for label, pillar in zip(labels, natal_pillars, strict=False)
        if len(pillar) >= 2
    ]
    if len(dayun_pillar) >= 2 and moving_label != "大运":
        participants.append((dayun_pillar[1], "大运支"))
    participants.append((moving_branch, f"{moving_label}支"))
    multi = _multi_relations(participants, required_label=f"{moving_label}支")
    active_stems = _active_stems(
        natal_pillars,
        dayun_pillar=dayun_pillar if moving_label != "大运" else "",
        moving_pillar=moving_pillar,
        moving_label=moving_label,
    )
    day_master = natal_pillars[2][0] if len(natal_pillars) >= 3 and natal_pillars[2] else ""
    transformation_relations = _transformation_facts(
        participants,
        active_stems=active_stems,
        day_master=day_master,
        required_label=f"{moving_label}支",
    )
    impact_relations = _impact_facts(
        participants,
        day_master=day_master,
        required_label=f"{moving_label}支",
    )
    return TimingRelationFacts(
        list(dict.fromkeys(stem_relations)),
        list(dict.fromkeys(hidden_stem_relations)),
        list(dict.fromkeys(branch_relations)),
        list(dict.fromkeys(multi)),
        list(dict.fromkeys(repeated)),
        transformation_relations,
        impact_relations,
    )


def natal_branch_dynamics(natal_pillars: list[str]) -> dict[str, list[dict[str, object]]]:
    labels = ("年", "月", "日", "时")
    participants = [
        (pillar[1], f"{label}支")
        for label, pillar in zip(labels, natal_pillars, strict=False)
        if len(pillar) >= 2
    ]
    day_master = natal_pillars[2][0] if len(natal_pillars) >= 3 and natal_pillars[2] else ""
    return {
        "合化判定": _transformation_facts(
            participants,
            active_stems=_active_stems(natal_pillars),
            day_master=day_master,
        ),
        "受影响属性": _impact_facts(participants, day_master=day_master),
    }


def _stem_pair(left: str, right: str, left_label: str, right_label: str) -> list[str]:
    if left == right:
        return [f"{left}伏吟{right_label}"]
    if frozenset((left, right)) in _STEM_COMBINES:
        return [f"{left}{right}合（{left_label}合{right_label}）"]
    left_element, right_element = _STEM_ELEMENT.get(left), _STEM_ELEMENT.get(right)
    if (left_element, right_element) in _CONTROLS:
        return [f"{left}克{right}（{left_label}克{right_label}）"]
    if (right_element, left_element) in _CONTROLS:
        return [f"{right}克{left}（{right_label}克{left_label}）"]
    if (left_element, right_element) in _GENERATES:
        return [f"{left}生{right}（{left_label}生{right_label}）"]
    if (right_element, left_element) in _GENERATES:
        return [f"{right}生{left}（{right_label}生{left_label}）"]
    return []


def _branch_pair(
    left: str, right: str, left_label: str, right_label: str
) -> tuple[list[str], bool]:
    if left == right:
        relations: list[str] = []
        if left in _SELF_PUNISHMENTS:
            relations.append(f"{left}{right}自刑（{left_label}支与{right_label}）")
        return relations, True
    pair = frozenset((left, right))
    labels = f"{left_label}支与{right_label}"
    relations: list[str] = []
    for relation_set, name in (
        (_SIX_COMBINES, "六合"), (_CLASHES, "相冲"), (_PUNISHMENT_PAIRS, "相刑"),
        (_HARMS, "相害"), (_BREAKS, "相破"),
    ):
        if pair in relation_set:
            relations.append(f"{left}{right}{name}（{labels}）")
    return relations, False


def _multi_relations(
    participants: list[tuple[str, str]], *, required_label: str
) -> list[str]:
    result: list[str] = []
    for indexes in combinations(range(len(participants)), 3):
        selected = [participants[index] for index in indexes]
        if required_label not in {label for _, label in selected}:
            continue
        branches = frozenset(branch for branch, _ in selected)
        labels = "/".join(label for _, label in selected)
        if branches in _THREE_HARMONIES:
            result.append(f"{''.join(branch for branch, _ in selected)}三合{_THREE_HARMONIES[branches]}局（{labels}）")
        if branches in _THREE_MEETINGS:
            result.append(f"{''.join(branch for branch, _ in selected)}三会{_THREE_MEETINGS[branches]}局（{labels}）")
        if branches in _THREE_PUNISHMENTS:
            result.append(f"{''.join(branch for branch, _ in selected)}三刑·{_THREE_PUNISHMENTS[branches]}（{labels}）")
    return result


def _active_stems(
    natal_pillars: list[str],
    *,
    dayun_pillar: str = "",
    moving_pillar: str = "",
    moving_label: str = "",
) -> list[tuple[str, str]]:
    labels = ("年干", "月干", "日干", "时干")
    stems = [
        (pillar[0], label)
        for pillar, label in zip(natal_pillars, labels, strict=False)
        if pillar and pillar[0] in _STEM_ELEMENT
    ]
    if dayun_pillar and dayun_pillar[0] in _STEM_ELEMENT:
        stems.append((dayun_pillar[0], "大运干"))
    if moving_pillar and moving_pillar[0] in _STEM_ELEMENT:
        stems.append((moving_pillar[0], f"{moving_label}干"))
    return list(dict.fromkeys(stems))


def _transformation_facts(
    participants: list[tuple[str, str]],
    *,
    active_stems: list[tuple[str, str]],
    day_master: str,
    required_label: str = "",
) -> list[dict[str, object]]:
    facts: list[dict[str, object]] = []
    for left_index, right_index in combinations(range(len(participants)), 2):
        selected = [participants[left_index], participants[right_index]]
        if required_label and required_label not in {label for _, label in selected}:
            continue
        pair = frozenset(branch for branch, _ in selected)
        target_element = _SIX_COMBINE_ELEMENTS.get(pair)
        if target_element:
            facts.append(
                _transformation_fact(
                    relation="六合",
                    selected=selected,
                    target_element=target_element,
                    active_stems=active_stems,
                    day_master=day_master,
                )
            )
    for indexes in combinations(range(len(participants)), 3):
        selected = [participants[index] for index in indexes]
        if required_label and required_label not in {label for _, label in selected}:
            continue
        branches = frozenset(branch for branch, _ in selected)
        if branches in _THREE_HARMONIES:
            facts.append(
                _transformation_fact(
                    relation="三合",
                    selected=selected,
                    target_element=_THREE_HARMONIES[branches],
                    active_stems=active_stems,
                    day_master=day_master,
                )
            )
        if branches in _THREE_MEETINGS:
            facts.append(
                _transformation_fact(
                    relation="三会",
                    selected=selected,
                    target_element=_THREE_MEETINGS[branches],
                    active_stems=active_stems,
                    day_master=day_master,
                )
            )
    return _dedupe_dicts(facts)


def _transformation_fact(
    *,
    relation: str,
    selected: list[tuple[str, str]],
    target_element: str,
    active_stems: list[tuple[str, str]],
    day_master: str,
) -> dict[str, object]:
    triggers = [
        f"{label}{stem}"
        for stem, label in active_stems
        if stem in _ELEMENT_STEMS[target_element]
    ]
    status = "合化成立" if triggers else "合化未成"
    participants = [_branch_attribute(branch, label, day_master) for branch, label in selected]
    return {
        "关系": f"{''.join(branch for branch, _ in selected)}{relation}{target_element}局",
        "化神": target_element,
        "状态": status,
        "引化天干": triggers,
        "依据": (
            f"天干透出{'、'.join(triggers)}作为{target_element}化神引化"
            if triggers
            else f"天干未透{''.join(_ELEMENT_STEMS[target_element])}，只论合绊或待化"
        ),
        "参与支": participants,
        "作用结果": (
            f"参与支原属性转入{target_element}气"
            if triggers
            else "参与支彼此合绊，原属性未转化"
        ),
    }


def _impact_facts(
    participants: list[tuple[str, str]],
    *,
    day_master: str,
    required_label: str = "",
) -> list[dict[str, object]]:
    facts: list[dict[str, object]] = []
    for left_index, right_index in combinations(range(len(participants)), 2):
        selected = [participants[left_index], participants[right_index]]
        if required_label and required_label not in {label for _, label in selected}:
            continue
        left, right = selected[0][0], selected[1][0]
        pair = frozenset((left, right))
        relations = [
            name
            for relation_set, name in (
                (_CLASHES, "相冲"),
                (_PUNISHMENT_PAIRS, "相刑"),
                (_HARMS, "相害"),
                (_BREAKS, "相破"),
            )
            if pair in relation_set
        ]
        if left == right and left in _SELF_PUNISHMENTS:
            relations.append("自刑")
        for relation in relations:
            attributes = [
                _branch_attribute(branch, label, day_master) for branch, label in selected
            ]
            affected = _affected_sides(attributes, relation)
            facts.append(
                {
                    "关系": f"{left}{right}{relation}",
                    "参与支": attributes,
                    "受影响一方": affected,
                    "作用结果": _impact_result(attributes, affected, relation),
                }
            )
    return _dedupe_dicts(facts)


def _branch_attribute(branch: str, label: str, day_master: str) -> dict[str, str]:
    main_stem = _BRANCH_HIDDEN_STEMS.get(branch, ("",))[0]
    return {
        "地支": branch,
        "宫位": label,
        "本气": main_stem,
        "五行": _BRANCH_ELEMENT.get(branch, ""),
        "十神": _ten_god(day_master, main_stem),
    }


def _affected_sides(attributes: list[dict[str, str]], relation: str) -> list[dict[str, str]]:
    if len(attributes) != 2 or relation != "相冲":
        return attributes
    left_element, right_element = attributes[0]["五行"], attributes[1]["五行"]
    if (left_element, right_element) in _CONTROLS:
        return [attributes[1]]
    if (right_element, left_element) in _CONTROLS:
        return [attributes[0]]
    return attributes


def _impact_result(
    attributes: list[dict[str, str]],
    affected: list[dict[str, str]],
    relation: str,
) -> str:
    labels = "、".join(
        f"{item['宫位']}{item['地支']}({item['五行']}/{item['十神'] or '未定'})"
        for item in affected
    )
    if relation == "相冲" and len(affected) == 1:
        return f"五行相克，{labels}为明确受克侧"
    return f"{labels}双方受{relation}作用，强弱程度仍须结合月令与通根"


def _ten_god(day_master: str, target_stem: str) -> str:
    day_element = _STEM_ELEMENT.get(day_master)
    target_element = _STEM_ELEMENT.get(target_stem)
    if not day_element or not target_element:
        return ""
    yang_stems = "甲丙戊庚壬"
    same_polarity = (day_master in yang_stems) == (target_stem in yang_stems)
    if day_element == target_element:
        return "比肩" if same_polarity else "劫财"
    if (day_element, target_element) in _GENERATES:
        return "食神" if same_polarity else "伤官"
    if (day_element, target_element) in _CONTROLS:
        return "偏财" if same_polarity else "正财"
    if (target_element, day_element) in _CONTROLS:
        return "七杀" if same_polarity else "正官"
    return "偏印" if same_polarity else "正印"


def _dedupe_dicts(items: list[dict[str, object]]) -> list[dict[str, object]]:
    deduped: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in items:
        key = repr(item)
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped
