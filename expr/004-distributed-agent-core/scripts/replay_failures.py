import json
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))
    from flatland_task import FlatlandTask
    from flatland.envs.persistence import RailEnvPersister
    from planning import collisions
    rows = json.loads((root / "runs/20261110-151902-aligned-ablation.json").read_text(encoding="utf-8"))
    output = []
    for row in rows:
        if row["args"]["method"] != "menus" or row["args"]["scenario"] not in ["Test_00_Level_6.pkl", "Test_00_Level_8.pkl"]:
            continue
        env, _ = RailEnvPersister.load_new(str(root.parent / "datasets/flatland-core/v2-audit" / row["args"]["scenario"]))
        trajectory = [json.loads(line) for line in (root / row["run"] / "trajectory.jsonl").read_text(encoding="utf-8").splitlines()]
        for frame in trajectory[:-1]:
            env.step({int(key): value for key, value in frame["actions"].items()})
        replay_matches = [list(train.position) if train.position is not None else None for train in env.agents] == trajectory[-2]["positions"]
        tasks = [FlatlandTask(env, handle) for handle in range(len(env.agents))]
        options = {str(task.handle): task.local_options(env._elapsed_steps) for task in tasks if not task.observe()["done"]}
        pairs = []
        for owner, plans in options.items():
            for peer, alternatives in options.items():
                if owner < peer:
                    count = sum(not collisions(plan.cells, alternative.cells) for plan in plans for alternative in alternatives)
                    pairs.append({"members": [owner, peer], "compatible_candidate_pairs": count,
                                  "candidate_pairs": len(plans)*len(alternatives)})
        output.append({"scenario": row["args"]["scenario"], "replay_matches": replay_matches,
                       "step": env._elapsed_steps, "candidate_counts": {owner: len(plans) for owner, plans in options.items()},
                       "pairwise": pairs,
                       "scope": "recomputed candidates without installed old plan; pairwise feasibility is not joint feasibility"})
    (root / "runs/failure-replay.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
