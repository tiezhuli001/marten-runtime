from __future__ import annotations

import re

from marten_runtime.bazi.timing_relations import timing_relation_facts
from marten_runtime.bazi_cases.models import SHARED_CASE_OWNER_KEY
from marten_runtime.bazi_cases.service import BaziCaseService
from marten_runtime.knowledge.service import KnowledgeService


_STEMS = "甲乙丙丁戊己庚辛壬癸"
_BRANCHES = "子丑寅卯辰巳午未申酉戌亥"


def evaluate_book_pipeline(
    case_service: BaziCaseService,
    knowledge_service: KnowledgeService,
    *,
    owner_key: str,
) -> dict[str, object]:
    timing_fixtures = [
        {
            "name": "婚姻反馈2000",
            "pillars": ["乙卯", "乙酉", "癸酉", "庚申"],
            "expected_year": 2000,
            "years": range(1997, 2004),
            "target_label": "日支",
        },
        {
            "name": "母亲健康反馈2000",
            "pillars": ["戊辰", "庚申", "辛巳", "辛卯"],
            "expected_year": 2000,
            "years": range(1997, 2004),
            "target_label": "年支",
        },
    ]
    old_year_hits = 0
    new_year_hits = 0
    old_pm1_hits = 0
    new_pm1_hits = 0
    timing_details: list[dict[str, object]] = []
    for fixture in timing_fixtures:
        old_ranked = _rank_years(
            fixture["pillars"], fixture["years"], target_label=str(fixture["target_label"]), complete=False
        )
        new_ranked = _rank_years(
            fixture["pillars"], fixture["years"], target_label=str(fixture["target_label"]), complete=True
        )
        expected = int(fixture["expected_year"])
        old_top3 = [year for _, year in old_ranked[:3]]
        new_top3 = [year for _, year in new_ranked[:3]]
        old_year_hits += int(expected in old_top3)
        new_year_hits += int(expected in new_top3)
        old_pm1_hits += int(any(abs(year - expected) <= 1 for year in old_top3))
        new_pm1_hits += int(any(abs(year - expected) <= 1 for year in new_top3))
        timing_details.append(
            {"name": fixture["name"], "expected_year": expected, "old_top3": old_top3, "new_top3": new_top3}
        )

    case_fixtures = [
        (["戊寅", "丁巳", "丁巳", "辛丑"], "巳酉丑三合后财运急转并濒临破产", "wealth", 49759),
        (["乙卯", "乙酉", "癸酉", "庚申"], "庚辰合婚姻宫，实际在2000年结婚", "marriage", 50841),
        (["戊辰", "庚申", "辛巳", "辛卯"], "母亲病情加重并在2000年得到反馈", "health", 30918),
    ]
    case_hits = 0
    citation_hits = 0
    subject_hits = 0
    case_details: list[dict[str, object]] = []
    expected_subject = {49759: "asset", 50841: "self", 30918: "mother"}
    for pillars, query, category, line_start in case_fixtures:
        result = case_service.search(
            owner_key=owner_key,
            query=query,
            top_k=3,
            current_chart={"result": {"四柱": pillars}},
            event_category=category,
        )
        matches = list(result.get("matches") or [])
        hit = next(
            (
                item for item in matches
                if int(dict(item.get("citation") or {}).get("line_start") or 0) == line_start
            ),
            None,
        )
        case_hits += int(hit is not None)
        citation = dict(hit.get("citation") or {}) if hit else {}
        citation_hits += int(bool(citation.get("source_title") and citation.get("chapter") and citation.get("line_start")))
        event_groups = ["verified_events", "reported_events", "inferred_events"]
        subjects = {
            str(event.get("subject") or "")
            for group in event_groups
            for event in (hit.get(group) or [] if hit else [])
        }
        subject_hits += int(expected_subject[line_start] in subjects)
        case_details.append({"line_start": line_start, "hit": hit is not None, "subjects": sorted(subjects)})

    method_fixtures = [
        ("庚辰 合婚姻宫 酉金", "第720章"),
        ("巳酉丑三合 比劫 用神", "第382章"),
    ]
    method_hits = 0
    method_details: list[dict[str, object]] = []
    for query, expected_chapter in method_fixtures:
        result = knowledge_service.search(
            namespace="bazi-theory",
            query=query,
            top_k=3,
            filters={"content_type": "timing_method"},
        )
        headings = [str(item.get("heading") or "") for item in result.get("results") or []]
        hit = any(expected_chapter in heading for heading in headings)
        method_hits += int(hit)
        method_details.append(
            {
                "query": query,
                "expected_chapter": expected_chapter,
                "hit": hit,
                "retrieval_mode": result.get("retrieval_mode"),
                "vector_status": result.get("vector_status"),
                "rerank_status": result.get("rerank_status"),
                "headings": headings,
            }
        )

    active_shared_cases = [
        record for record in case_service.store.list(SHARED_CASE_OWNER_KEY)
        if record.source_ref.title
    ]
    events = [event for record in active_shared_cases for event in record.events]
    predictive_without_feedback = [
        event for event in events
        if re.search(r"可能|应该|应当|推断|判断|预测|将会", event.description)
        and not re.search(r"事实|实际|反馈|果然|的确|应验", event.description)
    ]
    denominator = max(1, len(timing_fixtures))
    return {
        "metrics": {
            "timing_year_recall_at_3_before": old_year_hits / denominator,
            "timing_year_recall_at_3_after": new_year_hits / denominator,
            "timing_year_pm1_hit_rate_before": old_pm1_hits / denominator,
            "timing_year_pm1_hit_rate_after": new_pm1_hits / denominator,
            "case_retrieval_recall_at_3": case_hits / len(case_fixtures),
            "method_rag_recall_at_3": method_hits / len(method_fixtures),
            "event_subject_accuracy": subject_hits / len(case_fixtures),
            "citation_completeness": citation_hits / len(case_fixtures),
            "prediction_as_event_rate": len(predictive_without_feedback) / max(1, len(events)),
            "active_shared_case_count": len(active_shared_cases),
        },
        "timing_cases": timing_details,
        "case_queries": case_details,
        "method_queries": method_details,
    }


def _rank_years(
    pillars: list[str], years, *, target_label: str, complete: bool
) -> list[tuple[int, int]]:  # noqa: ANN001
    ranked: list[tuple[int, int]] = []
    branches = [pillar[1] for pillar in pillars]
    for year in years:
        annual = _year_pillar(int(year))
        if complete:
            facts = timing_relation_facts(annual, moving_label="流年", natal_pillars=pillars)
            target_relations = [
                item for item in [*facts.stem_relations, *facts.branch_relations, *facts.multi_relations]
                if target_label in item
            ]
            score = sum(_relation_trigger_weight(item) for item in target_relations)
        else:
            target_index = {"年支": 0, "月支": 1, "日支": 2, "时支": 3}[target_label]
            score = 3 * int(annual[1] == branches[target_index])
        ranked.append((score, int(year)))
    return sorted(ranked, key=lambda item: (-item[0], item[1]))


def _year_pillar(year: int) -> str:
    return _STEMS[(year - 4) % 10] + _BRANCHES[(year - 4) % 12]


def _relation_trigger_weight(relation: str) -> int:
    if "伏吟" in relation or "自刑" in relation:
        return 3
    if "相冲" in relation or "相刑" in relation or "相害" in relation:
        return 2
    return 1
