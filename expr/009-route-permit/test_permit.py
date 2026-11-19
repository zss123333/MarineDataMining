import unittest
from importlib.util import spec_from_file_location, module_from_spec
from pathlib import Path

spec = spec_from_file_location("route_permit_experiment", Path(__file__).with_name("run.py"))
runner = module_from_spec(spec)
spec.loader.exec_module(runner)


class PermitTests(unittest.TestCase):
    def test_event_matches_fast_periodic_execution_with_less_communication(self):
        case = runner.prepare()["cases"][0]
        event, event_frames, _ = runner.execute(case, "event", 1000)
        periodic, periodic_frames, _ = runner.execute(case, "periodic1", 1000)
        self.assertEqual(event["arrived"], 7)
        self.assertEqual(event_frames, periodic_frames)
        self.assertLess(event["total_bytes"], periodic["total_bytes"])
        self.assertTrue(event["unchanged_other_tasks"])
        self.assertEqual(event["occupancy_violations"], 0)
        self.assertEqual(event["unauthorized_entries"], [])

    def test_active_neighbor_cannot_grant_permission(self):
        task = runner.PermitTask("0", ("0", "1", "2"),
                                 {"0": {(0, 0)}, "1": {(0, 0)}, "2": set()},
                                 {"0": "active", "1": "waiting", "2": "waiting"}, [0], 0)
        from agent import Proposal, Candidate
        response = task.respond(Proposal("test", "1", 0, (), ("0", "1")), Candidate("permit", {}), {})
        self.assertFalse(response.feasible)


if __name__ == "__main__":
    unittest.main()
