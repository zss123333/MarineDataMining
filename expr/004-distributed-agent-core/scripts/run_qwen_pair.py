import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    results = []
    for method in ["independent", "menus"]:
        command = [sys.executable, str(root / "src/run_flatland.py"), "--dataset-version", "v3-holdout",
                   "--scenario", "Test_00_Level_0.pkl", "--method", method, "--steps", "1000",
                   "--groups", "resource", "--backend", "ollama", "--max-llm-calls", "6"]
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                   env=dict(os.environ, PYTHONIOENCODING="utf-8"), check=True)
        output = Path(completed.stdout.strip().splitlines()[-1])
        results.append({"run": str(output.relative_to(root)),
                        **json.loads((output / "summary.json").read_text(encoding="utf-8"))})
        print(method, results[-1]["arrived"], results[-1]["llm_calls"], flush=True)
        (root / "runs/qwen-holdout-pair.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
