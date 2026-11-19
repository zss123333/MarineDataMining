import unittest
from prepare import DATA, prepare
from task import MPCTask
from planning import routes
from flatland.envs.persistence import RailEnvPersister
import tempfile
import json
from pathlib import Path
from importlib.util import spec_from_file_location, module_from_spec

spec = spec_from_file_location("mpc_flatland_runner", Path(__file__).with_name("run.py"))
runner = module_from_spec(spec)
spec.loader.exec_module(runner)
run = runner.run
occupancy_audit = runner.occupancy_audit


class TaskTests(unittest.TestCase):
    def setUp(self):
        prepare()
        self.env, _ = RailEnvPersister.load_new(str(DATA / "Test_00_Level_0.pkl"))
        path = routes(self.env, self.env.agents[0], limit=1)[0]
        self.task = MPCTask(self.env, 0, path, [{"step": 10, "duration": 3, "agents": [0]}], "feedback", {"0": {state[0] for state in path}})

    def test_fixed_routes_only(self):
        options = self.task.local_options(0)
        self.assertTrue(options)
        self.assertTrue(all(option.route == self.task.fixed_route for option in options))

    def test_clock_indexed_disturbance(self):
        self.env._elapsed_steps = 10
        self.assertTrue(self.task.observe()["fault"])
        self.env._elapsed_steps = 13
        self.assertFalse(self.task.observe()["fault"])

    def test_feedback_boundary_stops_before_event(self):
        self.assertIsNone(self.task.feedback_boundary(None, {"step": 5}))

    def test_future_shared_route_dependency_blocks_admission(self):
        self.task.handle = 1
        self.task.public_resources = {"0": {(1, 1)}, "1": {(1, 1)}}
        self.assertEqual(self.task.blocking_peers(), ("0",))
        self.task.public_progress = {"0": "done"}
        self.assertEqual(self.task.blocking_peers(), ())

    def test_manifest_has_all_conditions(self):
        manifest = prepare()
        self.assertEqual(len(manifest["cases"]), 9)

    def test_serial_baseline_completes_with_explicit_experiment_limit(self):
        case = next(case for case in prepare()["cases"] if case["tier"] == "none")
        with tempfile.TemporaryDirectory() as directory:
            result = run(case, "fixed", 1000, Path(directory) / "run")
        self.assertEqual(result["arrived"], 7)
        self.assertEqual(result["observed_occupancy_violations"], 0)
        self.assertLess(result["original_episode_limit"], result["serial_budget"])
        self.assertEqual(result["experiment_episode_limit"], 1000)

    def test_occupancy_audit_detects_swap(self):
        self.assertEqual(occupancy_audit([{"positions": [[0, 0], [0, 1]]},
                                          {"positions": [[0, 1], [0, 0]]}]), 1)

    def test_hold_offmap_during_malfunction_recovery(self):
        from flatland.envs.step_utils.states import TrainState
        runner.disable_native_malfunctions(self.env)
        train = self.env.agents[6]
        self.env._elapsed_steps = int(train.earliest_departure)+1
        train.state_machine.set_state(TrainState.MALFUNCTION_OFF_MAP)
        self.env.step({index: runner.held_action(member) for index, member in enumerate(self.env.agents)})
        self.assertIsNone(train.position)

    def test_fixed_high_disturbance_has_no_unauthorized_entries(self):
        case = next(case for case in prepare()["cases"] if case["tier"] == "high" and "Level_1" in case["scenario"])
        with tempfile.TemporaryDirectory() as directory:
            result = run(case, "fixed", 1000, Path(directory) / "run")
        self.assertEqual(result["unauthorized_entries"], [])
        self.assertEqual(result["native_fault_samples"], 0)
        self.assertEqual(result["arrived"], 7)


if __name__ == "__main__":
    unittest.main()
