from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone


_STEM_INFO = {
    "甲": ("木", "yang"), "乙": ("木", "yin"),
    "丙": ("火", "yang"), "丁": ("火", "yin"),
    "戊": ("土", "yang"), "己": ("土", "yin"),
    "庚": ("金", "yang"), "辛": ("金", "yin"),
    "壬": ("水", "yang"), "癸": ("水", "yin"),
}
_BRANCH_HIDDEN = {
    "子": [("癸", 1.0)], "丑": [("己", 1.0), ("癸", 0.6), ("辛", 0.3)],
    "寅": [("甲", 1.0), ("丙", 0.6), ("戊", 0.3)],
    "卯": [("乙", 1.0)], "辰": [("戊", 1.0), ("乙", 0.6), ("癸", 0.3)],
    "巳": [("丙", 1.0), ("戊", 0.6), ("庚", 0.3)],
    "午": [("丁", 1.0), ("己", 0.6)],
    "未": [("己", 1.0), ("丁", 0.6), ("乙", 0.3)],
    "申": [("庚", 1.0), ("壬", 0.6), ("戊", 0.3)],
    "酉": [("辛", 1.0)], "戌": [("戊", 1.0), ("辛", 0.6), ("丁", 0.3)],
    "亥": [("壬", 1.0), ("甲", 0.6)],
}
_GENERATES = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
_CONTROLS = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}
_SIX_COMBINES = {frozenset(pair) for pair in ("子丑", "寅亥", "卯戌", "辰酉", "巳申", "午未")}
_CLASHES = {frozenset(pair) for pair in ("子午", "丑未", "寅申", "卯酉", "辰戌", "巳亥")}
_ELEMENTS = ("木", "火", "土", "金", "水")
_TEN_GODS = ("比肩", "劫财", "食神", "伤官", "偏财", "正财", "七杀", "正官", "偏印", "正印")


def extract_chart_features(payload: dict[str, object], *, reference_year: int | None = None) -> dict[str, object]:
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    if not isinstance(result, dict):
        return {}
    entries, pillars = _pillars(result)
    if len(pillars) != 4 or any(len(item) < 2 for item in pillars):
        return {}
    day_master = _basic_day_master(result) or pillars[2][0]
    features: dict[str, object] = {
        "feature_version": "bazi.case.features.v2",
        "year_pillar": pillars[0],
        "month_pillar": pillars[1],
        "day_pillar": pillars[2],
        "hour_pillar": pillars[3],
        "pillars": pillars,
        "chart_signature": hashlib.sha256("|".join(pillars).encode("utf-8")).hexdigest(),
        "day_master": day_master,
        "month_order": pillars[1][1],
    }
    gender = _basic_gender(result) or payload.get("gender")
    if gender:
        features["gender"] = str(gender)
    stems = [(pillar[0], 1.0) for pillar in pillars]
    hidden: list[tuple[str, float]] = []
    for index, pillar in enumerate(pillars):
        entry = entries[index] if index < len(entries) else {}
        parsed = _entry_hidden(entry)
        hidden.extend(parsed or _BRANCH_HIDDEN.get(pillar[1], []))
    features["element_profile"] = _normalized_profile(
        ((stem, weight) for stem, weight in [*stems, *hidden]),
        categories=_ELEMENTS,
        mapper=lambda stem: _STEM_INFO.get(stem, ("", ""))[0],
    )
    features["ten_god_profile"] = _normalized_profile(
        ((stem, weight) for stem, weight in [*stems[:2], *stems[3:], *hidden]),
        categories=_TEN_GODS,
        mapper=lambda stem: _ten_god(day_master, stem),
    )
    relations = set(str(item) for item in result.get("干支关系", []) if str(item).strip())
    relations.update(_derived_branch_relations(pillars))
    features["relations"] = sorted(relations)
    dayun = _dayun_entries(payload, result)
    if dayun:
        features["dayun_periods"] = dayun
        active = _active_dayun(dayun, reference_year or datetime.now(timezone.utc).year)
        if active:
            features["active_dayun"] = active
    return features


def cosine_profile(left: object, right: object) -> float | None:
    if not isinstance(left, dict) or not isinstance(right, dict) or not left or not right:
        return None
    keys = sorted(set(left) | set(right))
    a = [float(left.get(key) or 0.0) for key in keys]
    b = [float(right.get(key) or 0.0) for key in keys]
    denominator = math.sqrt(sum(value * value for value in a)) * math.sqrt(sum(value * value for value in b))
    return sum(x * y for x, y in zip(a, b)) / denominator if denominator else None


def jaccard(left: object, right: object) -> float | None:
    a = {str(item) for item in left} if isinstance(left, list) else set()
    b = {str(item) for item in right} if isinstance(right, list) else set()
    if not a and not b:
        return None
    return len(a & b) / len(a | b)


