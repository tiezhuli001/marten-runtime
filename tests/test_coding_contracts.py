import unittest

from marten_runtime.domains.coding.models import CodingRequest


class CodingContractTests(unittest.TestCase):
    def test_coding_request_contract_freezes_minimum_fields(self) -> None:
        request = CodingRequest(
            title="Fix bug",
            body="repair the failing test",
            repo="/tmp/repo",
            acceptance=["pytest -q"],
            constraints=["do not change api"],
        )

        self.assertEqual(request.title, "Fix bug")
        self.assertEqual(request.acceptance, ["pytest -q"])
        self.assertEqual(request.constraints, ["do not change api"])


if __name__ == "__main__":
    unittest.main()
