import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pilot import gate, validate_decision


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.old = {"id": "chef0-v1", "task": "dish", "expiry_step": 20}
        self.dependency = {"commitment_id": "chef0-v1", "type": "planned", "use_step": 15, "evidence": "future plate step"}

    def test_future_not_started_is_protected(self):
        self.assertEqual(gate("future_aware", "onion", self.old, [self.dependency], 5)[0], "dish")

    def test_current_only_ignores_future(self):
        self.assertEqual(gate("current_only", "onion", self.old, [self.dependency], 5)[0], "onion")

    def test_expired_not_frozen(self):
        self.assertEqual(gate("future_aware", "onion", self.old, [self.dependency], 21)[0], "onion")

    def test_bad_output_rejected(self):
        with self.assertRaises(ValueError):
            validate_decision({"task": "teleport", "future_plan": []}, 0, 200)


if __name__ == "__main__":
    unittest.main()
