import ast
import csv
import hashlib
import io
import json
from pathlib import Path
import urllib.request

from flatland.env_generation.env_generator import env_generator
from flatland.envs.persistence import RailEnvPersister


def main():
    root = Path(__file__).resolve().parents[2] / "datasets" / "flatland-core" / "v1"
    root.mkdir(parents=True, exist_ok=True)
    api = "https://api.github.com/repos/flatland-association/flatland-scenarios/commits/main"
    with urllib.request.urlopen(api, timeout=30) as response:
        commit = json.load(response)["sha"]
    base = f"https://raw.githubusercontent.com/flatland-association/flatland-scenarios/{commit}/"
    hashes = {}
    for name in ["scenarios/metadata.csv", "scenarios/gen_envs.py", "README.md"]:
        with urllib.request.urlopen(base + name, timeout=30) as response:
            data = response.read()
        target = root / ("upstream_" + Path(name).name)
        target.write_bytes(data)
        hashes[target.name] = hashlib.sha256(data).hexdigest()
    rows = list(csv.DictReader(io.StringIO((root / "upstream_metadata.csv").read_text(encoding="utf-8"))))
    selected = [row for row in rows if row["test_id"] == "Test_00"][:3]
    for row in selected:
        keys = ["n_agents", "x_dim", "y_dim", "n_cities", "max_rail_pairs_in_city",
                "max_rails_between_cities", "malfunction_duration_min", "malfunction_duration_max",
                "malfunction_interval", "seed"]
        params = {key: int(row[key]) for key in keys}
        params.update(grid_mode=row["grid_mode"] == "True", speed_ratios=ast.literal_eval(row["speed_ratios"]))
        env, _, _ = env_generator(**params)
        target = root / (row["test_id"] + "_" + row["env_id"] + ".pkl")
        RailEnvPersister.save(env, str(target))
        hashes[target.name] = hashlib.sha256(target.read_bytes()).hexdigest()
        print("prepared", target.name, flush=True)
    (root / "manifest.json").write_text(json.dumps({"upstream_commit": commit,
        "source": base, "flatland_version": "4.2.6", "kind": "regenerated official configurations, not original serialized benchmark",
        "selected": selected, "sha256": hashes}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
