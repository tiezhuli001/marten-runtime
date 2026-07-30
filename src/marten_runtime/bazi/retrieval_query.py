from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping
from zoneinfo import ZoneInfo

from marten_runtime.tools.builtins.bazi_tool import (
    CURRENT_RESULT_STATE_KEY,
    RESULTS_BY_ACTION_STATE_KEY,
)


_STEM_ELEMENTS = {
    "甲": "木", "乙": "木", "丙": "火", "丁": "火", "戊": "土",
    "己": "土", "庚": "金", "辛": "金", "壬": "水", "癸": "水",
}
_TOPIC_MARKERS = {
    "过三关": ("过三关", "三关", "断事", "应验", "核验"),
    "婚姻": ("婚姻", "婚恋", "结婚", "恋爱", "配偶"),
    "事业": ("事业", "工作", "职业", "升职", "创业"),
    "财富": ("财富", "财运", "收入", "赚钱", "资产"),
    "健康": ("健康", "疾病", "手术", "住院", "伤灾"),
    "学历": ("学历", "学业", "考试", "升学"),
    "六亲": ("父亲", "母亲", "父母", "子女", "六亲"),
}


@dataclass(frozen=True)
class BaziRetrievalPlan:
    theory_query: str
    theory_queries: tuple[str, ...]
    classical_query: str
    author_method_query: str
    case_query: str
    facts: tuple[str, ...]
    domain_terms: tuple[tuple[str, float], ...]
    month_ten_god: str = ""
    evidence_topics: tuple[str, ...] = ()


def current_bazi_result_from_context(tool_context: Mapping[str, object] | None) -> dict[str, object]:
    state = (tool_context or {}).get("turn_tool_state")
    if not isinstance(state, dict):
        return {}
    current = state.get(CURRENT_RESULT_STATE_KEY)
    by_action = state.get(RESULTS_BY_ACTION_STATE_KEY)
    candidates: list[dict[str, object]] = []
    if isinstance(by_action, dict):
        for action in ("chart", "resolve_pillars", "dayun"):
            item = by_action.get(action)
            if isinstance(item, dict) and item.get("ok") is True:
                candidates.append(item)
    if isinstance(current, dict) and current.get("ok") is True:
        candidates.append(current)
    selected = next((item for item in candidates if _pillars(item)), None)
    if selected is None:
        return {}
    result = deepcopy(selected)
    if isinstance(by_action, dict):
        related = {
            action: deepcopy(item.get("result"))
            for action, item in by_action.items()
            if isinstance(item, dict) and item.get("ok") is True and item is not selected
        }
        if related:
            result["relatedResults"] = related
    return result


