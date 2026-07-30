from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from uuid import uuid4

from pydantic import ValidationError

from marten_runtime.bazi_cases.features import cosine_profile, extract_chart_features, jaccard
from marten_runtime.bazi_cases.models import (
    BaziCaseEvent,
    BaziCaseInterpretation,
    BaziCasePrediction,
    BaziCaseRecord,
    BaziCaseReview,
    BaziCaseSourceRef,
    BaziExtractionQuality,
    BaziTopicConclusion,
    SHARED_CASE_NAMESPACE,
    SHARED_CASE_OWNER_KEY,
    utc_now_iso,
)
from marten_runtime.bazi_cases.sqlite_store import SQLiteBaziCaseStore
from marten_runtime.bazi_cases.text_parser import parse_case_text
from marten_runtime.knowledge.service import KnowledgeService


_EVENT_CATEGORIES = frozenset(
    {"education", "career", "wealth", "marriage", "health", "family", "children", "relocation", "legal", "other"}
)
_EVIDENCE_TYPES = frozenset(
    {"user_reported", "document_verified", "operator_verified", "model_inferred"}
)
_MIN_NEAR_SCORE = 0.60


class BaziCaseError(ValueError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class BaziCaseService:
    def __init__(self, store: SQLiteBaziCaseStore, knowledge_service: KnowledgeService) -> None:
        self.store = store
        self.knowledge_service = knowledge_service

    def save_current(
        self,
        *,
        owner_key: str,
        run_id: str,
        session_id: str,
        bazi_result: dict[str, object],
        question: str = "",
        analysis_summary: str = "",
        raw_case_text: str = "",
        interpretation: dict[str, object] | None = None,
        topic_conclusions: list[dict[str, object]] | None = None,
        predictions: list[dict[str, object]] | None = None,
        events: list[dict[str, object]] | None = None,
        reviews: list[dict[str, object]] | None = None,
        source_type: str = "user_saved",
        input_fingerprint: str = "",
        source_ref: dict[str, object] | None = None,
        extraction_quality: dict[str, object] | None = None,
        visibility: str = "private",
        status: str = "active_private",
    ) -> dict[str, object]:
        if bazi_result.get("ok") is not True or not isinstance(bazi_result.get("result"), dict):
            raise BaziCaseError("BAZI_CASE_CURRENT_RUN_REQUIRED", "current turn has no successful Bazi result")
        features = extract_chart_features(bazi_result)
        if not features:
            raise BaziCaseError("BAZI_CASE_CHART_REQUIRED", "four valid pillars are required")
        now = utc_now_iso()
        case_id = f"bcase_{uuid4().hex[:16]}"
        built_predictions = _predictions(predictions or [])
        built_events = _events(events or [])
        _validate_event_prediction_links(built_events, built_predictions)
        built_reviews = _reviews(reviews or [], built_predictions, built_events)
        record = BaziCaseRecord(
            case_id=case_id,
            case_version=1,
            owner_key=owner_key,
            visibility=visibility,
            status=status,
            source_type=source_type,
            source_run_id=run_id,
            source_session_id=session_id,
            input_fingerprint=input_fingerprint or str(bazi_result.get("inputFingerprint") or ""),
            engine=dict(bazi_result.get("engine") or {}),
            result_schema_version=str(bazi_result.get("resultSchemaVersion") or ""),
            time_basis=deepcopy(bazi_result.get("timeBasis")) if isinstance(bazi_result.get("timeBasis"), dict) else None,
            chart_snapshot=_chart_snapshot(bazi_result),
            chart_features=features,
            question=_bounded_text(question, 2000),
            analysis_summary=_bounded_text(analysis_summary, 4000),
            raw_case_text=_bounded_text(raw_case_text, 50000),
            interpretation=_interpretation(interpretation or {}),
            topic_conclusions=_conclusions(topic_conclusions or []),
            predictions=built_predictions,
            events=built_events,
            reviews=built_reviews,
            source_ref=BaziCaseSourceRef(**(source_ref or {})),
            extraction_quality=BaziExtractionQuality(**(extraction_quality or {})),
            projection_namespace=projection_namespace_for_owner(owner_key),
            projection_source_id=f"ksrc_case_{case_id.removeprefix('bcase_')}",
            created_at=now,
            updated_at=now,
        )
        self._write_projection(record)
        try:
            self.store.save(record)
        except Exception:
            try:
                self.knowledge_service.delete_source(
                    namespace=record.projection_namespace, source_id=record.projection_source_id
                )
            except Exception:
                pass
            raise
        return {"ok": True, "action": "save_current", "case": public_case(record)}

    def import_text(
        self, *, owner_key: str, text: str, run_id: str = "", session_id: str = ""
    ) -> dict[str, object]:
        parsed = parse_case_text(_bounded_text(text, 200000))
        if not parsed:
            raise BaziCaseError("BAZI_CASE_IMPORT_EMPTY", "no valid case blocks were found")
        return self.import_candidates(
            owner_key=owner_key,
            candidates=parsed,
            run_id=run_id,
            session_id=session_id,
        )

    def import_candidates(
        self,
        *,
        owner_key: str,
        candidates: list[dict[str, object]],
        run_id: str = "",
        session_id: str = "",
        replace_existing: bool = False,
        shared: bool = False,
    ) -> dict[str, object]:
        if not candidates:
            raise BaziCaseError("BAZI_CASE_IMPORT_EMPTY", "no valid case candidates were supplied")
        target_owner = SHARED_CASE_OWNER_KEY if shared else owner_key
        imported: list[dict[str, object]] = []
        updated: list[dict[str, object]] = []
        skipped_duplicates: list[str] = []
        for index, item in enumerate(candidates):
            if not isinstance(item, dict):
                raise BaziCaseError("BAZI_CASE_IMPORT_INVALID", "each case candidate must be an object")
            existing = self.store.get_by_input_fingerprint(
                target_owner, str(item["input_fingerprint"])
            )
            if existing is not None:
                if replace_existing and existing.source_type == "operator_imported":
                    replacement = self._replace_imported_candidate(existing, item)
                    if replacement is not None:
                        updated.append(public_case(replacement))
                        continue
                skipped_duplicates.append(existing.case_id)
                continue
            item = _rekey_candidate_references(item)
            dayun = [
                {"干支": ganzhi, "起运年份": 0, "起运年龄": position * 10}
                for position, ganzhi in enumerate(item.get("dayun") or [])
            ]
            result = {
                "ok": True,
                "inputFingerprint": item["input_fingerprint"],
                "engine": {"name": "case-text-import", "version": "2"},
                "resultSchemaVersion": "bazi.case.import.v2",
                "result": {"四柱": list(item["pillars"]), "性别": item["gender"]},
                "relatedResults": {"dayun": {"大运列表": dayun}},
            }
            saved = self.save_current(
                owner_key=target_owner,
                run_id=run_id or f"import-{index + 1}",
                session_id=session_id,
                bazi_result=result,
                question=str(item.get("question") or ""),
                analysis_summary=str(item.get("analysis_summary") or ""),
                raw_case_text=str(item.get("raw_case_text") or ""),
                interpretation=dict(item.get("interpretation") or {}),
                topic_conclusions=list(item.get("topic_conclusions") or []),
                predictions=list(item.get("predictions") or []),
                events=list(item.get("events") or []),
                reviews=list(item.get("reviews") or []),
                source_type="operator_imported",
                input_fingerprint=str(item["input_fingerprint"]),
                source_ref=dict(item.get("source_ref") or {}),
                extraction_quality=dict(item.get("extraction_quality") or {}),
                visibility="shared_curated" if shared else "private",
                status="active_shared" if shared else "active_private",
            )
            imported.append(saved["case"])
        return {
            "ok": True,
            "action": "import_text",
            "cases": imported,
            "count": len(imported),
            "updated_count": len(updated),
            "updated_cases": updated,
            "skipped_duplicate_count": len(skipped_duplicates),
            "skipped_duplicate_case_ids": skipped_duplicates,
        }

    def archive_private_imports_replaced_by_shared(
        self, *, content_sha256: str, accepted_fingerprints: set[str]
    ) -> dict[str, object]:
        shared_by_fingerprint = {
            record.input_fingerprint: record
            for record in self.store.list(SHARED_CASE_OWNER_KEY)
            if record.source_ref.content_sha256 == content_sha256
        }
        missing = sorted(accepted_fingerprints - set(shared_by_fingerprint))
        if missing:
            raise BaziCaseError(
                "BAZI_CASE_SHARED_MIGRATION_INCOMPLETE",
                "shared cases must be indexed before private book copies are archived",
            )
        archived: list[str] = []
        for record in self.store.list_active_private_imports_by_source_digest(content_sha256):
            if record.input_fingerprint not in accepted_fingerprints:
                continue
            self.archive(owner_key=record.owner_key, case_id=record.case_id)
            archived.append(record.case_id)
        return {
            "ok": True,
            "archived_private_duplicate_count": len(archived),
            "archived_private_duplicate_case_ids": archived,
        }

    def promote_private_imports_to_shared(
        self,
        *,
        owner_key: str,
        case_ids: list[str],
        source_ref_defaults: dict[str, object] | None = None,
    ) -> dict[str, object]:
        records: list[BaziCaseRecord] = []
        for case_id in dict.fromkeys(case_ids):
            record = self.store.get(owner_key, case_id)
            if record is None or record.status != "active_private":
                raise BaziCaseError("BAZI_CASE_NOT_FOUND", "active private case was not found")
            if record.source_type != "operator_imported":
                raise BaziCaseError(
                    "BAZI_CASE_PROMOTION_NOT_ALLOWED",
                    "only operator-imported cases can be promoted in bulk",
                )
            records.append(record)
        if not records:
            return {
                "ok": True,
                "action": "promote_private_imports_to_shared",
                "promoted_count": 0,
                "archived_private_case_ids": [],
            }

        candidates = [
            _candidate_from_record(record, source_ref_defaults=source_ref_defaults or {})
            for record in records
        ]
        imported = self.import_candidates(
            owner_key="",
            candidates=candidates,
            run_id="operator-promote-private-imports",
            shared=True,
        )
        active_shared = {
            record.input_fingerprint: record
            for record in self.store.list(SHARED_CASE_OWNER_KEY)
        }
        missing = sorted(
            record.input_fingerprint
            for record in records
            if record.input_fingerprint not in active_shared
        )
        if missing:
            raise BaziCaseError(
                "BAZI_CASE_SHARED_MIGRATION_INCOMPLETE",
                "all shared projections must exist before private cases are archived",
            )

        archived: list[str] = []
        for record in records:
            self.archive(owner_key=record.owner_key, case_id=record.case_id)
            archived.append(record.case_id)
        return {
            "ok": True,
            "action": "promote_private_imports_to_shared",
            "promoted_count": len(records),
            "shared_imported_count": imported["count"],
            "shared_duplicate_count": imported["skipped_duplicate_count"],
            "archived_private_case_ids": archived,
        }

    def _replace_imported_candidate(
        self, current: BaziCaseRecord, item: dict[str, object]
    ) -> BaziCaseRecord | None:
        raw_case_text = _bounded_text(item.get("raw_case_text"), 50000)
        if (
            raw_case_text == current.raw_case_text
            and current.extraction_quality.extractor_version == "book.case.extractor.v4"
        ):
            return None
        dayun = [
            {"干支": ganzhi, "起运年份": 0, "起运年龄": position * 10}
            for position, ganzhi in enumerate(item.get("dayun") or [])
        ]
        result = {
            "ok": True,
            "inputFingerprint": item["input_fingerprint"],
            "engine": {"name": "case-text-import", "version": "3"},
            "resultSchemaVersion": "bazi.case.import.v3",
            "result": {"四柱": list(item["pillars"]), "性别": item["gender"]},
            "relatedResults": {"dayun": {"大运列表": dayun}},
        }
        predictions = _predictions(list(item.get("predictions") or []))
        events = _events(list(item.get("events") or []))
        _validate_event_prediction_links(events, predictions)
        reviews = _reviews(list(item.get("reviews") or []), predictions, events)
        updated = current.model_copy(
            update={
                "schema_version": "bazi.case.v3",
                "case_version": current.case_version + 1,
                "engine": dict(result["engine"]),
                "result_schema_version": str(result["resultSchemaVersion"]),
                "chart_snapshot": _chart_snapshot(result),
                "chart_features": extract_chart_features(result),
                "analysis_summary": _bounded_text(item.get("analysis_summary"), 4000),
                "raw_case_text": raw_case_text,
                "interpretation": _interpretation(dict(item.get("interpretation") or {})),
                "topic_conclusions": _conclusions(list(item.get("topic_conclusions") or [])),
                "predictions": predictions,
                "events": events,
                "reviews": reviews,
                "source_ref": BaziCaseSourceRef(**dict(item.get("source_ref") or {})),
                "extraction_quality": BaziExtractionQuality(
                    **dict(item.get("extraction_quality") or {})
                ),
                "updated_at": utc_now_iso(),
            }
        )
        self._replace_projection_and_record(current, updated)
        return updated

    def get(self, *, owner_key: str, case_id: str) -> dict[str, object]:
        return {"ok": True, "case": public_case(self._require(owner_key, case_id), include_raw=True)}

    def list(self, *, owner_key: str, include_archived: bool = False) -> dict[str, object]:
        records = self.store.list(owner_key, include_archived=include_archived)
        return {"ok": True, "cases": [public_case(item) for item in records], "count": len(records)}

    def update_events(
        self,
        *,
        owner_key: str,
        case_id: str,
        events: list[dict[str, object]],
        question: str | None = None,
        analysis_summary: str | None = None,
        predictions: list[dict[str, object]] | None = None,
        reviews: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        current = self._require(owner_key, case_id)
        built_events = _events(events)
        built_predictions = current.predictions if predictions is None else _predictions(predictions)
        _validate_event_prediction_links(built_events, built_predictions)
        review_payloads = (
            [item.model_dump(mode="json") for item in current.reviews]
            if reviews is None else reviews
        )
        built_reviews = _reviews(review_payloads, built_predictions, built_events)
        updated = current.model_copy(
            update={
                "case_version": current.case_version + 1,
                "events": built_events,
                "predictions": built_predictions,
                "reviews": built_reviews,
                "question": current.question if question is None else _bounded_text(question, 2000),
                "analysis_summary": current.analysis_summary if analysis_summary is None else _bounded_text(analysis_summary, 4000),
                "updated_at": utc_now_iso(),
            }
        )
        self._replace_projection_and_record(current, updated)
        return {"ok": True, "action": "update_events", "case": public_case(updated)}

    def archive(self, *, owner_key: str, case_id: str) -> dict[str, object]:
        return self._remove_projection(owner_key=owner_key, case_id=case_id, status="archived")

    def delete(self, *, owner_key: str, case_id: str) -> dict[str, object]:
        return self._remove_projection(owner_key=owner_key, case_id=case_id, status="deleted")

    def search(
        self,
        *,
        owner_key: str,
        query: str,
        top_k: int = 3,
        current_chart: dict[str, object] | None = None,
        event_category: str = "",
    ) -> dict[str, object]:
        query = str(query or "").strip()
        if not query:
            raise BaziCaseError("BAZI_CASE_QUERY_REQUIRED", "query is required")
        if top_k < 1 or top_k > 20:
            raise BaziCaseError("BAZI_CASE_TOP_K_INVALID", "top_k must be between 1 and 20")
        if event_category and event_category not in _EVENT_CATEGORIES:
            raise BaziCaseError("BAZI_CASE_EVENT_CATEGORY_INVALID", "event_category is invalid")
        records = [
            item
            for item in [*self.store.list(SHARED_CASE_OWNER_KEY), *self.store.list(owner_key)]
            if _matches_topic(item, event_category)
        ]
        if not records:
            return {"ok": True, "action": "search", "query": query, "matches": [], "count": 0}
        semantic_scores: dict[str, float] = {}
        semantic_timings: list[dict[str, object]] = []
        for namespace in dict.fromkeys(record.projection_namespace for record in records):
            semantic = self.knowledge_service.search(
                namespace=namespace,
                query=query,
                top_k=max(top_k * 5, 30),
                filters={"evidence_kind": "case_record"},
            )
            if not semantic.get("ok"):
                raise BaziCaseError(
                    "BAZI_CASE_PROJECTION_SEARCH_FAILED",
                    str(semantic.get("message") or semantic.get("error_code") or "case projection search failed"),
                    retryable=True,
                )
            for case_id, score in _case_semantic_scores(list(semantic.get("results") or [])).items():
                semantic_scores[case_id] = max(semantic_scores.get(case_id, 0.0), score)
            semantic_timings.append(semantic)
        current_features = extract_chart_features(current_chart or {})
        matches: list[dict[str, object]] = []
        for record in records:
            direct = bool(
                current_features
                and current_features.get("chart_signature") == record.chart_features.get("chart_signature")
            )
            structure, similarities, differences = structural_similarity(
                current_features, record.chart_features, query=query, interpretation=record.interpretation
            )
            timing, timing_triggers = timing_similarity(current_features, record, query)
            semantic_score = max(
                semantic_scores.get(record.case_id, 0.0),
                _lexical_score(query, projection_text(record)),
            )
            feedback = feedback_quality(record)
            if current_features:
                score = 0.45 * structure + 0.20 * timing + 0.20 * semantic_score + 0.15 * feedback
            else:
                score = (0.20 * semantic_score + 0.15 * feedback) / 0.35
            if not direct and score < _MIN_NEAR_SCORE:
                continue
            matches.append(
                _search_match(
                    record, score, structure, timing, semantic_score, feedback,
                    similarities, differences, timing_triggers, direct,
                )
            )
        matches.sort(key=lambda item: (item["match_type"] != "direct", -float(item["score"]), str(item["case_id"])))
        selected = matches[:top_k]
        return {
            "ok": True,
            "action": "search",
            "query": query,
            "matches": selected,
            "count": len(selected),
            "retrieval": {
                "mode": "chart_timing_semantic_feedback" if current_features else "semantic_feedback",
                "namespace_scope": "shared_curated+owner_private",
                "minimum_near_score": _MIN_NEAR_SCORE,
                "embedding_ms": round(sum(float(item.get("embedding_ms") or 0.0) for item in semantic_timings), 3),
                "total_ms": round(sum(float(item.get("total_ms") or 0.0) for item in semantic_timings), 3),
            },
        }

    def _require(self, owner_key: str, case_id: str) -> BaziCaseRecord:
        record = self.store.get(owner_key, str(case_id or "").strip())
        if record is None:
            raise BaziCaseError("BAZI_CASE_NOT_FOUND", "case was not found")
        return record

    def _write_projection(self, record: BaziCaseRecord) -> None:
        scope_label = "共享书籍案例" if record.visibility == "shared_curated" else "私有案例"
        result = self.knowledge_service.replace_text_source_atomically(
            namespace=record.projection_namespace,
            source={
                "source_id": record.projection_source_id,
                "title": f"{scope_label} {record.case_id}",
                "kind": "bazi_case",
                "uri": f"bazi-case://{record.case_id}",
                "version": str(record.case_version),
                "text": projection_text(record),
                "metadata": {
                    "evidence_kind": "case_record",
                    "case_id": record.case_id,
                    "case_version": record.case_version,
                    "visibility": record.visibility,
                    "event_categories": sorted({event.category for event in record.events}),
                    "verification_status": sorted({event.verification_status for event in record.events}),
                    "source_title": record.source_ref.title,
                    "source_chapter": record.source_ref.chapter,
                    "extraction_grade": record.extraction_quality.grade,
                },
            },
        )
        if not result.get("ok") or result.get("embedding_status") not in {"embedded", "disabled"}:
            raise BaziCaseError("BAZI_CASE_PROJECTION_FAILED", "case projection could not be indexed", retryable=True)

    def _replace_projection_and_record(self, current: BaziCaseRecord, updated: BaziCaseRecord) -> None:
        self._write_projection(updated)
        try:
            self.store.save(updated)
        except Exception:
            self._write_projection(current)
            raise

    def _remove_projection(self, *, owner_key: str, case_id: str, status: str) -> dict[str, object]:
        current = self._require(owner_key, case_id)
        updated = current.model_copy(
            update={"status": status, "case_version": current.case_version + 1, "updated_at": utc_now_iso()}
        )
        self.store.save(updated)
        try:
            deleted = self.knowledge_service.delete_source(
                namespace=current.projection_namespace, source_id=current.projection_source_id
            )
        except Exception:
            self.store.save(current)
            raise
        if not deleted.get("ok"):
            self.store.save(current)
            raise BaziCaseError("BAZI_CASE_PROJECTION_FAILED", "case projection could not be removed", retryable=True)
        result = {"ok": True, "action": status.removesuffix("d"), "case_id": case_id}
        if status == "archived":
            result["case_version"] = updated.case_version
        return result


def owner_key_from_context(context: dict | None) -> str:
    channel_id = " ".join(str((context or {}).get("channel_id") or "").split())
    user_id = " ".join(str((context or {}).get("user_id") or "").split())
    if not channel_id or not user_id:
        raise BaziCaseError("BAZI_CASE_OWNER_REQUIRED", "trusted channel and user identity are required")
    return hashlib.sha256(f"{channel_id}:{user_id}".encode("utf-8")).hexdigest()


def projection_namespace_for_owner(owner_key: str) -> str:
    if owner_key == SHARED_CASE_OWNER_KEY:
        return SHARED_CASE_NAMESPACE
    return f"bazi-cases-private-{owner_key[:24]}"


def structural_similarity(
    current: dict[str, object], candidate: dict[str, object], *, query: str = "",
    interpretation: BaziCaseInterpretation | None = None,
) -> tuple[float, list[str], list[str]]:
    if not current or not candidate:
        return 0.0, [], []
    similarities: list[str] = []
    differences: list[str] = []
    raw = 0.0
    labels = {"day_master": "日主", "month_order": "月令"}
    for key in ("day_master", "month_order"):
        left, right = str(current.get(key) or ""), str(candidate.get(key) or "")
        if left and right and left == right:
            raw += 0.04
            similarities.append(f"{labels[key]}相同：{left}")
        elif left and right:
            differences.append(f"{labels[key]}不同：当前{left}，案例{right}")
    element = cosine_profile(current.get("element_profile"), candidate.get("element_profile")) or 0.0
    ten_god = cosine_profile(current.get("ten_god_profile"), candidate.get("ten_god_profile")) or 0.0
    raw += 0.10 * element + 0.10 * ten_god
    similarities.extend([f"五行分布相似度：{element:.2f}", f"十神分布相似度：{ten_god:.2f}"])
    relation = _relation_similarity(current.get("relations"), candidate.get("relations"))
    raw += 0.09 * relation
    similarities.append(f"干支关系相似度：{relation:.2f}")
    pattern_score = _interpretation_query_score(query, interpretation)
    raw += 0.08 * pattern_score
    if pattern_score:
        similarities.append(f"格局与用神语义相似度：{pattern_score:.2f}")
    for key, label in (("year_pillar", "年柱"), ("month_pillar", "月柱"), ("day_pillar", "日柱"), ("hour_pillar", "时柱")):
        left, right = str(current.get(key) or ""), str(candidate.get(key) or "")
        if left and right and left == right:
            similarities.append(f"{label}相同：{left}")
        elif left and right:
            differences.append(f"{label}不同：当前{left}，案例{right}")
    return min(1.0, raw / 0.45), similarities, differences


def timing_similarity(
    current: dict[str, object], record: BaziCaseRecord, query: str
) -> tuple[float, list[str]]:
    if not current:
        return 0.0, []
    triggers: list[str] = []
    current_periods = list(current.get("dayun_periods") or [])
    candidate_periods = list(record.chart_features.get("dayun_periods") or [])
    current_active = dict(current.get("active_dayun") or {})
    candidate_active = dict(record.chart_features.get("active_dayun") or {})
    score = 0.5 if not current_periods and not candidate_periods else 0.0
    if current_active and candidate_active:
        if current_active.get("ganzhi") == candidate_active.get("ganzhi"):
            score += 0.5
            triggers.append(f"当前大运同为{current_active.get('ganzhi')}")
        else:
            left_elements = {current_active.get("stem_element"), current_active.get("branch_element")}
            right_elements = {candidate_active.get("stem_element"), candidate_active.get("branch_element")}
            overlap = len((left_elements - {None, ""}) & (right_elements - {None, ""}))
            score += 0.25 * min(1.0, overlap)
    current_sequence = [str(item.get("ganzhi") or "") for item in current_periods]
    candidate_sequence = [str(item.get("ganzhi") or "") for item in candidate_periods]
    if current_sequence and candidate_sequence:
        sequence_score = len(set(current_sequence) & set(candidate_sequence)) / max(len(set(current_sequence)), 1)
        score += 0.3 * sequence_score
        if sequence_score:
            triggers.append(f"大运序列重合度：{sequence_score:.2f}")
    years = set(re.findall(r"(?:19|20)\d{2}", query))
    if years:
        timed = [*record.events, *record.predictions]
        if any(str(item.time_start) in years or str(item.time_end) in years for item in timed):
            score += 0.2
            triggers.append("查询年份与案例事件或预测年份一致")
    elif bool(current_periods) != bool(candidate_periods):
        score += 0.25
    return min(1.0, score), triggers


def feedback_quality(record: BaziCaseRecord) -> float:
    if not record.events:
        return 0.0
    event_scores = {"verified": 1.0, "reported": 0.75, "unverified": 0.15}
    base = sum(event_scores[event.verification_status] * event.confidence for event in record.events) / len(record.events)
    reviewed = sum(review.outcome != "unknown" for review in record.reviews)
    return min(1.0, base + min(0.2, reviewed * 0.05))


def projection_text(record: BaziCaseRecord) -> str:
    lines = ["# 盘面特征"]
    labels = {"year_pillar": "年柱", "month_pillar": "月柱", "day_pillar": "日柱", "hour_pillar": "时柱", "day_master": "日主", "month_order": "月令", "gender": "性别"}
    lines.extend(f"{labels[key]}：{record.chart_features[key]}" for key in labels if record.chart_features.get(key))
    if record.question:
        lines.extend(["", "# 原始问题", record.question])
    if record.analysis_summary:
        lines.extend(["", "# 分析摘要", record.analysis_summary])
    interpretation = record.interpretation
    interpretation_parts = [interpretation.strength, interpretation.pattern, *interpretation.useful_elements, *interpretation.favorable_elements, *interpretation.unfavorable_elements, *interpretation.basis]
    if any(interpretation_parts):
        lines.extend(["", "# 理法解释", " ".join(item for item in interpretation_parts if item)])
    if record.topic_conclusions:
        lines.extend(["", "# 主题结论"])
        lines.extend(f"{item.topic}：{item.conclusion}" for item in record.topic_conclusions)
    if record.predictions:
        lines.extend(["", "# 待验证预测"])
        lines.extend(f"{item.topic}｜{item.status}｜{item.time_start}-{item.time_end}：{item.conclusion}" for item in record.predictions)
    visible_events = [event for event in record.events if not event.privacy_redacted]
    if visible_events:
        lines.extend(["", "# 已观察反馈"])
        lines.extend(f"{event.category}｜{event.verification_status}｜{event.evidence_type}：{event.description} {event.outcome}".strip() for event in visible_events)
    return "\n".join(lines)


def public_case(record: BaziCaseRecord, *, include_raw: bool = False) -> dict[str, object]:
    result = {
        "case_id": record.case_id, "schema_version": record.schema_version,
        "case_version": record.case_version, "status": record.status, "visibility": record.visibility,
        "source_type": record.source_type, "source_run_id": record.source_run_id,
        "source_session_id": record.source_session_id, "input_fingerprint": record.input_fingerprint,
        "engine": record.engine, "result_schema_version": record.result_schema_version,
        "chart_features": record.chart_features, "question": record.question,
        "analysis_summary": record.analysis_summary,
        "interpretation": record.interpretation.model_dump(mode="json"),
        "topic_conclusions": [item.model_dump(mode="json") for item in record.topic_conclusions],
        "predictions": [item.model_dump(mode="json") for item in record.predictions],
        "events": [item.model_dump(mode="json") for item in record.events],
        "reviews": [item.model_dump(mode="json") for item in record.reviews],
        "source_ref": record.source_ref.model_dump(mode="json"),
        "extraction_quality": record.extraction_quality.model_dump(mode="json"),
        "created_at": record.created_at, "updated_at": record.updated_at,
    }
    if include_raw:
        result["raw_case_text"] = record.raw_case_text
    return result


def _events(items: list[dict[str, object]]) -> list[BaziCaseEvent]:
    events: list[BaziCaseEvent] = []
    for item in items:
        if not isinstance(item, dict):
            raise BaziCaseError("BAZI_CASE_EVENT_INVALID", "each event must be an object")
        category, evidence_type = str(item.get("category") or ""), str(item.get("evidence_type") or "")
        if category not in _EVENT_CATEGORIES:
            raise BaziCaseError("BAZI_CASE_EVENT_CATEGORY_INVALID", "event category is invalid")
        if evidence_type not in _EVIDENCE_TYPES:
            raise BaziCaseError("BAZI_CASE_EVENT_EVIDENCE_INVALID", "event evidence_type is invalid")
        allowed_status = {"user_reported": "reported", "document_verified": "verified", "operator_verified": "verified", "model_inferred": "unverified"}[evidence_type]
        requested = str(item.get("verification_status") or "")
        if requested and requested != allowed_status:
            raise BaziCaseError("BAZI_CASE_EVENT_VERIFICATION_INVALID", f"{evidence_type} events must use verification_status={allowed_status}")
        payload = {**item, "event_id": str(item.get("event_id") or f"bevt_{uuid4().hex[:16]}"), "category": category, "evidence_type": evidence_type, "verification_status": allowed_status}
        try:
            events.append(BaziCaseEvent(**payload))
        except ValidationError as exc:
            raise BaziCaseError("BAZI_CASE_EVENT_INVALID", "event fields are invalid") from exc
    return events


def _interpretation(item: dict[str, object]) -> BaziCaseInterpretation:
    try:
        return BaziCaseInterpretation(**item)
    except ValidationError as exc:
        raise BaziCaseError("BAZI_CASE_INTERPRETATION_INVALID", "interpretation fields are invalid") from exc


def _conclusions(items: list[dict[str, object]]) -> list[BaziTopicConclusion]:
    try:
        return [BaziTopicConclusion(**{**item, "conclusion_id": str(item.get("conclusion_id") or f"bcon_{uuid4().hex[:16]}")}) for item in items]
    except (ValidationError, AttributeError) as exc:
        raise BaziCaseError("BAZI_CASE_CONCLUSION_INVALID", "topic conclusion fields are invalid") from exc


def _predictions(items: list[dict[str, object]]) -> list[BaziCasePrediction]:
    try:
        return [BaziCasePrediction(**{**item, "prediction_id": str(item.get("prediction_id") or f"bpred_{uuid4().hex[:16]}")}) for item in items]
    except (ValidationError, AttributeError) as exc:
        raise BaziCaseError("BAZI_CASE_PREDICTION_INVALID", "prediction fields are invalid") from exc


def _reviews(items: list[dict[str, object]], predictions: list[BaziCasePrediction], events: list[BaziCaseEvent]) -> list[BaziCaseReview]:
    prediction_ids = {item.prediction_id for item in predictions}
    event_ids = {item.event_id for item in events}
    result: list[BaziCaseReview] = []
    for item in items:
        if not isinstance(item, dict) or str(item.get("prediction_id") or "") not in prediction_ids:
            raise BaziCaseError("BAZI_CASE_REVIEW_REFERENCE_INVALID", "review must reference an existing prediction")
        if item.get("event_id") and str(item["event_id"]) not in event_ids:
            raise BaziCaseError("BAZI_CASE_REVIEW_REFERENCE_INVALID", "review event reference is invalid")
        try:
            result.append(BaziCaseReview(**{**item, "review_id": str(item.get("review_id") or f"brev_{uuid4().hex[:16]}"), "created_at": str(item.get("created_at") or utc_now_iso())}))
        except ValidationError as exc:
            raise BaziCaseError("BAZI_CASE_REVIEW_INVALID", "review fields are invalid") from exc
    return result


def _validate_event_prediction_links(
    events: list[BaziCaseEvent], predictions: list[BaziCasePrediction]
) -> None:
    prediction_ids = {item.prediction_id for item in predictions}
    if any(set(event.linked_prediction_ids) - prediction_ids for event in events):
        raise BaziCaseError(
            "BAZI_CASE_EVENT_PREDICTION_REFERENCE_INVALID",
            "event must reference an existing prediction",
        )


def _rekey_candidate_references(item: dict[str, object]) -> dict[str, object]:
    candidate = deepcopy(item)
    prediction_ids: dict[str, str] = {}
    predictions = list(candidate.get("predictions") or [])
    for prediction in predictions:
        if not isinstance(prediction, dict):
            continue
        old_id = str(prediction.get("prediction_id") or "")
        new_id = f"bpred_{uuid4().hex[:16]}"
        if old_id:
            prediction_ids[old_id] = new_id
        prediction["prediction_id"] = new_id

    event_ids: dict[str, str] = {}
    events = list(candidate.get("events") or [])
    for event in events:
        if not isinstance(event, dict):
            continue
        old_id = str(event.get("event_id") or "")
        new_id = f"bevt_{uuid4().hex[:16]}"
        if old_id:
            event_ids[old_id] = new_id
        event["event_id"] = new_id
        event["linked_prediction_ids"] = [
            prediction_ids.get(str(value), str(value))
            for value in event.get("linked_prediction_ids") or []
        ]

    reviews = list(candidate.get("reviews") or [])
    for review in reviews:
        if not isinstance(review, dict):
            continue
        review["review_id"] = f"brev_{uuid4().hex[:16]}"
        review["prediction_id"] = prediction_ids.get(
            str(review.get("prediction_id") or ""), str(review.get("prediction_id") or "")
        )
        if review.get("event_id"):
            review["event_id"] = event_ids.get(
                str(review["event_id"]), str(review["event_id"])
            )
    candidate["predictions"] = predictions
    candidate["events"] = events
    candidate["reviews"] = reviews
    return candidate


def _candidate_from_record(
    record: BaziCaseRecord, *, source_ref_defaults: dict[str, object]
) -> dict[str, object]:
    snapshot = record.chart_snapshot
    related = snapshot.get("_related_results")
    dayun_result = related.get("dayun") if isinstance(related, dict) else None
    dayun_rows = dayun_result.get("大运列表") if isinstance(dayun_result, dict) else []
    dayun = [
        str(item.get("干支") or "")
        for item in dayun_rows
        if isinstance(item, dict) and item.get("干支")
    ]
    source_ref = record.source_ref.model_dump(mode="json")
    for key, value in source_ref_defaults.items():
        if key in source_ref and not source_ref[key] and value:
            source_ref[key] = value
    return {
        "gender": str(snapshot.get("性别") or ""),
        "pillars": list(snapshot.get("四柱") or []),
        "dayun": dayun,
        "input_fingerprint": record.input_fingerprint,
        "question": record.question,
        "analysis_summary": record.analysis_summary,
        "raw_case_text": record.raw_case_text,
        "interpretation": record.interpretation.model_dump(mode="json"),
        "topic_conclusions": [
            item.model_dump(mode="json") for item in record.topic_conclusions
        ],
        "predictions": [item.model_dump(mode="json") for item in record.predictions],
        "events": [item.model_dump(mode="json") for item in record.events],
        "reviews": [item.model_dump(mode="json") for item in record.reviews],
        "source_ref": source_ref,
        "extraction_quality": record.extraction_quality.model_dump(mode="json"),
    }


def _chart_snapshot(bazi_result: dict[str, object]) -> dict[str, object]:
    snapshot = deepcopy(dict(bazi_result["result"]))
    related = bazi_result.get("relatedResults")
    if isinstance(related, dict) and related:
        snapshot["_related_results"] = deepcopy(related)
    return snapshot


def _bounded_text(value: object, maximum: int) -> str:
    text = str(value or "").strip()
    if len(text) > maximum:
        raise BaziCaseError("BAZI_CASE_TEXT_TOO_LONG", f"text exceeds {maximum} characters")
    return text


def _semantic_score(item: dict[str, object]) -> float:
    return max(0.0, min(1.0, float(item.get("score") or 0.0)))


def _case_semantic_scores(items: list[dict[str, object]]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for item in items:
        case_id = str(dict(item.get("metadata") or {}).get("case_id") or "")
        if case_id:
            scores[case_id] = max(scores.get(case_id, 0.0), _semantic_score(item))
    return scores


def _lexical_score(query: str, text: str) -> float:
    compact_query = re.sub(r"\s+", "", query.lower())
    compact_text = re.sub(r"\s+", "", text.lower())
    if not compact_query:
        return 0.0
    if compact_query in compact_text:
        return 1.0
    units = {compact_query[index:index + 2] for index in range(max(1, len(compact_query) - 1))}
    return sum(unit in compact_text for unit in units) / len(units)


def _matches_topic(record: BaziCaseRecord, category: str) -> bool:
    if not category:
        return True
    return any(item.category == category for item in record.events) or any(item.topic == category for item in [*record.topic_conclusions, *record.predictions])


def _relation_similarity(left: object, right: object) -> float:
    if isinstance(left, list) and isinstance(right, list) and not left and not right:
        return 1.0
    return jaccard(left, right) or 0.0


def _interpretation_query_score(query: str, interpretation: BaziCaseInterpretation | None) -> float:
    if interpretation is None:
        return 0.0
    terms = [interpretation.pattern, *interpretation.useful_elements, *interpretation.favorable_elements, *interpretation.unfavorable_elements]
    terms = [term for term in terms if term]
    if not terms:
        return 0.0
    return sum(term in query for term in terms) / len(terms)


def _search_match(
    record: BaziCaseRecord, score: float, structural_score: float, timing_score: float,
    semantic_score: float, feedback_score: float, similarities: list[str], differences: list[str],
    timing_triggers: list[str], direct: bool,
) -> dict[str, object]:
    visible_events = [event for event in record.events if not event.privacy_redacted]
    verified = [event.model_dump(mode="json") for event in visible_events if event.verification_status == "verified"]
    reported = [event.model_dump(mode="json") for event in visible_events if event.verification_status == "reported"]
    inferred = [event.model_dump(mode="json") for event in visible_events if event.verification_status == "unverified"]
    citation: dict[str, object] = {
        "kind": "case", "case_id": record.case_id, "case_version": record.case_version
    }
    if record.source_ref.title:
        citation.update(
            {
                "source_title": record.source_ref.title,
                "chapter": record.source_ref.chapter,
                "line_start": record.source_ref.line_start,
                "line_end": record.source_ref.line_end,
            }
        )
    return {
        "case_id": record.case_id, "case_version": record.case_version,
        "visibility": record.visibility,
        "match_type": "direct" if direct else "near",
        "similarity_level": "direct" if direct else ("high" if score >= 0.75 else "reference"),
        "score": round(score, 6),
        "score_parts": {"structural": round(structural_score, 6), "timing": round(timing_score, 6), "semantic": round(semantic_score, 6), "feedback_quality": round(feedback_score, 6)},
        "similarities": similarities or ["问题语义相关；未提供足够盘面特征进行结构比较"],
        "differences": differences, "timing_triggers": timing_triggers,
        "verified_events": verified, "reported_events": reported, "inferred_events": inferred,
        "predictions": [item.model_dump(mode="json") for item in record.predictions],
        "reviews": [item.model_dump(mode="json") for item in record.reviews],
        "topic_conclusions": [item.model_dump(mode="json") for item in record.topic_conclusions],
        "analysis_summary": record.analysis_summary,
        "citation": citation,
        "limitations": ["单个案例不能证明因果，也不能替代经典规则或确定性排盘事实。"],
    }
