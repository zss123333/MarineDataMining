import unittest
from prepare import DATA, prepare
from task import MPCTask
from planning import routes
from flatland.envs.persistence import RailEnvPersister


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
        self.assertEqual(self.task.feedback_boundary(None, {"step": 5}), 10)

    def test_manifest_has_all_conditions(self):
        manifest = prepare()
        self.assertEqual(len(manifest["cases"]), 9)


if __name__ == "__main__":
    unittest.main()