def build_bazi_retrieval_plan(
    bazi_result: Mapping[str, object], *, user_message: str = ""
) -> BaziRetrievalPlan | None:
    payload = bazi_result.get("result")
    if not isinstance(payload, dict):
        return None
    rows = payload.get("四柱")
    if not isinstance(rows, list) or len(rows) != 4 or not all(isinstance(row, dict) for row in rows):
        return None
    pillars = [str(row.get("干支") or "").strip() for row in rows]
    if any(len(pillar) < 2 for pillar in pillars):
        return None

    day_master = pillars[2][0]
    day_element = _STEM_ELEMENTS.get(day_master, "")
    month_order = pillars[1][1]
    month_ten_god = _month_main_ten_god(rows[1])
    visible_ten_gods = _visible_ten_gods(rows)
    relations = _relation_terms(payload.get("干支关系"))
    structures = _structure_candidates(month_ten_god, visible_ten_gods)
    hypotheses = _retrieval_hypotheses(month_ten_god, structures)
    topics = _requested_topics(user_message)
    methods = _requested_methods(user_message)
    evidence_topics = _evidence_topics(user_message)
    active_dayun = _active_dayun(bazi_result)

    day_month = f"{day_master}{day_element}生{month_order}月" if day_element else f"{day_master}日{month_order}月"
    facts = _unique(
        [
            day_month,
            f"{month_order}月月令{month_ten_god}" if month_ten_god else "",
            *[f"{stem}{ten_god}" for stem, ten_god in visible_ten_gods],
            *relations,
            *structures,
            f"{month_ten_god}格候选" if month_ten_god else "",
            *[f"{item}候选" for item in hypotheses],
            *methods,
            *topics,
        ]
    )
    core_relations = relations[:3]
    core_theory_terms = _unique(
        [
            day_month,
            f"{month_ten_god}格" if month_ten_god else "",
            *hypotheses,
            *core_relations,
            *methods,
            *topics,
        ]
    )
    theory_query = " ".join(
        _unique(
            [
                *core_theory_terms,
                *_evidence_query_terms(evidence_topics),
            ]
        )
    )
    theory_queries = [" ".join(core_theory_terms)]
    for evidence_topic_group in _evidence_topic_groups(evidence_topics):
        theory_queries.append(
            " ".join(
                _unique(
                    [
                        day_month,
                        f"{month_ten_god}格" if month_ten_god else "",
                        *hypotheses,
                        *methods,
                        *_evidence_query_terms(evidence_topic_group),
                    ]
                )
            )
        )
    case_query = " ".join(
        _unique(
            [
                "男命" if _gender(payload) == "男" else "女命" if _gender(payload) == "女" else "",
                day_month,
                f"{month_ten_god}格" if month_ten_god else "",
                *hypotheses,
                *core_relations,
                f"当前{active_dayun}大运" if active_dayun else "",
                *topics,
            ]
        )
    )
    domain_terms: list[tuple[str, float]] = [(day_month, 4.0), (f"{month_order}月", 5.0)]
    if month_ten_god:
        domain_terms.extend([(month_ten_god, 5.0), (_ten_god_family(month_ten_god), 5.0)])
    domain_terms.extend((term, 2.5) for term in relations)
    domain_terms.extend((term, 2.0) for term in structures)
    domain_terms.extend((term, 1.0) for term in topics)
    domain_terms.extend((term, 0.8) for term in _evidence_query_terms(evidence_topics))
    return BaziRetrievalPlan(
        theory_query=theory_query,
        theory_queries=tuple(_unique(theory_queries)),
        classical_query="月令",
        author_method_query=_author_method_query(evidence_topics),
        case_query=case_query,
        facts=tuple(facts),
        domain_terms=tuple((term, weight) for term, weight in domain_terms if term),
        month_ten_god=month_ten_god,
        evidence_topics=tuple(evidence_topics),
    )


def rerank_bazi_theory_results(
    results: list[dict[str, object]], *, plan: BaziRetrievalPlan, top_k: int
) -> list[dict[str, object]]:
    if not results:
        return []
    base_scores = [float(item.get("score") or 0.0) for item in results]
    low, high = min(base_scores), max(base_scores)
    denominator = sum(weight for _, weight in plan.domain_terms) or 1.0
    ranked: list[tuple[float, dict[str, object]]] = []
    for item, base in zip(results, base_scores, strict=True):
        text = " ".join(
            (
                str(item.get("source_title") or ""),
                str(item.get("heading") or ""),
                str(item.get("text") or ""),
            )
        )
        matched = sum(weight for term, weight in plan.domain_terms if term in text)
        domain_score = min(1.0, matched / denominator)
        if plan.month_ten_god and plan.month_ten_god in text and any(
            marker in text for marker in ("月令", "秉令", "当令", "司令")
        ):
            domain_score = min(1.0, domain_score + 0.30)
        base_score = (base - low) / (high - low) if high > low else 1.0
        evidence_score = {
            "classical_original": 1.0,
            "historical_commentary": 0.8,
            "modern_commentary": 0.6,
            "marten_interpretation": 0.5,
        }.get(str(dict(item.get("metadata") or {}).get("evidence_kind") or ""), 0.3)
        score = 0.35 * base_score + 0.55 * domain_score + 0.10 * evidence_score
        updated = dict(item)
        score_parts = dict(updated.get("score_parts") or {})
        score_parts["base_normalized"] = round(base_score, 6)
        score_parts["bazi_domain"] = round(domain_score, 6)
        updated["score_parts"] = score_parts
        updated["score"] = round(score, 6)
        ranked.append((score, updated))
    ranked.sort(key=lambda pair: (pair[0], str(pair[1].get("chunk_id") or "")), reverse=True)
    deduplicated: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for _, item in ranked:
        key = (
            str(item.get("source_id") or ""),
            " ".join(str(item.get("heading") or "").split()),
        )
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(item)
    return _diverse_theory_evidence(deduplicated, plan=plan, top_k=top_k)