def element_of_ganzhi(value: str) -> tuple[str, str]:
    if len(value) < 2:
        return "", ""
    stem_element = _STEM_INFO.get(value[0], ("", ""))[0]
    hidden = _BRANCH_HIDDEN.get(value[1], [])
    branch_element = _STEM_INFO.get(hidden[0][0], ("", ""))[0] if hidden else ""
    return stem_element, branch_element


def _pillars(result: dict[str, object]) -> tuple[list[dict[str, object]], list[str]]:
    raw = result.get("四柱") or result.get("原始四柱") or result.get("pillars")
    if isinstance(raw, dict):
        return [], [str(raw.get(key) or "").strip() for key in ("年柱", "月柱", "日柱", "时柱")]
    if isinstance(raw, (list, tuple)):
        entries = [dict(item) for item in raw if isinstance(item, dict)]
        if len(entries) == 4:
            return entries, [str(item.get("干支") or "").strip() for item in entries]
        return [], [str(item).strip() for item in raw]
    return [], [str(result.get(key) or "").strip() for key in ("年柱", "月柱", "日柱", "时柱")]


def _basic_day_master(result: dict[str, object]) -> str:
    basic = result.get("基本信息")
    return str(basic.get("日主") or "") if isinstance(basic, dict) else ""


def _basic_gender(result: dict[str, object]) -> str:
    basic = result.get("基本信息")
    if isinstance(basic, dict):
        return str(basic.get("性别") or "")
    return str(result.get("性别") or result.get("gender") or "")


def _entry_hidden(entry: dict[str, object]) -> list[tuple[str, float]]:
    weights = {"本气": 1.0, "中气": 0.6, "余气": 0.3}
    raw = entry.get("藏干")
    if not isinstance(raw, list):
        return []
    return [
        (str(item.get("天干") or ""), weights.get(str(item.get("气性") or ""), 0.5))
        for item in raw if isinstance(item, dict) and item.get("天干")
    ]


def _normalized_profile(items, *, categories: tuple[str, ...], mapper) -> dict[str, float]:  # noqa: ANN001, ANN202
    counts = {key: 0.0 for key in categories}
    for item, weight in items:
        category = mapper(str(item))
        if category in counts:
            counts[category] += float(weight)
    total = sum(counts.values())
    return {key: round(value / total, 6) for key, value in counts.items()} if total else {}


def _ten_god(day_master: str, other: str) -> str:
    day = _STEM_INFO.get(day_master)
    target = _STEM_INFO.get(other)
    if day is None or target is None:
        return ""
    day_element, day_polarity = day
    target_element, target_polarity = target
    same = day_polarity == target_polarity
    if target_element == day_element:
        return "比肩" if same else "劫财"
    if _GENERATES[day_element] == target_element:
        return "食神" if same else "伤官"
    if _CONTROLS[day_element] == target_element:
        return "偏财" if same else "正财"
    if _CONTROLS[target_element] == day_element:
        return "七杀" if same else "正官"
    return "偏印" if same else "正印"


def _derived_branch_relations(pillars: list[str]) -> set[str]:
    branches = [item[1] for item in pillars]
    stems = [item[0] for item in pillars]
    result: set[str] = set()
    for left in range(len(branches)):
        for right in range(left + 1, len(branches)):
            result.add(f"干对:{left}-{right}:{stems[left]}{stems[right]}")
            result.add(f"支对:{left}-{right}:{branches[left]}{branches[right]}")
            pair = frozenset((branches[left], branches[right]))
            if pair in _SIX_COMBINES:
                result.add(f"六合:{''.join(sorted(pair))}")
            if pair in _CLASHES:
                result.add(f"相冲:{''.join(sorted(pair))}")
            if branches[left] == branches[right]:
                result.add(f"同支:{branches[left]}")
    return result


def _dayun_entries(payload: dict[str, object], result: dict[str, object]) -> list[dict[str, object]]:
    related = payload.get("relatedResults")
    dayun_result = related.get("dayun") if isinstance(related, dict) else None
    raw = dayun_result.get("大运列表") if isinstance(dayun_result, dict) else result.get("大运列表")
    if not isinstance(raw, list):
        return []
    periods: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        ganzhi = str(item.get("干支") or "")
        if not ganzhi:
            continue
        stem_element, branch_element = element_of_ganzhi(ganzhi)
        periods.append(
            {
                "ganzhi": ganzhi,
                "start_year": int(item.get("起运年份") or 0),
                "start_age": int(item.get("起运年龄") or 0),
                "ten_god": str(item.get("十神") or ""),
                "stem_element": stem_element,
                "branch_element": branch_element,
            }
        )
    return periods


def _active_dayun(periods: list[dict[str, object]], year: int) -> dict[str, object]:
    eligible = [
        item for item in periods
        if 0 < int(item.get("start_year") or 0) <= year
    ]
    return dict(max(eligible, key=lambda item: int(item.get("start_year") or 0))) if eligible else {}
