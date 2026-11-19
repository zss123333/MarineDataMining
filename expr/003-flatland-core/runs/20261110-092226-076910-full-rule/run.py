import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import importlib.metadata
import json
from pathlib import Path
import time

from flatland.envs.persistence import RailEnvPersister
from coordination import Commitment, Coordinator, Ollama
from planning import action, candidates, collisions, predict


ROOT = Path(__file__).resolve().parents[1]


def aligned(commitment, now, horizon):
    if commitment.status != "active":
        return [None] * horizon
    return [commitment.path[stamp-commitment.start]
            if commitment.start <= stamp < min(commitment.expires, commitment.start+len(commitment.path)) else None
            for stamp in range(now, now+horizon)]


def register_dependencies(protocol, owner, plan, now):
    protocol.registered = [item for item in protocol.registered if item["consumer"] != owner]
    for provider, commitment in protocol.commitments.items():
        if provider == owner or commitment.status != "active":
            continue
        published = aligned(commitment, now, len(plan.cells))
        for offset, resource in enumerate(plan.cells):
            if resource is None or resource in published[offset:offset+1]:
                continue
            if resource in published[:offset]:
                protocol.register(owner, provider, resource, now+offset, now)
                break


def dependency_breaks(protocol, owner, proposal, now):
    broken = []
    for item in protocol.registered:
        if item["provider"] != owner or item["use_at"] < now:
            continue
        index = item["use_at"]-now
        if index < len(proposal.cells) and proposal.cells[index] == item["resource"]:
            broken.append(item)
    return broken


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="Test_00_Level_0.pkl")
    parser.add_argument("--method", choices=["independent", "fixed", "full", "current_only", "no_lookahead", "no_confirmation", "global_repair"], default="full")
    parser.add_argument("--backend", choices=["rule", "ollama"], default="rule")
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--max-llm-calls", type=int, default=20)
    args = parser.parse_args()
    if args.steps < 1 or args.max_llm_calls < 0:
        parser.error("invalid step or model budget")
    horizon = 32
    dataset = ROOT.parent / "datasets" / "flatland-core" / "v1" / args.scenario
    env, _ = RailEnvPersister.load_new(str(dataset))
    protocol = Coordinator(horizon)
    llm = Ollama() if args.backend == "ollama" else None
    output = ROOT / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + "-" + args.method + "-" + args.backend)
    output.mkdir(parents=True)
    for source in (ROOT / "src").glob("*.py"):
        (output / source.name).write_bytes(source.read_bytes())
    started = time.perf_counter()
    plans = {}
    retry = {}
    arrivals = {}
    total_reward = 0.0
    decisions = 0
    budget_fallbacks = 0
    rejected = 0
    repairs = 0
    native_faults = 0
    monitor_revocations = 0
    with (output / "trajectory.jsonl").open("w", encoding="utf-8") as trace:
        for now in range(min(args.steps, env._max_episode_steps)):
            protocol.expire(now)
            for owner, agent in enumerate(env.agents):
                commitment = protocol.commitments.get(owner)
                if agent.state.name == "DONE":
                    arrivals.setdefault(owner, now)
                    if commitment and commitment.status == "active":
                        commitment.status = "released"
                        protocol.invalidate_chain(owner, now)
                        protocol.messages.append({"type": "release", "owner": owner, "at": now})
                    continue
                if agent.malfunction_handler.malfunction_down_counter > 0:
                    if commitment and commitment.status == "active":
                        native_faults += 1
                        protocol.revoke(owner, now, "observed native malfunction")
                    continue
                if commitment and commitment.status == "active":
                    expected = aligned(commitment, now, 1)[0]
                    actual = tuple(agent.position) if agent.position is not None else None
                    if actual != expected:
                        monitor_revocations += 1
                        protocol.revoke(owner, now, "conditional trajectory assumption violated by observed state")
            for owner in sorted(range(len(env.agents)), key=lambda handle: ((handle-now//8) % len(env.agents))):
                agent = env.agents[owner]
                if agent.state.name == "DONE" or agent.malfunction_handler.malfunction_down_counter > 0:
                    continue
                old = protocol.commitments.get(owner)
                event = old is None or old.status != "active" or owner in protocol.repairs
                if not event or now < retry.get(owner, 0):
                    continue
                if owner in protocol.repairs:
                    repairs += 1
                protocol.repairs.discard(owner)
                options = candidates(env, agent, now, horizon, plans.get(owner))
                if not options:
                    protocol.revoke(owner, now, "no legal route")
                    continue
                peers = {peer: aligned(commitment, now, horizon) for peer, commitment in protocol.commitments.items()
                         if peer != owner and commitment.status == "active"}
                summaries = []
                for option in options:
                    hits = sum(len(collisions(option.cells, cells)) for cells in peers.values())
                    broken = dependency_breaks(protocol, owner, option, now)
                    if args.method == "current_only":
                        broken = [item for item in broken if item["use_at"] <= now]
                    summaries.append({"label": option.label, "wait": option.wait_until-now,
                                      "route_cells": len(option.route), "conflict_steps": hits,
                                      "broken_future_uses": broken})
                def score(index):
                    item = summaries[index]
                    penalty = 0 if args.method == "independent" else 30*item["conflict_steps"]
                    if args.method not in ["independent", "current_only"]:
                        penalty += 100*len(item["broken_future_uses"])
                    return item["wait"] + item["route_cells"] + penalty
                if args.method == "no_lookahead":
                    order = list(range(len(options)))
                else:
                    order = sorted(range(len(options)), key=score)
                if llm and len(llm.calls) < args.max_llm_calls:
                    selected = llm.choose(owner, summaries, {"step": now, "old_version": old.version if old else None,
                                         "dependent_future_uses": [item for item in protocol.registered if item["provider"] == owner and item["use_at"] >= now]})
                    order.remove(selected)
                    order.insert(0, selected)
                elif llm:
                    budget_fallbacks += 1
                decisions += 1
                accepted = False
                for selected in order:
                    option = options[selected]
                    if args.method == "fixed":
                        duration = 8
                    else:
                        first_conflict = min((offset for cells in peers.values() for offset in collisions(option.cells, cells)), default=horizon)
                        duration = max(4, min(horizon, first_conflict if first_conflict else 4))
                    if args.method in ["independent", "no_confirmation"]:
                        version = protocol.versions.get(owner, 0)+1
                        protocol.versions[owner] = version
                        protocol.commitments[owner] = Commitment(owner, version, now, now+duration, option.cells)
                        if args.method == "no_confirmation":
                            protocol.invalidate_chain(owner, now)
                    else:
                        required = protocol.propose(owner, option.cells, now, duration)
                        for peer in sorted(required):
                            if owner not in protocol.pending:
                                break
                            proposed = protocol.pending[owner][0]
                            peer_agent = env.agents[peer]
                            peer_plan = plans.get(peer)
                            peer_future = peers.get(peer, [])
                            if peer_plan:
                                peer_route = peer_plan.route
                                if peer_agent.position is not None:
                                    peer_state = (tuple(peer_agent.position), int(peer_agent.direction))
                                    if peer_state in peer_route:
                                        peer_route = peer_route[peer_route.index(peer_state):]
                                peer_future = predict(peer_agent, peer_route, now, max(now, peer_plan.wait_until), horizon)
                            hits = collisions(option.cells, peer_future)
                            protected = [item for item in dependency_breaks(protocol, owner, option, now) if item["consumer"] == peer]
                            if args.method == "current_only":
                                protected = [item for item in protected if item["use_at"] <= now]
                            accept = not hits and not protected
                            if llm and len(llm.calls) < args.max_llm_calls:
                                decision = llm.choose(peer, [{"decision": "accept", "conflict_steps": len(hits), "broken_uses": protected},
                                                            {"decision": "reject_request_alternative"}],
                                                      {"proposal_owner": owner, "version": proposed.version, "step": now})
                                accept = accept and decision == 0
                            protocol.messages.append({"type": "peer_evaluation", "peer": peer, "owner": owner,
                                                      "version": proposed.version, "at": now, "conflicts": hits,
                                                      "broken_uses": protected, "accept": accept})
                            protocol.acknowledge(owner, proposed.version, peer, now, accept)
                    current = protocol.commitments.get(owner)
                    if current and current.status == "active" and current.start == now and current.path == option.cells:
                        plans[owner] = option
                        if args.method != "independent":
                            register_dependencies(protocol, owner, option, now)
                        if args.method == "global_repair":
                            protocol.repairs.update(peer for peer in plans if peer != owner)
                        accepted = True
                        break
                    rejected += 1
                if not accepted:
                    retry[owner] = now+3
            actions = {}
            for owner, agent in enumerate(env.agents):
                if agent.state.name == "DONE":
                    continue
                commitment = protocol.commitments.get(owner)
                valid = commitment and commitment.status == "active" and owner in plans
                actions[owner] = action(agent, plans[owner], now) if valid and not agent.malfunction_handler.malfunction_down_counter else 4
            _, rewards, dones, _ = env.step(actions)
            total_reward += sum(float(value) for value in rewards.values())
            trace.write(json.dumps({"step": now, "actions": actions,
                        "positions": [agent.position for agent in env.agents],
                        "states": [agent.state.name for agent in env.agents]}, default=int)+"\n")
            if dones["__all__"]:
                break
    for owner, agent in enumerate(env.agents):
        if agent.state.name == "DONE":
            arrivals.setdefault(owner, now+1)
    summary = {"args": vars(args), "implementation": "dependency-contract-v2",
               "flatland": importlib.metadata.version("flatland-rl"),
               "scenario_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
               "agents": len(env.agents), "arrived": len(arrivals), "arrival_steps": arrivals,
               "steps": now+1, "reward": total_reward, "decisions": decisions,
               "messages": len(protocol.messages), "wall_seconds": time.perf_counter()-started,
               "llm_calls": len(llm.calls) if llm else 0, "budget_rule_fallbacks": budget_fallbacks,
               "rejected_candidates": rejected, "local_repairs": repairs,
               "native_fault_revocations": native_faults, "monitor_revocations": monitor_revocations,
               "future_registrations": sum(item["type"] == "dependency_register" and item["kind"] == "future" for item in protocol.messages),
               "interpretation": "paired evaluation needed; no safety or superiority guarantee"}
    for name, data in [("summary", summary), ("messages", protocol.messages), ("dependencies", protocol.registered),
                       ("plans", {owner: asdict(plan) for owner, plan in plans.items()}), ("llm", llm.calls if llm else [])]:
        (output / (name+".json")).write_text(json.dumps(data, indent=2, default=int), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    print(output, flush=True)


if __name__ == "__main__":
    main()
