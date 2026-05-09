import unittest

from marten_runtime.memory.intent import (
    MEMORY_DELETE_INTENT,
    MEMORY_INTENT_FIELD,
    MEMORY_WRITE_INTENT,
    has_explicit_memory_delete_intent,
    has_explicit_memory_write_intent,
    normalize_memory_intent_value,
)


class MemoryIntentTests(unittest.TestCase):
    def test_normalize_memory_intent_value(self) -> None:
        self.assertEqual(normalize_memory_intent_value(" durable_write "), MEMORY_WRITE_INTENT)
        self.assertEqual(normalize_memory_intent_value("DURABLE_DELETE"), MEMORY_DELETE_INTENT)
        self.assertEqual(normalize_memory_intent_value(None), "")

    def test_has_explicit_memory_write_intent_accepts_structured_payload(self) -> None:
        self.assertTrue(
            has_explicit_memory_write_intent(
                {"action": "append", MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT}
            )
        )
        self.assertTrue(
            has_explicit_memory_write_intent(
                {"action": "replace", MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT}
            )
        )

    def test_has_explicit_memory_delete_intent_accepts_structured_payload(self) -> None:
        self.assertTrue(
            has_explicit_memory_delete_intent(
                {"action": "delete", MEMORY_INTENT_FIELD: MEMORY_DELETE_INTENT}
            )
        )

    def test_memory_intent_helpers_reject_missing_or_mismatched_payload(self) -> None:
        self.assertFalse(has_explicit_memory_write_intent({"action": "append"}))
        self.assertFalse(
            has_explicit_memory_write_intent(
                {"action": "append", MEMORY_INTENT_FIELD: MEMORY_DELETE_INTENT}
            )
        )
        self.assertFalse(has_explicit_memory_delete_intent({"action": "delete"}))
        self.assertFalse(
            has_explicit_memory_delete_intent(
                {"action": "delete", MEMORY_INTENT_FIELD: MEMORY_WRITE_INTENT}
            )
        )


if __name__ == "__main__":
    unittest.main()
