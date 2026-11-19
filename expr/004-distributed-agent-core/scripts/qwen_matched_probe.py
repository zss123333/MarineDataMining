import json
from pathlib import Path
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root.parent / "003-flatland-core/src"))
    from coordination import Ollama
    runs = json.loads((root / "runs/qwen-holdout-pair.json").read_text(encoding="utf-8"))
    calls = json.loads((root / runs[0]["run"] / "llm.json").read_text(encoding="utf-8"))
    tasks = [json.loads(call["request"]["messages"][-1]["content"]) for call in calls[:3]]
    output = []
    for enabled in [False, True]:
        client = Ollama()
        for task in tasks:
            choice = client.choose(task["agent"], task["candidates"], task["context"])
            output.append({"framework_enabled": enabled, "task": task, "choice": choice,
                           "call": client.calls[-1]})
    (root / "runs/qwen-matched-probe.json").write_text(json.dumps(output, indent=2), encoding="utf-8")
    print("Identical local inputs and three calls per condition; not an end-to-end effect experiment")


if __name__ == "__main__":
    main()