def _diverse_theory_evidence(
    items: list[dict[str, object]], *, plan: BaziRetrievalPlan, top_k: int
) -> list[dict[str, object]]:
    if not plan.evidence_topics or top_k < 3:
        return items[:top_k]
    chapter_types = {"author_chapter"}
    classical_types = {"classical_original", "historical_commentary"}
    author_methods: list[dict[str, object]] = []
    author_sources: set[str] = set()
    author_method_limit = 2 if top_k >= 5 else 1
    for item in items:
        metadata = dict(item.get("metadata") or {})
        if (
            str(metadata.get("content_type") or "") != "author_method"
            or not _matches_author_method_topic(item, plan.author_method_query)
        ):
            continue
        source = str(metadata.get("source_title") or item.get("source_id") or "")
        if source in author_sources:
            continue
        author_sources.add(source)
        author_methods.append(item)
        if len(author_methods) >= author_method_limit:
            break
    timing_method = next(
        (
            item
            for item in items
            if str(dict(item.get("metadata") or {}).get("content_type") or "")
            == "timing_method"
        ),
        None,
    )
    methods = author_methods or ([timing_method] if timing_method is not None else [])
    chapters: list[dict[str, object]] = []
    chapter_groups: set[str] = set()
    chapter_limit = 3 if top_k >= 8 else 1
    for item in items:
        if str(dict(item.get("metadata") or {}).get("content_type") or "") not in chapter_types:
            continue
        group = _chapter_evidence_group(item)
        if group in chapter_groups:
            continue
        chapter_groups.add(group)
        chapters.append(item)
        if len(chapters) >= chapter_limit:
            break
    classical = next(
        (
            item
            for item in items
            if str(dict(item.get("metadata") or {}).get("evidence_kind") or "")
            in classical_types
        ),
        None,
    )
    reserved = [item for item in (classical, *methods, *chapters) if item is not None]
    reserved_ids = {str(item.get("chunk_id") or "") for item in reserved}
    core = [item for item in items if str(item.get("chunk_id") or "") not in reserved_ids]
    leading = [classical] if classical is not None else []
    supporting = [item for item in (*methods, *chapters) if item is not None]
    return [*leading, *core[: max(0, top_k - len(reserved))], *supporting][:top_k]


def _matches_author_method_topic(item: Mapping[str, object], query: str) -> bool:
    text = " ".join((str(item.get("heading") or ""), str(item.get("text") or "")))
    topic_terms: tuple[str, ...] = ()
    if "过三关" in query or "具体应验" in query:
        topic_terms = ("具体应验", "应验的时间", "断事", "大事情", "综合细致")
    elif "健康取象" in query or "疾病应期" in query:
        topic_terms = ("健康", "疾病", "身体", "五脏", "六腑", "伤病")
    elif "婚姻" in query or "配偶星" in query:
        topic_terms = ("婚姻", "婚恋", "配偶", "夫妻宫", "结婚", "离婚")
    elif "六亲" in query or "父母星宫" in query:
        topic_terms = ("六亲", "父亲", "母亲", "父母")
    elif "事业" in query:
        topic_terms = ("事业", "工作", "职业")
    elif "财富" in query:
        topic_terms = ("财富", "财运", "收入")
    return not topic_terms or any(term in text for term in topic_terms)


