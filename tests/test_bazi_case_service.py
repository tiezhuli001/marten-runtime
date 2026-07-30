from __future__ import annotations

import unittest

from marten_runtime.bazi_cases.service import owner_key_from_context, projection_namespace_for_owner
from marten_runtime.bazi_cases.models import SHARED_CASE_OWNER_KEY
from marten_runtime.knowledge.embeddings import EmbeddingResult, EmbeddingStatus
from tests.bazi_case_support import bazi_result, build_case_service


class MissingEmbeddingAdapter:
    def embed_texts(self, _texts: list[str]) -> EmbeddingResult:
        return EmbeddingResult(status=EmbeddingStatus.MISSING_MODEL, message="missing fixture model")

    def is_loaded(self) -> bool:
        return False

    def unload(self) -> bool:
        return False

    def model_status(self, *, idle_ttl_seconds: float | None) -> dict[str, object]:
        return {"status": "not_loaded"}


class BaziCaseServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service, self.tmp = build_case_service()
        self.owner_a = owner_key_from_context({"channel_id": "feishu", "user_id": "user-a"})
        self.owner_b = owner_key_from_context({"channel_id": "feishu", "user_id": "user-b"})

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def save(self, owner: str | None = None) -> dict[str, object]:
        return self.service.save_current(
            owner_key=owner or self.owner_a,
            run_id="run-1",
            session_id="session-1",
            bazi_result=bazi_result(["甲子", "丙寅", "戊辰", "庚申"]),
            question="事业发展如何",
            analysis_summary="先依据经典判断，再参考已验证事业事件。",
            events=[
                {
                    "category": "career",
                    "description": "2021年晋升为部门负责人",
                    "evidence_type": "document_verified",
                    "time_start": "2021",
                    "time_precision": "exact_year",
                },
                {
                    "category": "wealth",
                    "description": "用户称收入增加",
                    "evidence_type": "user_reported",
                },
                {
                    "category": "marriage",
                    "description": "模型推测关系变化",
                    "evidence_type": "model_inferred",
                    "privacy_redacted": True,
                },
            ],
        )

    def test_save_keeps_authoritative_snapshot_private_and_projects_redacted_text(self) -> None:
        saved = self.save()["case"]

        self.assertEqual(saved["chart_features"]["day_pillar"], "戊辰")
        self.assertNotIn("chart_snapshot", saved)
        self.assertNotIn("time_basis", saved)
        source = self.service.knowledge_service.store.get_source(
            projection_namespace_for_owner(self.owner_a),
            f"ksrc_case_{saved['case_id'].removeprefix('bcase_')}",
        )
        chunks = self.service.knowledge_service.store.list_chunks(source.namespace, source_id=source.source_id)
        projection = "\n".join(chunk.text for chunk in chunks)
        self.assertNotIn("1990-01-01", projection)
        self.assertNotIn("模型推测关系变化", projection)
        self.assertNotIn(self.owner_a, projection)

    def test_owner_isolation_fails_without_revealing_foreign_case(self) -> None:
        case_id = self.save()["case"]["case_id"]

        foreign_get = self.service.store.get(self.owner_b, case_id)
        foreign_list = self.service.list(owner_key=self.owner_b)
        foreign_search = self.service.search(owner_key=self.owner_b, query="事业", top_k=3)

        self.assertIsNone(foreign_get)
        self.assertEqual(foreign_list["cases"], [])
        self.assertEqual(foreign_search["matches"], [])
        self.assertNotEqual(
            projection_namespace_for_owner(self.owner_a), projection_namespace_for_owner(self.owner_b)
        )

    def test_shared_curated_case_is_visible_without_exposing_foreign_private_cases(self) -> None:
        private_case_id = self.save(owner=self.owner_a)["case"]["case_id"]
        shared = self.service.import_candidates(
            owner_key="",
            shared=True,
            candidates=[{
                "gender": "male",
                "pillars": ["甲子", "丙寅", "戊辰", "庚申"],
                "dayun": [],
                "input_fingerprint": "sha256:" + "9" * 64,
                "analysis_summary": "书籍共享事业案例",
                "events": [{
                    "category": "career", "description": "2021年晋升",
                    "evidence_type": "document_verified",
                }],
                "source_ref": {"title": "测试命书", "chapter": "事业章"},
            }],
        )["cases"][0]

        result = self.service.search(
            owner_key=self.owner_b,
            query="事业晋升",
            current_chart=bazi_result(["甲子", "丙寅", "戊辰", "庚申"]),
        )

        self.assertEqual(shared["status"], "active_shared")
        self.assertEqual(shared["visibility"], "shared_curated")
        self.assertEqual(self.service.store.list(SHARED_CASE_OWNER_KEY)[0].case_id, shared["case_id"])
        self.assertIn(shared["case_id"], {item["case_id"] for item in result["matches"]})
        self.assertNotIn(private_case_id, {item["case_id"] for item in result["matches"]})

    def test_shared_import_archives_only_matching_private_book_copy(self) -> None:
        source_digest = "a" * 64
        candidate = {
            "gender": "male",
            "pillars": ["甲子", "丙寅", "戊辰", "庚申"],
            "dayun": [],
            "input_fingerprint": "sha256:" + "8" * 64,
            "analysis_summary": "书籍案例",
            "predictions": [{
                "prediction_id": "book-prediction-1", "topic": "career",
                "conclusion": "事业会变化",
            }],
            "events": [{
                "event_id": "book-event-1", "category": "career",
                "description": "书中反馈事业变化", "evidence_type": "document_verified",
                "linked_prediction_ids": ["book-prediction-1"],
            }],
            "reviews": [{
                "review_id": "book-review-1", "prediction_id": "book-prediction-1",
                "event_id": "book-event-1", "outcome": "confirmed",
            }],
            "source_ref": {
                "title": "测试命书", "chapter": "事业章", "content_sha256": source_digest,
            },
        }
        private = self.service.import_candidates(
            owner_key=self.owner_a, candidates=[candidate]
        )["cases"][0]
        user_case = self.save(owner=self.owner_a)["case"]
        shared = self.service.import_candidates(
            owner_key="", shared=True, candidates=[candidate]
        )["cases"][0]

        migration = self.service.archive_private_imports_replaced_by_shared(
            content_sha256=source_digest,
            accepted_fingerprints={candidate["input_fingerprint"]},
        )

        self.assertEqual(migration["archived_private_duplicate_count"], 1)
        self.assertEqual(
            self.service.store.get(self.owner_a, private["case_id"]).status,
            "archived",
        )
        self.assertEqual(
            self.service.store.get(self.owner_a, user_case["case_id"]).status,
            "active_private",
        )
        source = self.service.knowledge_service.store.get_source(
            projection_namespace_for_owner(SHARED_CASE_OWNER_KEY),
            f"ksrc_case_{shared['case_id'].removeprefix('bcase_')}",
        )
        self.assertTrue(source.title.startswith("共享书籍案例"))

    def test_private_book_copy_is_not_archived_until_shared_projection_exists(self) -> None:
        source_digest = "b" * 64
        with self.assertRaisesRegex(ValueError, "shared cases must be indexed"):
            self.service.archive_private_imports_replaced_by_shared(
                content_sha256=source_digest,
                accepted_fingerprints={"sha256:" + "7" * 64},
            )

    def test_operator_imports_can_be_promoted_to_shared_without_losing_case_structure(self) -> None:
        candidate = {
            "gender": "male",
            "pillars": ["甲子", "丙寅", "戊辰", "庚申"],
            "dayun": ["丁卯", "戊辰"],
            "input_fingerprint": "sha256:" + "6" * 64,
            "question": "事业与婚姻如何",
            "analysis_summary": "原局以食伤生财论。",
            "predictions": [{
                "prediction_id": "prediction-1", "topic": "career",
                "conclusion": "事业平台有调整",
            }],
            "events": [{
                "event_id": "event-1", "category": "career",
                "description": "2021年调整岗位", "evidence_type": "document_verified",
                "linked_prediction_ids": ["prediction-1"],
            }],
            "reviews": [{
                "review_id": "review-1", "prediction_id": "prediction-1",
                "event_id": "event-1", "outcome": "confirmed",
            }],
        }
        private = self.service.import_candidates(
            owner_key=self.owner_a, candidates=[candidate], run_id="local-case-md"
        )["cases"][0]

        result = self.service.promote_private_imports_to_shared(
            owner_key=self.owner_a,
            case_ids=[private["case_id"]],
            source_ref_defaults={"title": "本地可信案例集"},
        )

        self.assertEqual(result["promoted_count"], 1)
        self.assertEqual(self.service.list(owner_key=self.owner_a)["cases"], [])
        shared = self.service.store.list(SHARED_CASE_OWNER_KEY)[0]
        self.assertEqual(shared.question, "事业与婚姻如何")
        self.assertEqual(shared.source_ref.title, "本地可信案例集")
        self.assertEqual(shared.events[0].description, "2021年调整岗位")
        self.assertEqual(shared.reviews[0].event_id, shared.events[0].event_id)
        self.assertEqual(
            shared.reviews[0].prediction_id, shared.predictions[0].prediction_id
        )
        foreign = self.service.search(
            owner_key=self.owner_b,
            query="事业平台调整",
            current_chart=bazi_result(["甲子", "丙寅", "戊辰", "庚申"]),
        )
        self.assertEqual(foreign["matches"][0]["case_id"], shared.case_id)

        repeated = self.service.promote_private_imports_to_shared(
            owner_key=self.owner_a, case_ids=[]
        )
        self.assertEqual(repeated["promoted_count"], 0)

    def test_update_versions_events_and_preserves_evidence_rules(self) -> None:
        case_id = self.save()["case"]["case_id"]
        updated = self.service.update_events(
            owner_key=self.owner_a,
            case_id=case_id,
            events=[
                {
                    "category": "career",
                    "description": "2022年转任总监",
                    "evidence_type": "user_reported",
                }
            ],
        )["case"]

        self.assertEqual(updated["case_version"], 2)
        self.assertEqual(updated["events"][0]["verification_status"], "reported")
        search = self.service.search(
            owner_key=self.owner_a,
            query="转任总监",
            top_k=1,
            current_chart=bazi_result(["甲子", "丙寅", "戊辰", "庚申"]),
        )
        self.assertEqual(search["matches"][0]["reported_events"][0]["description"], "2022年转任总监")
        self.assertEqual(search["matches"][0]["verified_events"], [])

    def test_archive_and_delete_remove_projection_and_search_visibility(self) -> None:
        case_id = self.save()["case"]["case_id"]
        self.service.archive(owner_key=self.owner_a, case_id=case_id)

        self.assertEqual(self.service.list(owner_key=self.owner_a)["cases"], [])
        self.assertEqual(self.service.search(owner_key=self.owner_a, query="事业")["matches"], [])
        archived = self.service.list(owner_key=self.owner_a, include_archived=True)["cases"][0]
        self.assertEqual(archived["status"], "archived")
        self.service.delete(owner_key=self.owner_a, case_id=case_id)
        self.assertEqual(self.service.list(owner_key=self.owner_a, include_archived=True)["cases"], [])

    def test_search_returns_separate_verification_groups_and_explainable_similarity(self) -> None:
        self.save()
        result = self.service.search(
            owner_key=self.owner_a,
            query="事业晋升",
            top_k=3,
            current_chart=bazi_result(["甲子", "丙寅", "戊辰", "辛酉"]),
        )

        match = result["matches"][0]
        self.assertGreater(match["score_parts"]["structural"], 0.5)
        self.assertGreaterEqual(match["score"], 0.60)
        self.assertEqual(match["match_type"], "near")
        self.assertIn("日柱相同：戊辰", match["similarities"])
        self.assertTrue(any("时柱不同" in item for item in match["differences"]))
        self.assertEqual(len(match["verified_events"]), 1)
        self.assertEqual(len(match["reported_events"]), 1)
        self.assertEqual(match["inferred_events"], [])
        self.assertEqual(match["citation"]["kind"], "case")
        self.assertTrue(match["limitations"])

    def test_exact_chart_is_direct_and_predictions_never_become_events(self) -> None:
        saved = self.service.save_current(
            owner_key=self.owner_a,
            run_id="run-prediction",
            session_id="session-1",
            bazi_result=bazi_result(["甲子", "丙寅", "戊辰", "庚申"]),
            question="2026年事业如何",
            predictions=[
                {
                    "topic": "career",
                    "time_start": "2026",
                    "time_precision": "exact_year",
                    "conclusion": "2026年可能调整岗位",
                }
            ],
            events=[],
        )["case"]

        result = self.service.search(
            owner_key=self.owner_a,
            query="2026年事业岗位",
            current_chart=bazi_result(["甲子", "丙寅", "戊辰", "庚申"]),
        )

        match = next(item for item in result["matches"] if item["case_id"] == saved["case_id"])
        self.assertEqual(match["match_type"], "direct")
        self.assertEqual(len(match["predictions"]), 1)
        self.assertEqual(match["verified_events"], [])
        self.assertEqual(match["reported_events"], [])
        self.assertEqual(match["inferred_events"], [])

    def test_import_text_keeps_conclusions_predictions_and_feedback_separate(self) -> None:
        result = self.service.import_text(
            owner_key=self.owner_a,
            text="""男：13
庚 庚 己 癸
辰 辰 未 酉
大运：
辛 庚 癸 甲 乙 丙
巳 午 未 申 酉 戌
原局：己土生辰月，主要用食伤。
财运：未来甲申、乙酉可能会有是非。
命主反馈：23年到25年过得不舒服，有不少是非。""",
        )

        case = self.service.get(owner_key=self.owner_a, case_id=result["cases"][0]["case_id"])["case"]
        self.assertEqual(result["count"], 1)
        self.assertEqual(case["chart_features"]["pillars"], ["庚辰", "庚辰", "己未", "癸酉"])
        self.assertEqual(case["source_type"], "operator_imported")
        self.assertEqual(len(case["predictions"]), 1)
        self.assertEqual(case["predictions"][0]["status"], "pending")
        self.assertEqual(len(case["events"]), 1)
        self.assertEqual(case["events"][0]["verification_status"], "reported")
        self.assertIn("男:13", case["raw_case_text"].replace(" ", ""))

        duplicate = self.service.import_text(
            owner_key=self.owner_a,
            text="""男：13
庚 庚 己 癸
辰 辰 未 酉
大运：
辛 庚 癸 甲 乙 丙
巳 午 未 申 酉 戌
原局：己土生辰月，主要用食伤。
财运：未来甲申、乙酉可能会有是非。
命主反馈：23年到25年过得不舒服，有不少是非。""",
        )
        self.assertEqual(duplicate["count"], 0)
        self.assertEqual(duplicate["skipped_duplicate_count"], 1)

    def test_event_cannot_link_to_missing_prediction(self) -> None:
        with self.assertRaisesRegex(ValueError, "existing prediction"):
            self.service.save_current(
                owner_key=self.owner_a,
                run_id="run-invalid-link",
                session_id="session-1",
                bazi_result=bazi_result(["甲子", "丙寅", "戊辰", "庚申"]),
                events=[{
                    "category": "career",
                    "description": "岗位发生变化",
                    "evidence_type": "user_reported",
                    "linked_prediction_ids": ["bpred_missing"],
                }],
            )

    def test_all_same_chart_cases_sort_before_near_cases(self) -> None:
        same_chart = ["甲子", "丙寅", "戊辰", "庚申"]
        direct_ids = {
            self.service.save_current(
                owner_key=self.owner_a,
                run_id=f"run-direct-{index}",
                session_id="session-1",
                bazi_result=bazi_result(same_chart, fingerprint_char=str(index)),
                question="事业变化",
                events=[{
                    "category": "career",
                    "description": f"第{index}个同盘反馈",
                    "evidence_type": "user_reported",
                }],
            )["case"]["case_id"]
            for index in (1, 2)
        }
        self.service.save_current(
            owner_key=self.owner_a,
            run_id="run-near",
            session_id="session-1",
            bazi_result=bazi_result(["甲子", "丙寅", "戊辰", "辛酉"]),
            question="事业变化",
            events=[{
                "category": "career",
                "description": "近似盘反馈",
                "evidence_type": "user_reported",
            }],
        )

        matches = self.service.search(
            owner_key=self.owner_a,
            query="事业变化",
            top_k=3,
            current_chart=bazi_result(same_chart),
            event_category="career",
        )["matches"]

        self.assertEqual({item["case_id"] for item in matches[:2]}, direct_ids)
        self.assertEqual([item["match_type"] for item in matches[:2]], ["direct", "direct"])

    def test_failed_projection_update_preserves_authoritative_case_and_previous_chunks(self) -> None:
        saved = self.save()["case"]
        namespace = projection_namespace_for_owner(self.owner_a)
        source_id = f"ksrc_case_{saved['case_id'].removeprefix('bcase_')}"
        before = "\n".join(
            item.text
            for item in self.service.knowledge_service.store.list_chunks(namespace, source_id=source_id)
        )
        self.service.knowledge_service.embedding_adapter = MissingEmbeddingAdapter()

        with self.assertRaisesRegex(ValueError, "case projection could not be indexed"):
            self.service.update_events(
                owner_key=self.owner_a,
                case_id=saved["case_id"],
                events=[
                    {
                        "category": "career",
                        "description": "不应发布的新事件",
                        "evidence_type": "user_reported",
                    }
                ],
            )

        current = self.service.get(owner_key=self.owner_a, case_id=saved["case_id"])["case"]
        after = "\n".join(
            item.text
            for item in self.service.knowledge_service.store.list_chunks(namespace, source_id=source_id)
        )
        self.assertEqual(current["case_version"], 1)
        self.assertEqual(before, after)
        self.assertNotIn("不应发布的新事件", after)

    def test_replacing_imported_case_persists_updated_snapshot_and_engine(self) -> None:
        candidate = {
            "gender": "male",
            "pillars": ["甲子", "丙寅", "戊辰", "庚申"],
            "dayun": ["丁卯"],
            "input_fingerprint": "sha256:" + "5" * 64,
            "raw_case_text": "extractor v3 source",
            "extraction_quality": {"extractor_version": "book.case.extractor.v3"},
        }
        saved = self.service.import_candidates(
            owner_key=self.owner_a, candidates=[candidate]
        )["cases"][0]
        replacement = {
            **candidate,
            "pillars": ["乙丑", "丁卯", "己巳", "辛未"],
            "dayun": ["戊辰", "己巳"],
            "raw_case_text": "extractor v4 source",
            "extraction_quality": {"extractor_version": "book.case.extractor.v4"},
        }

        result = self.service.import_candidates(
            owner_key=self.owner_a,
            candidates=[replacement],
            replace_existing=True,
        )
        current = self.service.store.get(self.owner_a, saved["case_id"])

        self.assertEqual(result["updated_count"], 1)
        self.assertEqual(current.case_version, 2)
        self.assertEqual(current.engine["version"], "3")
        self.assertEqual(current.chart_features["pillars"], replacement["pillars"])
        self.assertEqual(current.chart_snapshot["四柱"], replacement["pillars"])

    def test_projection_delete_exception_restores_active_case(self) -> None:
        saved = self.save()["case"]
        original_delete = self.service.knowledge_service.delete_source

        def fail_delete(**_kwargs: object) -> dict[str, object]:
            raise RuntimeError("knowledge unavailable")

        self.service.knowledge_service.delete_source = fail_delete
        try:
            with self.assertRaisesRegex(RuntimeError, "knowledge unavailable"):
                self.service.archive(owner_key=self.owner_a, case_id=saved["case_id"])
        finally:
            self.service.knowledge_service.delete_source = original_delete

        current = self.service.store.get(self.owner_a, saved["case_id"])
        self.assertEqual(current.status, "active_private")
        self.assertEqual(current.case_version, 1)


if __name__ == "__main__":
    unittest.main()
