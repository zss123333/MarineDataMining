import argparse
import ast
import hashlib
import importlib.metadata
import json
import platform
import random
import subprocess
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from overcooked_ai_py.mdp.actions import Action, Direction
from overcooked_ai_py.mdp.overcooked_mdp import OvercookedGridworld


EXPERIMENT = Path(__file__).resolve().parents[1]
WORKSPACE = EXPERIMENT.parent


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def load_dataset(config):
    directory = (WORKSPACE / config["dataset"]).resolve()
    if not directory.is_relative_to((WORKSPACE / "datasets").resolve()):
        raise ValueError("Dataset must be inside expr/datasets")
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest["upstream_commit"] != config["upstream_commit"]:
        raise ValueError("Upstream version mismatch")
    for record in manifest["files"]:
        path = (directory / record["path"]).resolve()
        if not path.is_relative_to(directory):
            raise ValueError("Invalid manifest path")
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("Dataset checksum mismatch")
    split = json.loads((directory / "splits/smoke.json").read_text(encoding="utf-8"))
    if split["layout"] != config["layout"] or split["seeds"] != config["seeds"]:
        raise ValueError("Config differs from frozen smoke split")
    layout = ast.literal_eval((directory / "raw" / (config["layout"] + ".layout")).read_text())
    grid = [row.strip() for row in layout.pop("grid").splitlines()]
    return OvercookedGridworld.from_grid(grid, layout), manifest


def navigate(mdp, state, agent, target):
    player = state.players[agent]
    blocked = state.players[1 - agent].position
    floors = set(mdp.get_valid_player_positions()) - {blocked}
    initial = (player.position, player.orientation)
    queue = deque([(initial, [])])
    visited = {initial}
    while queue:
        (position, orientation), path = queue.popleft()
        facing = (position[0] + orientation[0], position[1] + orientation[1])
        if facing == tuple(target):
            return (path[0] if path else Action.INTERACT), len(path)
        for direction in Direction.ALL_DIRECTIONS:
            neighbor = (position[0] + direction[0], position[1] + direction[1])
            next_position = neighbor if neighbor in floors else position
            candidate = (next_position, direction)
            if candidate not in visited:
                visited.add(candidate)
                queue.append((candidate, path + [direction]))
    raise RuntimeError(f"Unreachable macro target: agent={agent}, target={target}")


def scripted_action(mdp, state):
    player = state.players[0]
    held = player.get_object().name if player.has_object() else None
    pot = mdp.get_pot_locations()[0]
    soup = state.get_object(pot) if state.has_object(pot) else None
    if held == "onion":
        macro, target = "deposit_onion", pot
    elif held == "soup":
        macro, target = "deliver_soup", mdp.get_serving_locations()[0]
    elif held == "dish":
        if soup is not None and soup.is_ready:
            macro, target = "plate_soup", pot
        else:
            return Action.STAY, "wait_cooking"
    elif soup is None or (not soup.is_cooking and not soup.is_ready and len(soup.ingredients) < 3):
        macro, target = "fetch_onion", mdp.get_onion_dispenser_locations()[0]
    elif not soup.is_cooking and not soup.is_ready:
        macro, target = "start_cooking", pot
    else:
        macro, target = "fetch_dish", mdp.get_dish_dispenser_locations()[0]
    action, _ = navigate(mdp, state, 0, target)
    return action, macro


def episode(mdp, method, seed, horizon, path):
    random.seed(seed)
    np.random.seed(seed)
    state = mdp.get_standard_start_state()
    total_reward = 0.0
    deliveries = 0
    stationary_steps = 0
    macros = set()
    with path.open("w", encoding="utf-8") as stream:
        for step in range(horizon):
            before = state.to_dict()
            action, macro = (Action.STAY, "idle") if method == "idle" else scripted_action(mdp, state)
            joint = (action, Action.STAY)
            state, info = mdp.get_state_transition(state, joint)
            reward = float(sum(info["sparse_reward_by_agent"]))
            delivered = sum(bool(value) for value in info["event_infos"].get("soup_delivery", []))
            total_reward += reward
            deliveries += delivered
            stationary_steps += int(state.player_positions == tuple(tuple(player["position"]) for player in before["players"]))
            macros.add(macro)
            assert len(set(state.player_positions)) == 2
            assert all(position in mdp.get_valid_player_positions() for position in state.player_positions)
            stream.write(json.dumps({"step": step, "state_before": before, "joint_action": joint, "macro": macro, "state_after": state.to_dict(), "reward": reward, "deliveries": delivered}, ensure_ascii=False) + "\n")
    return {"method": method, "seed": seed, "steps": horizon, "sparse_reward": total_reward, "deliveries": deliveries, "stationary_joint_steps": stationary_steps, "macros": sorted(macros), "llm_calls": 0, "llm_tokens": 0}


