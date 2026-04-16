import unittest

from marten_runtime.self_improve.review_child_contract import parse_review_child_result


class SelfImproveReviewContractTests(unittest.TestCase):
    def test_review_child_contract_parses_structured_json_payload(self) -> None:
        result = parse_review_child_result(
            """
            {
              "lesson_proposals": [
                {
                  "candidate_text": "Keep the path narrow.",
                  "rationale": "Repeated recovery pattern.",
                  "source_fingerprints": ["main|timeout"],
                  "score": 0.88
                }
              ],
              "skill_proposals": [],
              "nothing_to_save_reason": null,
              "confidence": 0.91,
              "classification_rationale": "Stable repeated workflow"
            }
            """
        )

        self.assertEqual(result.lesson_proposals[0].candidate_text, "Keep the path narrow.")
        self.assertEqual(result.confidence, 0.91)

    def test_review_child_contract_rejects_missing_json_object(self) -> None:
        with self.assertRaises(ValueError):
            parse_review_child_result("not-json")

    def test_review_child_contract_rejects_json_without_review_decision(self) -> None:
        with self.assertRaises(ValueError):
            parse_review_child_result("{}")

    def test_review_child_contract_allows_explicit_nothing_to_save_reason(self) -> None:
        result = parse_review_child_result(
            """
            {
              "lesson_proposals": [],
              "skill_proposals": [],
              "nothing_to_save_reason": "No reusable lesson in this run."
            }
            """
        )

        self.assertEqual(result.nothing_to_save_reason, "No reusable lesson in this run.")

    def test_review_child_contract_accepts_string_confidence_labels(self) -> None:
        result = parse_review_child_result(
            """
            {
              "lesson_proposals": [],
              "skill_proposals": [],
              "nothing_to_save_reason": "Simple one-off workflow.",
              "confidence": "high",
              "classification_rationale": "The evidence is clear but not reusable enough."
            }
            """
        )

        self.assertEqual(result.nothing_to_save_reason, "Simple one-off workflow.")
        self.assertEqual(result.confidence, 0.9)


if __name__ == "__main__":
    unittest.main()
