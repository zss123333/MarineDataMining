import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import time

from prepare import DATA, ROOT, prepare
from task import MPCTask
from agent import Agent, Response
from demo import Mailbox
from planning import Plan, predict, routes
from flatland.envs.persistence import RailEnvPersister
from initialization import initialize
from flatland.envs.malfunction_generators import NoMalfunctionGen
from flatland.envs.malfunction_effects_generators import MalfunctionEffectsGenerator


def disable_native_malfunctions(env):
    env.malfunction_generator = NoMalfunctionGen()
    env.malfunction_process_data = env.malfunction_generator.get_process_data()
    env.effects_generator = MalfunctionEffectsGenerator(env.malfunction_generator)


def held_action(train):
    return 0 if train.position is None else 4


def occupancy_audit(frames):
    violations = 0
    previous = None
    for frame in frames:
        positions = frame["positions"]
        occupied = [tuple(position) for position in positions if position is not None]
        violations += len(occupied)-len(set(occupied))
        if previous is not None:
            for first in range(len(positions)):
                for second in range(first+1, len(positions)):
                    if (positions[first] is not None and positions[second] is not None
                            and positions[first] != positions[second]
                            and positions[first] == previous[second] and positions[second] == previous[first]):
                        violations += 1
        previous = positions
    return violations


