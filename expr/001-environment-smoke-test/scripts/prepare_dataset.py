import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen


EXPERIMENT = Path(__file__).resolve().parents[1]
WORKSPACE = EXPERIMENT.parent
COMMIT = "739950a079cdaed5a44fcc662efc40244c205d06"


def prepare():
    destination = WORKSPACE / "datasets/overcooked-smoke/v1"
    if destination.exists():
        manifest_path = destination / "manifest.json"
        if not manifest_path.exists():
            raise RuntimeError("Incomplete dataset exists; inspect it before retrying")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for record in manifest["files"]:
            actual = hashlib.sha256((destination / record["path"]).read_bytes()).hexdigest()
            if actual != record["sha256"]:
                raise RuntimeError("Dataset checksum mismatch: " + record["path"])
        print("Existing dataset verified:", destination)
        return
    sources = {
        "raw/cramped_room.layout": "src/overcooked_ai_py/data/layouts/cramped_room.layout",
        "raw/UPSTREAM_LICENSE": "LICENSE",
    }
    payloads = {}
    for relative, upstream in sources.items():
        url = f"https://raw.githubusercontent.com/HumanCompatibleAI/overcooked_ai/{COMMIT}/{upstream}"
        with urlopen(url, timeout=60) as response:
            payloads[relative] = (response.read(), url)
    payloads["splits/smoke.json"] = (
        json.dumps({"purpose": "development_smoke_only", "layout": "cramped_room", "seeds": [0, 1, 2]}, indent=2).encode(),
        "generated fixed development configuration, not a held-out test split",
    )
    records = []
    for relative, (content, source) in payloads.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        records.append({"path": relative, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(), "source": source})
    manifest = {"name": "overcooked-smoke", "version": "v1", "upstream_commit": COMMIT, "created_utc": datetime.now(timezone.utc).isoformat(), "files": records}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Prepared:", destination)


if __name__ == "__main__":
    prepare()
