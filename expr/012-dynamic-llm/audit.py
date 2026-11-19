import json
from pathlib import Path
import sys


def audit(batch):
    rows = json.loads((batch / "results.json").read_text(encoding="utf-8"))
    checks = []
    for row in rows:
        assert row["completed"] == 3
        assert all(stage["valid"] and stage["committed"] for stage in row["stages"])
        assert row["unrelated_preserved"] and row["revocation_delivered"]
        assert all(len(step["workers"]) <= 1 for step in row["execution"])
        assert row["outsider_contacted"] == (not row["scoped"])
        if row["scoped"]:
            assert any(event.get("event") == "response_dependency_expansion"
                       for trace in row["trace"].values() for event in trace)
        checks.append({"seed": row["seed"], "scoped": row["scoped"], "passed": True})
    pairs = []
    for seed in sorted({row["seed"] for row in rows}):
        pair = [row for row in rows if row["seed"] == seed]
        assert len(pair) == 2
        pairs.append({"seed": seed, "same_execution": pair[0]["execution"] == pair[1]["execution"]})
    result = {"run_checks": checks, "paired_execution": pairs,
              "totals": {str(scoped): {key: sum(row[key] for row in rows if row["scoped"] == scoped)
                                        for key in ["completed", "llm_calls", "input_tokens", "output_tokens", "messages"]}
                         for scoped in [True, False]}}
    (batch / "audit.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    audit(Path(sys.argv[1]))