def _chapter_evidence_group(item: Mapping[str, object]) -> str:
    text = " ".join((str(item.get("heading") or ""), str(item.get("text") or "")))
    groups = (
        ("timing", ("过三关", "应期", "流年", "神煞", "断事")),
        ("relationship", ("婚姻", "配偶", "夫妻宫", "六亲", "父母", "子女")),
        ("livelihood", ("事业", "职业", "财富", "财运", "学历", "学业")),
        ("health", ("健康", "疾病", "五脏", "六腑", "伤病")),
    )
    return next(
        (name for name, markers in groups if any(marker in text for marker in markers)),
        "general",
    )


def _pillars(result: Mapping[str, object]) -> list[str]:
    payload = result.get("result")
    if not isinstance(payload, dict):
        return []
    rows = payload.get("四柱") or payload.get("原始四柱")
    if isinstance(rows, dict):
        return [str(rows.get(key) or "") for key in ("年柱", "月柱", "日柱", "时柱")]
    if isinstance(rows, list):
        return [
            str(row.get("干支") or "") if isinstance(row, dict) else str(row)
            for row in rows
        ]
    return []


def _month_main_ten_god(row: Mapping[str, object]) -> str:
    hidden = row.get("藏干")
    if not isinstance(hidden, list):
        return ""
    for item in hidden:
        if isinstance(item, dict) and str(item.get("十神") or "").strip():
            return str(item["十神"]).strip()
    return ""


