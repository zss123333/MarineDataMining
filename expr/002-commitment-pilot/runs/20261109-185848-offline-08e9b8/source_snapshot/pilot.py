import argparse
import hashlib
import importlib.util
import json
import os
import random
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
SPEC = importlib.util.spec_from_file_location("smoke_common", WORKSPACE / "001-environment-smoke-test/src/smoke.py")
COMMON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COMMON)
Action = COMMON.Action
TASKS = {"onion", "start", "dish", "plate", "deliver", "wait"}


def describe(mdp, state):
    pots = []
    for position in mdp.get_pot_locations():
        soup = state.get_object(position) if state.has_object(position) else None
        pots.append({"position": position, "ingredients": len(soup.ingredients) if soup else 0, "cooking": bool(soup and soup.is_cooking), "ready": bool(soup and soup.is_ready)})
    return {"players": [{"position": player.position, "held": player.get_object().name if player.has_object() else None} for player in state.players], "pots": pots}


def macro_action(mdp, state, agent, task):
    player = state.players[agent]
    held = player.get_object().name if player.has_object() else None
    pot = mdp.get_pot_locations()[0]
    soup = state.get_object(pot) if state.has_object(pot) else None
    if task == "wait":
        return Action.STAY, "waiting"
    if task == "onion":
        if held not in (None, "onion"):
            return Action.STAY, "incompatible_inventory"
        if held == "onion" and soup and (soup.is_cooking or soup.is_ready or len(soup.ingredients) >= 3):
            return Action.STAY, "pot_unavailable"
        target = pot if held == "onion" else mdp.get_onion_dispenser_locations()[0]
    elif task == "start":
        if held or not soup or soup.is_cooking or soup.is_ready or len(soup.ingredients) < 3:
            return Action.STAY, "start_precondition_false"
        target = pot
    elif task == "dish":
        if held:
            return Action.STAY, "inventory_occupied"
        target = mdp.get_dish_dispenser_locations()[0]
    elif task == "plate":
        if held != "dish" or not soup or not soup.is_ready:
            return Action.STAY, "plate_precondition_false"
        target = pot
    elif task == "deliver":
        if held != "soup":
            return Action.STAY, "deliver_precondition_false"
        target = mdp.get_serving_locations()[0]
    else:
        raise ValueError("Unknown macro")
    try:
        action, _ = COMMON.navigate(mdp, state, agent, target)
        return action, "executable"
    except RuntimeError:
        return Action.STAY, "temporarily_unreachable"


def validate_decision(value, step, horizon):
    if not isinstance(value, dict) or value.get("task") not in TASKS:
        raise ValueError("Decision must contain a legal task")
    if not isinstance(value.get("future_plan"), list) or len(value["future_plan"]) > 4 or any(task not in TASKS for task in value["future_plan"]):
        raise ValueError("future_plan must contain at most four legal macros")
    dependencies = value.get("dependencies", [])
    if not isinstance(dependencies, list) or len(dependencies) > 4:
        raise ValueError("Invalid dependencies")
    for dependency in dependencies:
        if not isinstance(dependency, dict) or dependency.get("type") not in ("current", "planned", "predicted"):
            raise ValueError("Invalid dependency type")
        if not isinstance(dependency.get("commitment_id"), str) or not isinstance(dependency.get("evidence"), str):
            raise ValueError("Dependency requires commitment ID and evidence")
        window = dependency.get("use_step")
        if type(window) is not int or not step <= window <= horizon:
            raise ValueError("Invalid dependency use window")
    return value


def gate(method, proposed, previous, dependency_records, step):
    if previous is None or proposed == previous["task"] or previous["expiry_step"] <= step:
        return proposed, "no_active_change"
    if method == "fixed_commitment":
        return previous["task"], "fixed_term"
    relevant = [record for record in dependency_records if record["commitment_id"] == previous["id"] and record["use_step"] >= step]
    if method == "current_only":
        relevant = [record for record in relevant if record["type"] == "current"]
    if method in ("current_only", "future_aware") and relevant:
        return previous["task"], "dependency_protected"
    return proposed, "revision_allowed"


