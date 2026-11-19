import hashlib
import json
from pathlib import Path
import random
import shutil

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parent / "datasets/mpc-flatland-v1"


def prepare():
    DATA.mkdir(exist_ok=True)
    cases = []
    for level in range(3):
        source = ROOT.parent / f"datasets/flatland-core/v3-holdout/Test_00_Level_{level}.pkl"
        target = DATA / source.name
        if not target.exists():
            shutil.copyfile(source, target)
        if target.read_bytes() != source.read_bytes():
            raise ValueError("Scenario fingerprint mismatch")
        for tier, interval, duration in [("none", 40, 0), ("low", 40, 3), ("high", 20, 8)]:
            generator = random.Random(901+level)
            events = [{"step": step, "agents": generator.sample(list(range(7)), 2), "duration": duration}
                      for step in range(interval, 1000, interval)] if duration else []
            event_file = f"level{level}-{tier}-events.json"
            encoded = json.dumps(events, indent=2)
            path = DATA / event_file
            if path.exists() and path.read_text(encoding="utf-8") != encoded:
                raise ValueError("Event table mismatch")
            path.write_text(encoded, encoding="utf-8")
            cases.append({"scenario": target.name, "tier": tier, "events": event_file,
                          "scenario_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                          "events_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = {"status": "development; reused previously observed seeded configurations, not unseen holdout",
                "source": "../flatland-core/v3-holdout/manifest.json", "cases": cases,
                "disturbance": "fixed clock-indexed action-STOP commands; native malfunctions disabled"}
    (DATA / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(json.dumps(prepare(), indent=2))