def replay(mdp, path):
    state = mdp.get_standard_start_state()
    count = 0
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            assert json.loads(json.dumps(state.to_dict())) == record["state_before"]
            actions = tuple(tuple(action) if isinstance(action, list) else action for action in record["joint_action"])
            state, info = mdp.get_state_transition(state, actions)
            assert json.loads(json.dumps(state.to_dict())) == record["state_after"]
            assert float(sum(info["sparse_reward_by_agent"])) == record["reward"]
            count += 1
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=EXPERIMENT / "configs/smoke.json")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if config["horizon"] <= 0 or not config["seeds"] or set(config["methods"]) != {"idle", "scripted_delivery"}:
        raise ValueError("Invalid smoke configuration")
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-smoke-" + uuid.uuid4().hex[:6]
    directory = EXPERIMENT / "runs" / run_id
    (directory / "trajectories").mkdir(parents=True)
    (directory / "logs").mkdir()
    write_json(directory / "config.resolved.json", config)
    manifest = {"run_id": run_id, "status": "running", "started_utc": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(), "packages": {name: importlib.metadata.version(name) for name in ["numpy", "gymnasium", "overcooked_ai", "cloudpickle", "farama-notifications", "typing_extensions"]}, "command": __import__("sys").argv, "purpose": "environment smoke, not LLM effectiveness", "compatibility_deviation": "Minimal MDP tested on Python 3.13 and NumPy 2; upstream declares Python 3.10 and NumPy <2"}
    write_json(directory / "run_manifest.json", manifest)
    started = time.perf_counter()
    try:
        manifest["git_commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=EXPERIMENT, text=True).strip()
        manifest["git_status"] = subprocess.check_output(["git", "status", "--porcelain", "--", "."], cwd=EXPERIMENT, text=True, encoding="utf-8").strip()
        snapshot = directory / "source_snapshot"
        for relative in ["src/smoke.py", "scripts/prepare_dataset.py", "tests/test_smoke.py", "requirements.txt"]:
            target = snapshot / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((EXPERIMENT / relative).read_bytes())
        source = importlib.metadata.distribution("overcooked_ai").read_text("direct_url.json")
        manifest["upstream_install"] = json.loads(source) if source else None
        installed_commit = (manifest["upstream_install"] or {}).get("vcs_info", {}).get("commit_id")
        installed_url = (manifest["upstream_install"] or {}).get("url", "")
        archive_url = "https://codeload.github.com/HumanCompatibleAI/overcooked_ai/zip/" + config["upstream_commit"]
        if installed_commit != config["upstream_commit"] and installed_url != archive_url:
            raise RuntimeError("Install the exact pinned upstream commit or archive")
        mdp, dataset = load_dataset(config)
        manifest["dataset_manifest"] = dataset
        rows = []
        for method in config["methods"]:
            for seed in config["seeds"]:
                path = directory / "trajectories" / f"{method}-seed{seed}.jsonl"
                row = episode(mdp, method, seed, config["horizon"], path)
                row["replayed_steps"] = replay(mdp, path)
                rows.append(row)
        write_json(directory / "metrics/episodes.json", rows)
        checks = {"idle_zero_reward": all(row["sparse_reward"] == 0 for row in rows if row["method"] == "idle"), "script_delivers": all(row["deliveries"] >= 1 for row in rows if row["method"] == "scripted_delivery"), "replay_exact": all(row["replayed_steps"] == config["horizon"] for row in rows)}
        write_json(directory / "metrics/checks.json", checks)
        if not all(checks.values()):
            raise RuntimeError("Smoke acceptance checks failed")
        report = "# Environment smoke result\n\nNot a multi-agent method comparison. One scripted chef, one stationary chef.\n\n| Method | Seed | Deliveries | Reward | Replayed steps |\n| --- | --- | --- | --- | --- |\n"
        for row in rows:
            report += f"| {row['method']} | {row['seed']} | {row['deliveries']} | {row['sparse_reward']} | {row['replayed_steps']} |\n"
        report += "\nSeeds do not create independent variation here: fixed initial state, deterministic policy and dynamics. No statistical significance or LLM coordination claim.\n"
        (directory / "report.md").write_text(report, encoding="utf-8")
        manifest["status"] = "completed"
        print(directory)
    except Exception:
        import traceback
        (directory / "logs/error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        manifest["status"] = "failed"
        raise
    finally:
        manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
        manifest["wall_seconds"] = time.perf_counter() - started
        write_json(directory / "run_manifest.json", manifest)


if __name__ == "__main__":
    main()