class ChatClient:
    def __init__(self, config, path):
        self.config = config
        self.path = path
        self.calls = 0
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0}
        self.usage_complete = True
        self.base = os.environ.get("EXPR_API_BASE", "").rstrip("/")
        self.model = os.environ.get("EXPR_MODEL", "")
        self.key = os.environ.get(os.environ.get("EXPR_API_KEY_ENV", "EXPR_API_KEY"), "")
        parsed = urlparse(self.base)
        if not self.key or not self.model or parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("Set explicit HTTPS EXPR_API_BASE, EXPR_MODEL and EXPR_API_KEY (or EXPR_API_KEY_ENV)")
        if parsed.query or parsed.fragment:
            raise ValueError("API base must not contain query or fragment")

    def decide(self, observation, method, step, agent):
        if self.calls >= self.config["max_calls"]:
            raise RuntimeError("Global request budget exhausted")
        instruction = (
            "You control one chef in cooperative Overcooked. Choose task from onion (fetch then deposit), "
            "start (empty hands start full pot), dish (fetch plate), plate (scoop ready soup with dish), deliver, wait. "
            "You may change task only at decision ticks. Actions cannot discard inventory. Use visible facts only. "
            "Output JSON only: {task, future_plan:[up to 4 task names], dependencies:[{commitment_id,type:current|planned|predicted,use_step:integer,evidence:string}]}. "
            "Dependency evidence must reference the teammate's published current commitment. Do not invent IDs. "
            "Plan ahead, avoid both chefs blocking each other. No hidden reasoning needed. "
        )
        instruction += {
            "independent": "Prioritize your own feasible progress; publishing plans does not restrict revisions.",
            "fixed_commitment": "Published tasks remain fixed for their validity term. Account for this constraint.",
            "current_only": "Evaluate teammate dependence on current actions. Only current dependencies constrain revisions.",
            "future_aware": "Evaluate present and future teammate needs. Consider their announced future plan and visible task progress, including not-yet-started steps. Distinguish explicit planned from uncertain predicted needs.",
        }[method]
        payload = {"model": self.model, "temperature": self.config["temperature"], "max_tokens": self.config["max_tokens_per_call"], "messages": [{"role": "system", "content": instruction}, {"role": "user", "content": json.dumps(observation)}]}
        request = Request(self.base + "/chat/completions", data=json.dumps(payload).encode(), headers={"Authorization": "Bearer " + self.key, "Content-Type": "application/json"})
        self.calls += 1
        started = time.perf_counter()
        record = {"call": self.calls, "method": method, "step": step, "agent": agent, "input": observation}
        try:
            with urlopen(request, timeout=self.config["timeout_seconds"]) as response:
                body = json.load(response)
            content = body["choices"][0]["message"]["content"]
            record["output"] = content
            record["usage"] = body.get("usage")
            usage = body.get("usage") or {}
            for name in self.usage:
                if name not in usage:
                    self.usage_complete = False
                self.usage[name] += usage.get(name, 0)
            value = validate_decision(json.loads(content), step, self.config["horizon"])
            record["status"] = "ok"
            return value
        except Exception as error:
            record["status"] = "error"
            record["error_type"] = type(error).__name__
            raise RuntimeError("Model call failed; inspect redacted call log") from None
        finally:
            record["seconds"] = time.perf_counter() - started
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def offline_decision(mdp, state, agent):
    player = state.players[agent]
    held = player.get_object().name if player.has_object() else None
    pot = mdp.get_pot_locations()[0]
    soup = state.get_object(pot) if state.has_object(pot) else None
    if held == "soup":
        task = "deliver"
    elif held == "dish":
        task = "plate" if soup and soup.is_ready else "wait"
    elif held == "onion":
        task = "onion"
    elif soup is None or (not soup.is_cooking and not soup.is_ready and len(soup.ingredients) < 3):
        task = "onion" if agent == 0 else "wait"
    elif not soup.is_cooking and not soup.is_ready:
        task = "start" if agent == 0 else "dish"
    else:
        task = "dish" if agent == 1 else "wait"
    return {"task": task, "future_plan": [], "dependencies": []}


