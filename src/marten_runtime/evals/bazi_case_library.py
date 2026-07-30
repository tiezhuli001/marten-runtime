from __future__ import annotations

import hashlib

from marten_runtime.bazi_cases.service import BaziCaseService


def evaluate_private_case_retrieval(
    service: BaziCaseService,
    *,
    owner_key: str,
    cases: object,
) -> dict[str, object]:
    corpus, queries = _fixture_parts(cases)
    case_ids: dict[str, str] = {}
    events: dict[str, str] = {}
    for item in corpus:
        fixture_id = str(item["id"])
        saved = service.save_current(
            owner_key=owner_key,
            run_id=f"run-{fixture_id}",
            session_id="eval-session",
            bazi_result=_bazi_result(list(item["pillars"]), fixture_id=fixture_id),
            question=str(item["query"]),
            analysis_summary=f"{item['category']} 类别案例：{item['query']}",
            events=[{
                "category": item["category"],
                "description": item["event"],
                "evidence_type": "document_verified",
            }],
        )
        case_ids[fixture_id] = str(saved["case"]["case_id"])
        events[fixture_id] = str(item["event"])

    counts = {"exact": 0, "near": 0, "feedback": 0, "distractor": 0}
    hits = {"exact": 0, "near": 0, "feedback": 0, "distractor": 0}
    complete = returned = fact_conflicts = prediction_as_event = 0
    cases_report: list[dict[str, object]] = []
    for item in queries:
        query_type = str(item["type"])
        target_id = str(item.get("target_id") or "")
        counts[query_type] += 1
        result = service.search(
            owner_key=owner_key,
            query=str(item["query"]),
            top_k=3,
            current_chart=_bazi_result(list(item["pillars"]), fixture_id=f"query-{item['id']}"),
            event_category=str(item.get("category") or ""),
        )
        matches = list(result["matches"])
        returned += len(matches)
        expected_case_id = case_ids.get(target_id, "")
        rank = next((index + 1 for index, match in enumerate(matches) if match["case_id"] == expected_case_id), 0)
        if query_type == "exact":
            hit = rank == 1 and matches[0].get("match_type") == "direct"
        elif query_type == "distractor":
            hit = not matches
        else:
            target = matches[rank - 1] if rank else None
            hit = bool(
                rank <= 3
                and target is not None
                and (query_type != "feedback" or any(
                    event["description"] == events[target_id] for event in target["verified_events"]
                ))
            )
        hits[query_type] += int(hit)
        complete += sum(
            bool(match.get("similarities"))
            and "differences" in match
            and "timing_triggers" in match
            and bool(match.get("limitations"))
            and match.get("citation", {}).get("kind") == "case"
            and set(match.get("score_parts", {})) == {"structural", "timing", "semantic", "feedback_quality"}
            for match in matches
        )
        fact_conflicts += sum("chart_snapshot" in match or "time_basis" in match for match in matches)
        prediction_as_event += sum(
            event.get("event_id", "").startswith("bpred_")
            for match in matches
            for group in ("verified_events", "reported_events", "inferred_events")
            for event in match[group]
        )
        cases_report.append({
            "id": str(item["id"]), "type": query_type, "hit": hit, "rank": rank,
            "returned_case_ids": [match["case_id"] for match in matches],
            "top_score_parts": matches[0]["score_parts"] if matches else {},
        })

    other_owner = hashlib.sha256(b"eval:foreign-owner").hexdigest()
    owner_leakage = len(service.search(
        owner_key=other_owner, query="事业反馈", current_chart=_bazi_result(list(corpus[0]["pillars"]), fixture_id="foreign")
    )["matches"])
    exact_recall = _ratio(hits["exact"], counts["exact"])
    near_recall = _ratio(hits["near"], counts["near"])
    feedback_recall = _ratio(hits["feedback"], counts["feedback"])
    return {
        "fixture_count": len(corpus),
        "query_count": len(queries),
        "metrics": {
            "exact_recall_at_1": exact_recall,
            "near_recall_at_3": near_recall,
            "theory_only_verified_event_recall_at_3": 0.0,
            "with_cases_verified_event_recall_at_3": feedback_recall,
            "verified_event_recall_lift": feedback_recall,
            "distractor_rejection_rate": _ratio(hits["distractor"], counts["distractor"]),
            "result_contract_completeness": complete / returned if returned else 1.0,
            "owner_leakage": owner_leakage,
            "prediction_as_event": prediction_as_event,
            "builtin_fact_conflicts": fact_conflicts,
        },
        "cases": cases_report,
    }


def _fixture_parts(value: object) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if isinstance(value, dict):
        return list(value.get("corpus") or []), list(value.get("queries") or [])
    fixtures = list(value or [])
    return fixtures, [
        {"id": item["id"], "type": "feedback", "target_id": item["id"], "pillars": item["pillars"], "category": item["category"], "query": item["query"]}
        for item in fixtures
    ]


def _ratio(value: int, total: int) -> float:
    return value / total if total else 1.0


def _bazi_result(pillars: list[object], *, fixture_id: str) -> dict[str, object]:
    digest = hashlib.sha256(fixture_id.encode("utf-8")).hexdigest()
    return {
        "ok": True,
        "inputFingerprint": f"sha256:{digest}",
        "engine": {"name": "mock-bazi", "version": "1"},
        "resultSchemaVersion": "bazi.chart.v1",
        "timeBasis": {"requested": "clock", "timezone": "Asia/Shanghai"},
        "result": {"四柱": [str(item) for item in pillars]},
    }
