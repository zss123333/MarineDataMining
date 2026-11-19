import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

spec = spec_from_file_location("rail_local_repair", Path(__file__).with_name("run.py"))
repair = module_from_spec(spec)
spec.loader.exec_module(repair)


class RepairTests(unittest.TestCase):
    def test_downstream_only_patch(self):
        plan = repair.SegmentedPlan({"0": {"resource": [0, 0], "enter": 0, "exit": 2},
                                     "1": {"resource": [0, 1], "enter": 2, "exit": 4}})
        patch = repair.local_response(plan, [{"shared": {"resource": [0, 1], "enter": 2, "exit": 6}}])
        self.assertEqual(set(patch.updates), {"1"})
        plan.apply(patch)
        self.assertEqual(plan.versions["0"], 0)
        self.assertEqual(plan.segments["1"]["enter"], 6)

    def test_no_conflict_no_patch(self):
        plan = repair.SegmentedPlan({"0": {"resource": [0, 0], "enter": 0, "exit": 2}})
        self.assertIsNone(repair.local_response(plan, []))


if __name__ == "__main__":
    unittest.main()
