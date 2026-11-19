import ast
import csv
import hashlib
import json
from pathlib import Path

from flatland.env_generation.env_generator import env_generator
from flatland.envs.persistence import RailEnvPersister


def main():
    root = Path(__file__).resolve().parents[2] / "datasets" / "flatland-core"
    target = root / "v3-holdout"
    target.mkdir(exist_ok=False)
    rows = list(csv.DictReader((root / "v2-audit/upstream_metadata.csv").open(encoding="utf-8")))
    selected = []
    for index in range(4):
        row = next(row for row in rows if row["test_id"] == "Test_00" and row["env_id"] == f"Level_{index}")
        keys = ["n_agents", "x_dim", "y_dim", "n_cities", "max_rail_pairs_in_city",
                "max_rails_between_cities", "malfunction_duration_min", "malfunction_duration_max",
                "malfunction_interval", "seed"]
        params = {key: int(row[key]) for key in keys}
        params["seed"] = 1042 + index
        params.update(grid_mode=row["grid_mode"] == "True", speed_ratios=ast.literal_eval(row["speed_ratios"]))
        name = f"Test_00_Level_{index}.pkl"
        selected.append({"file": name, "parameters": params})
    manifest = {"purpose": "unseen seeded variants of official configurations, not official serialized benchmark",
                "development": "v1 and v2-audit all ten scenarios",
                "protocol": "four fixed seeds 1042..1045; keep native faults; run all methods; no tuning after viewing",
                "selected": selected}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for row in selected:
        env, _, _ = env_generator(**row["parameters"])
        path = target / row["file"]
        RailEnvPersister.save(env, str(path))
        row["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
