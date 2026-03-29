import unittest

from marten_runtime.domains.review.models import ReviewTarget
from marten_runtime.domains.review.repair_loop import RepairLoop
from marten_runtime.domains.review.service import ReviewService
from marten_runtime.domains.review.findings import make_blocking_finding
from marten_runtime.session.rehydration import ChildSessionHandoff


class ReviewRuntimeTests(unittest.TestCase):
    def test_review_service_marks_empty_diff_blocking(self) -> None:
        service = ReviewService()
        target = ReviewTarget(
            title="Review patch",
            run_id="run_coding_1",
            validation_run_id="run_validation_1",
            diff="",
            changed_files=[],
            handoff=ChildSessionHandoff(
                parent_session_id="sess_parent",
                active_goal="review patch",
                task_scope="review diff",
                recent_files=["tracked.txt"],
                open_todos=["check diff"],
                relevant_constraints=["child only"],
                bootstrap_manifest_id="boot_default",
                skill_snapshot_id="skill_default",
                tool_snapshot_id="tool_default",
                continuation_hint="review patch",
            ),
        )

        result = service.run(target)

        self.assertFalse(result.review_passed)
        self.assertTrue(result.review_run_id.startswith("run_review_"))
        self.assertTrue(result.findings[0].blocking)
        self.assertEqual(result.prompt_mode, "child")

    def test_review_service_rejects_non_child_handoff(self) -> None:
        service = ReviewService()
        target = ReviewTarget(
            title="Review patch",
            run_id="run_coding_1",
            validation_run_id="run_validation_1",
            diff="diff --git a/tracked.txt b/tracked.txt",
            changed_files=["tracked.txt"],
            handoff=ChildSessionHandoff(
                parent_session_id="sess_parent",
                active_goal="review patch",
                task_scope="review diff",
                recent_files=["tracked.txt"],
                open_todos=["check diff"],
                relevant_constraints=["child only"],
                bootstrap_manifest_id="boot_default",
                skill_snapshot_id="skill_default",
                tool_snapshot_id="tool_default",
                continuation_hint="review patch",
                prompt_mode="full",
            ),
        )

        result = service.run(target)

        self.assertFalse(result.review_passed)
        self.assertEqual(result.findings[0].title, "Invalid review handoff")

    def test_repair_loop_retries_blocking_findings_up_to_limit(self) -> None:
        service = ReviewService()
        loop = RepairLoop()
        target = ReviewTarget(
            title="Review patch",
            run_id="run_coding_1",
            validation_run_id="run_validation_1",
            diff="",
            changed_files=[],
            handoff=ChildSessionHandoff(
                parent_session_id="sess_parent",
                active_goal="review patch",
                task_scope="review diff",
                recent_files=["tracked.txt"],
                open_todos=["check diff"],
                relevant_constraints=["child only"],
                bootstrap_manifest_id="boot_default",
                skill_snapshot_id="skill_default",
                tool_snapshot_id="tool_default",
                continuation_hint="review patch",
            ),
        )
        result = service.run(target)
        finding = make_blocking_finding("Needs fix", "blocking issue")

        self.assertTrue(loop.should_retry(result, max_rounds=3, current_round=1))
        self.assertFalse(loop.should_retry(result, max_rounds=3, current_round=3))
        self.assertTrue(finding.blocking)


if __name__ == "__main__":
    unittest.main()