def run_episode(mdp, config, method, seed, client, path):
    state = mdp.get_standard_start_state()
    commitments = [None, None]
    plans = [[], []]
    dependencies = [[], []]
    versions = [0, 0]
    reward = 0.0
    deliveries = 0
    blocked = 0
    protected = 0
    random.seed(seed)
    with path.open("w", encoding="utf-8") as stream:
        for step in range(config["horizon"]):
            decisions = []
            if step % config["decision_interval"] == 0:
                snapshot = json.loads(json.dumps({"state": describe(mdp, state), "commitments": commitments, "future_plans": plans, "dependency_records": dependencies}))
                # Both chefs decide from the same pre-decision snapshot.
                decisions = [client.decide({**snapshot, "agent_id": agent, "step": step, "horizon": config["horizon"]}, method, step, agent) if client else offline_decision(mdp, state, agent) for agent in range(2)]
                valid_ids = {item["id"] for item in commitments if item and item["expiry_step"] > step}
                for agent, decision in enumerate(decisions):
                    for record in decision["dependencies"]:
                        if record["commitment_id"] not in valid_ids or (commitments[agent] and record["commitment_id"] == commitments[agent]["id"]):
                            raise ValueError("Dependency references invalid/self commitment")
                dependencies = [decision["dependencies"] for decision in decisions]
                for agent, decision in enumerate(decisions):
                    task, reason = gate(method, decision["task"], commitments[agent], dependencies[1 - agent], step)
                    protected += int(reason == "dependency_protected")
                    decision["executed_task"] = task
                    decision["gate_reason"] = reason
                    previous = commitments[agent]
                    if previous is None or previous["task"] != task or previous["expiry_step"] <= step:
                        versions[agent] += 1
                        commitments[agent] = {"id": f"chef{agent}-v{versions[agent]}", "task": task, "expiry_step": step + config["commitment_steps"]}
                    plans[agent] = decision["future_plan"]
            actions = []
            statuses = []
            for agent in range(2):
                action, status = macro_action(mdp, state, agent, commitments[agent]["task"])
                actions.append(action)
                statuses.append(status)
                blocked += int(status not in ("executable", "waiting"))
            before = state.to_dict()
            state, info = mdp.get_state_transition(state, tuple(actions))
            gained = float(sum(info["sparse_reward_by_agent"]))
            delivered = sum(bool(value) for value in info["event_infos"].get("soup_delivery", []))
            reward += gained
            deliveries += delivered
            stream.write(json.dumps({"step": step, "before": before, "actions": actions, "after": state.to_dict(), "decisions": decisions, "commitments": commitments, "macro_status": statuses, "reward": gained, "deliveries": delivered}) + "\n")
    return {"method": method, "seed": seed, "reward": reward, "deliveries": deliveries, "blocked_macro_steps": blocked, "dependency_protections": protected, "steps": config["horizon"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["offline", "api"], required=True)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/pilot.json")
    parser.add_argument("--allow-paid", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.backend == "api" and not args.allow_paid:
        parser.error("Real calls require explicit --allow-paid and configured environment")
    if config["decision_interval"] <= 0 or config["horizon"] <= 0 or not config["seeds"]:
        raise ValueError("Invalid protocol")
    allowed_methods = {"independent", "fixed_commitment", "current_only", "future_aware"}
    if not config["methods"] or not set(config["methods"]).issubset(allowed_methods):
        raise ValueError("Unknown methods")
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + args.backend + "-" + uuid.uuid4().hex[:6]
    directory = ROOT / "runs" / run_id
    for name in ["logs", "trajectories", "metrics"]:
        (directory / name).mkdir(parents=True)
    COMMON.write_json(directory / "config.resolved.json", config)
    manifest = {"status": "running", "backend": args.backend, "purpose": "offline engineering validation only" if args.backend == "offline" else "LLM coordination pilot, not final confirmatory study", "started_utc": datetime.now(timezone.utc).isoformat()}
    try:
        mdp, dataset = COMMON.load_dataset(config)
        manifest["dataset_manifest"] = dataset
        for source in [ROOT / "src/pilot.py", Path(COMMON.__file__), args.config]:
            manifest.setdefault("source_sha256", {})[source.name] = hashlib.sha256(source.read_bytes()).hexdigest()
            target = directory / "source_snapshot" / source.name
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(source.read_bytes())
        client = ChatClient(config, directory / "logs/calls.jsonl") if args.backend == "api" else None
        if client:
            manifest.update({"model": client.model, "api_base": client.base})
        rows = []
        for seed in config["seeds"]:
            methods = list(config["methods"])
            random.Random(seed).shuffle(methods)
            for method in methods:
                row = run_episode(mdp, config, method, seed, client, directory / "trajectories" / f"{method}-{seed}.jsonl")
                rows.append(row)
                COMMON.write_json(directory / "metrics/episodes.json", rows)
        manifest["status"] = "completed"
        manifest["calls"] = client.calls if client else 0
        manifest["usage"] = client.usage if client else None
        manifest["usage_complete"] = client.usage_complete if client else False
        report = "# Pilot results\n\nBackend: " + args.backend + ". Offline results are NOT evidence of LLM method effectiveness.\n\n| Method | Seed | Deliveries | Reward | Blocked macro steps |\n| --- | --- | --- | --- | --- |\n"
        for row in rows:
            report += f"| {row['method']} | {row['seed']} | {row['deliveries']} | {row['reward']} | {row['blocked_macro_steps']} |\n"
        (directory / "report.md").write_text(report, encoding="utf-8")
    except Exception:
        manifest["status"] = "failed"
        (directory / "logs/error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
    finally:
        manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
        COMMON.write_json(directory / "run_manifest.json", manifest)
        print(directory)


if __name__ == "__main__":
    main()