def _visible_ten_gods(rows: list[dict[str, object]]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for index, row in enumerate(rows):
        if index == 2:
            continue
        pillar = str(row.get("干支") or "")
        ten_god = str(row.get("天干十神") or "").strip()
        if pillar and ten_god and ten_god != "-":
            result.append((pillar[0], ten_god))
    return result


def _relation_terms(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    terms: list[str] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        text = str(item).strip()
        if not text:
            continue
        normalized = text.replace("化火", "").replace("化木", "").replace("化金", "").replace("化水", "").replace("化土", "")
        branches = "".join(sorted({char for char in normalized[:4] if char in "子丑寅卯辰巳午未申酉戌亥"}))
        marker = next(
            (name for name in ("三合", "三会", "六合", "相冲", "冲", "相刑", "刑", "相害", "害", "相破", "破") if name in normalized),
            normalized,
        )
        key = branches, marker
        if key in seen:
            continue
        seen.add(key)
        terms.append(normalized)
    return _unique(terms)[:6]


def _structure_candidates(month_ten_god: str, visible: list[tuple[str, str]]) -> list[str]:
    gods = {ten_god for _, ten_god in visible}
    if month_ten_god:
        gods.add(month_ten_god)
    terms: list[str] = []
    if gods & {"偏财", "正财"} and gods & {"正官", "七杀"}:
        terms.append("财官同见")
    if gods & {"比肩", "劫财"} and gods & {"偏财", "正财"}:
        terms.append("比劫财星同见")
    if gods & {"正官", "七杀"} and gods & {"偏印", "正印"}:
        terms.append("官印同见")
    if gods & {"食神", "伤官"} and gods & {"偏财", "正财"}:
        terms.append("食伤财星同见")
    if "食神" in gods and "七杀" in gods:
        terms.append("食神七杀同见")
    return terms


def _retrieval_hypotheses(month_ten_god: str, structures: list[str]) -> list[str]:
    hypotheses: list[str] = []
    if "财官同见" in structures:
        hypotheses.extend(["财生官", "身财官强弱"])
    if "比劫财星同见" in structures:
        hypotheses.append("比劫财星")
    if "官印同见" in structures:
        hypotheses.append("官印相生")
    if "食伤财星同见" in structures:
        hypotheses.append("食伤生财")
    if "食神七杀同见" in structures:
        hypotheses.append("食神制杀")
    if month_ten_god in {"比肩", "劫财"}:
        hypotheses.append("建禄月劫")
    return _unique(hypotheses)


def _requested_topics(message: str) -> list[str]:
    return [topic for topic, markers in _TOPIC_MARKERS.items() if any(marker in message for marker in markers)]


def _requested_methods(message: str) -> list[str]:
    methods: list[str] = []
    if "子平" in message or "格局" in message:
        methods.append("子平格局")
    if "盲派" in message or "做功" in message:
        methods.append("盲派做功")
    return methods or ["子平格局", "盲派做功"]


def _evidence_topics(message: str) -> list[str]:
    requested = _requested_topics(message)
    if requested:
        return requested
    if any(marker in message for marker in ("分析", "解盘", "子平", "盲派", "过三关")):
        return [
            "过三关",
            "应期",
            "神煞",
            "健康取象",
            "婚姻",
            "六亲",
            "事业",
            "财富",
            "学历",
        ]
    return []


def _evidence_topic_groups(topics: list[str]) -> list[list[str]]:
    groups = (
        {"过三关", "应期", "神煞"},
        {"健康", "健康取象", "婚姻", "六亲"},
        {"事业", "财富", "学历"},
    )
    grouped: list[list[str]] = []
    consumed: set[str] = set()
    for members in groups:
        selected = [topic for topic in topics if topic in members]
        if selected:
            grouped.append(selected)
            consumed.update(selected)
    grouped.extend([[topic] for topic in topics if topic not in consumed])
    return grouped


def _evidence_query_terms(topics: list[str]) -> list[str]:
    terms: list[str] = []
    for topic in topics:
        terms.extend(
            {
                "过三关": ["过三关具体应验", "原局大运流年", "星宫位断事"],
                "应期": ["应期方法", "大运流年"],
                "健康": ["健康取象", "五行生克"],
                "健康取象": ["健康取象", "五行生克"],
                "神煞": ["神煞应用", "用忌条件"],
                "婚姻": ["婚姻应期", "配偶星夫妻宫"],
                "六亲": ["六亲应期", "父母星宫"],
                "事业": ["事业应期", "官印食伤"],
                "财富": ["财富应期", "食伤生财"],
                "学历": ["学业应期", "印星文昌"],
            }.get(topic, [topic])
        )
    return _unique(terms)


def _author_method_query(topics: list[str]) -> str:
    if not topics:
        return "应期方法 大运流年"
    topic = topics[0]
    if len(topics) > 1:
        if "过三关" in topics:
            topic = "过三关"
        elif "健康取象" in topics:
            topic = "健康取象"
        elif "婚姻" in topics:
            topic = "婚姻"
    return {
        "过三关": "过三关 大运定阶段 流年定具体应验 星宫位 寻根基 找出处 引动原理",
        "应期": "大运流年应期 原局刑冲合害",
        "健康": "五行生克 健康取象 疾病应期",
        "健康取象": "五行生克 健康取象 疾病应期",
        "神煞": "神煞辅助 五行十神生克 用忌条件",
        "婚姻": "婚姻宫逢冲 配偶星 婚姻不顺 离婚",
        "六亲": "六亲应期 父母星宫 岁运引动",
        "事业": "事业应期 官印食伤 岁运引动",
        "财富": "财富应期 食伤生财 岁运引动",
        "学历": "学业应期 印星文昌 岁运引动",
    }.get(topic, topic)


def _active_dayun(result: Mapping[str, object]) -> str:
    related = result.get("relatedResults")
    dayun = related.get("dayun") if isinstance(related, dict) else None
    cycles = dayun.get("大运列表") if isinstance(dayun, dict) else None
    if not isinstance(cycles, list):
        return ""
    current_year = datetime.now(ZoneInfo("Asia/Shanghai")).year
    eligible = [
        item for item in cycles
        if isinstance(item, dict) and 0 < int(item.get("起运年份") or 0) <= current_year
    ]
    if not eligible:
        return ""
    selected = max(eligible, key=lambda item: int(item.get("起运年份") or 0))
    return str(selected.get("干支") or "")


def _gender(payload: Mapping[str, object]) -> str:
    basic = payload.get("基本信息")
    if isinstance(basic, dict):
        return str(basic.get("性别") or "")
    return str(payload.get("性别") or "")


def _ten_god_family(ten_god: str) -> str:
    return {
        "偏财": "财星", "正财": "财星", "正官": "官星", "七杀": "官杀",
        "偏印": "印星", "正印": "印星", "食神": "食伤", "伤官": "食伤",
        "比肩": "比劫", "劫财": "比劫",
    }.get(ten_god, "")


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))
