from datetime import datetime
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--levels", type=int, default=3)
    parser.add_argument("--dataset-version", default="v1")
    parser.add_argument("--groups", choices=["all", "resource"], default="resource")
    parser.add_argument("--methods", nargs="+", default=["independent", "single", "menus_no_repair", "menus"])
    args = parser.parse_args()
    results = []
    for level in range(args.levels):
        for method in args.methods:
            command = [sys.executable, str(root / "src/run_flatland.py"), "--scenario",
                       f"Test_00_Level_{level}.pkl", "--method", method, "--steps", "1000",
                       "--dataset-version", args.dataset_version,
                       "--groups", "all" if method == "official_dla" else args.groups]
            environment = dict(os.environ, PYTHONIOENCODING="utf-8")
            completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                       env=environment, check=True)
            output = Path(completed.stdout.strip().splitlines()[-1])
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            results.append({"run": str(output.relative_to(root)), **summary})
            print(level, method, summary["arrived"], summary["capped_completion_steps"], flush=True)
    target = root / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-aligned-ablation.json")
    target.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(target, flush=True)


if __name__ == "__main__":
    main()