def run(case, method, steps, output):
    env, _ = RailEnvPersister.load_new(str(DATA / case["scenario"]))
    original_limit = env._max_episode_steps
    env._max_episode_steps = steps
    disable_native_malfunctions(env)
    events = json.loads((DATA / case["events"]).read_text(encoding="utf-8"))
    paths = [routes(env, train, limit=1)[0] for train in env.agents]
    resources = {str(index): {state[0] for state in route} for index, route in enumerate(paths)}
    members = tuple(resources)
    mailbox = Mailbox()
    agents = [Agent(identity, members, MPCTask(env, int(identity), paths[int(identity)], events, method, resources),
                    mailbox, max_negotiation_rounds=3 if method == "feedback" else 1) for identity in members]
    initial_records, serial_budget = initialize(agents)
    initial = [record["departure"] for record in initial_records]
    arrivals = {}
    positions = []
    admission_violations = []
    started = time.perf_counter()
    for now in range(min(steps, env._max_episode_steps)):
        progress = {str(index): "done" if index in arrivals else "pending" for index in range(len(agents))}
        for member in agents:
            member.task.public_progress = progress
            observation = member.task.observe()
            if method != "fixed" and member.task.plan is None and not observation["fault"] and not observation["done"]:
                options = member.task.local_options(now)
                if options:
                    member.task.plan = options[0]
                    member.task.fallback_uses += 1
        if method != "fixed":
            for member in agents:
                member.step(now)
            for phase in range(200):
                batches = {member.identity: mailbox.receive(member.identity) for member in agents}
                for member in agents:
                    for message in batches[member.identity]:
                        member.think(message)
                if not any(mailbox.queues.values()):
                    break
            else:
                raise RuntimeError("Negotiation did not quiesce")
        actions = {}
        allowed = {}
        for member in agents:
            observation = member.task.observe()
            if method == "fixed":
                handle = int(member.identity)
                preceding_done = all(index in arrivals for index in range(handle))
                allowed[handle] = preceding_done and now >= member.task.plan.wait_until and not observation["fault"]
                if not preceding_done or observation["fault"]:
                    actions[handle] = held_action(member.task.train)
                else:
                    from planning import action
                    actions[handle] = action(member.task.train, member.task.plan, now)
            else:
                actions[int(member.identity)] = member.act()
            if member.task.train.position is None and (observation["fault"] or
                    member.task.plan is None or now < member.task.plan.wait_until):
                actions[int(member.identity)] = 0
        before = [train.position for train in env.agents]
        _, _, dones, _ = env.step(actions)
        if method == "fixed":
            for handle, train in enumerate(env.agents):
                if before[handle] is None and train.position is not None and not allowed[handle]:
                    admission_violations.append({"step": now, "agent": handle})
        for handle, train in enumerate(env.agents):
            if train.state.name == "DONE":
                arrivals.setdefault(handle, now+1)
        positions.append({"step": now, "positions": [train.position for train in env.agents], "actions": actions,
                          "admission_allowed": allowed,
                          "states": [train.state.name for train in env.agents],
                          "native_fault_counters": [train.malfunction_handler.malfunction_down_counter for train in env.agents]})
        if dones["__all__"]:
            break
    traces = [event for member in agents for event in member.trace]
    committed = {(member.identity, event["proposal"]) for member in agents for event in member.trace
                 if event.get("decision") == "commit"}
    selected = [(member.identity, event) for member in agents for event in member.trace
                if event.get("event") == "selected_combination"]
    result = {"method": method, "case": case, "agents": len(agents), "arrived": len(arrivals),
              "steps": now+1, "arrival_steps": arrivals, "initial_departures": initial,
              "original_episode_limit": original_limit, "experiment_episode_limit": steps,
              "initialization": initial_records, "serial_budget": serial_budget,
              "original_deadlines": [int(train.latest_arrival) for train in env.agents],
              "completion_penalty": sum(arrivals.get(index, env._max_episode_steps) for index in range(len(agents))),
              "penalty_per_unfinished": env._max_episode_steps,
              "messages": len(mailbox.messages), "message_bytes": sum(len(json.dumps(asdict(message), default=str).encode()) for message in mailbox.messages),
              "checks": sum(event.get("checked", 0) for event in traces),
              "commits": sum(event.get("decision") == "commit" for event in traces),
              "aborts": sum(event.get("decision") == "abort" for event in traces),
              "revocations": sum(member.task.revocations for member in agents),
              "observed_occupancy_violations": occupancy_audit(positions),
              "unauthorized_entries": admission_violations,
              "native_fault_samples": sum(counter > 0 for frame in positions for counter in frame["native_fault_counters"]),
              "proposals": sum(message.kind == "propose" and message.receiver == message.sender for message in mailbox.messages),
              "feedback_proposals": sum(message.kind == "propose" and message.receiver == message.sender
                                        and message.payload.attempt > 0 for message in mailbox.messages),
              "committed_alternatives": sum(event.get("uses_alternative", False) and (identity, event["proposal"]) in committed
                                            for identity, event in selected),
              "menu_exhausted": sum(event.get("reason") == "menu_exhausted" for event in traces),
              "budget_exhausted": sum(event.get("reason") == "budget_exhausted" for event in traces),
              "repair_installs": sum(member.task.repair_installs for member in agents),
              "execution_blocks": sum(event.get("event") == "execution_blocked" for event in traces),
              "fallback_uses": sum(member.task.fallback_uses for member in agents),
              "route_guard_waits": sum(member.task.guard_waits for member in agents),
              "implementation": "route-order-guard-v1",
              "distinct_proposers": len({message.sender for message in mailbox.messages if message.kind == "propose"}),
              "seconds": time.perf_counter()-started, "llm_calls": 0}
    output.mkdir()
    (output / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (output / "trajectory.json").write_text(json.dumps(positions, default=int), encoding="utf-8")
    (output / "negotiation.json").write_text(json.dumps({member.identity: member.trace for member in agents}), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--levels", type=int, default=3)
    parser.add_argument("--tiers", nargs="+", default=["low", "high"], choices=["none", "low", "high"])
    parser.add_argument("--methods", nargs="+", default=["fixed", "periodic", "single", "menus", "feedback"], choices=["fixed", "periodic", "single", "menus", "feedback"])
    args = parser.parse_args()
    if args.steps < 1 or not 1 <= args.levels <= 3:
        parser.error("steps must be positive and levels in 1..3")
    manifest = prepare()
    batch = ROOT / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    batch.mkdir(parents=True)
    core = ROOT.parent.parent / "核心源码/agent.py"
    for path in [core, *ROOT.glob("*.py")]:
        (batch / ("core_agent.py" if path == core else path.name)).write_bytes(path.read_bytes())
    (batch / "config.json").write_text(json.dumps({"args": vars(args), "core_sha256": hashlib.sha256(core.read_bytes()).hexdigest(), "status": "development"}, indent=2), encoding="utf-8")
    results = []
    for case in manifest["cases"][:args.levels*3]:
        if case["tier"] not in args.tiers:
            continue
        for method in args.methods:
            result = run(case, method, args.steps, batch / f"{Path(case['scenario']).stem}-{case['tier']}-{method}")
            results.append(result)
            (batch / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
            print(case["scenario"], case["tier"], method, result["arrived"], flush=True)
    print(batch, flush=True)


if __name__ == "__main__":
    main()
