import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from smoke import EXPERIMENT, episode, load_dataset, navigate, replay


class SmokeTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((EXPERIMENT / "configs/smoke.json").read_text())
        self.mdp, _ = load_dataset(self.config)

    def test_idle_and_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trajectory.jsonl"
            row = episode(self.mdp, "idle", 0, 5, path)
            self.assertEqual(row["sparse_reward"], 0)
            self.assertEqual(replay(self.mdp, path), 5)

    def test_script_delivers(self):
        with tempfile.TemporaryDirectory() as directory:
            row = episode(self.mdp, "scripted_delivery", 0, 200, Path(directory) / "trajectory.jsonl")
            self.assertGreaterEqual(row["deliveries"], 1)
            self.assertIn("plate_soup", row["macros"])

    def test_unreachable_target(self):
        with self.assertRaises(RuntimeError):
            navigate(self.mdp, self.mdp.get_standard_start_state(), 0, (999, 999))

    def test_dataset_cannot_escape(self):
        self.config["dataset"] = "../outside"
        with self.assertRaises(ValueError):
            load_dataset(self.config)


if __name__ == "__main__":
    unittest.main()
