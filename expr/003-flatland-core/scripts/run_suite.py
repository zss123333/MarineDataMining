import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ablations", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    methods = ["independent", "fixed", "full"]
    if args.ablations:
        methods += ["current_only", "no_lookahead", "no_confirmation", "global_repair"]
    results = []
    for level in range(3):
        for method in methods:
            command = [sys.executable, str(root / "src" / "run.py"), "--method", method,
                       "--scenario", f"Test_00_Level_{level}.pkl", "--steps", "300"]
            completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True)
            output = Path(completed.stdout.strip().splitlines()[-1])
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            results.append({"run": str(output.relative_to(root)), **summary})
            print(level, method, summary["arrived"], round(summary["wall_seconds"], 2), flush=True)
    target = root / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-paired-suite.json")
    target.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
