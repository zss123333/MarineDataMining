import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import time

from agent import Agent, Response
from demo import Mailbox
from flatland_task import FlatlandTask, ModelBudget
from planning import routes
from flatland.envs.persistence import RailEnvPersister


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="Test_00_Level_0.pkl")
    parser.add_argument("--dataset-version", default="v1")
    parser.add_argument("--method", choices=["independent", "single", "menus_no_repair", "menus"], default="menus")
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--backend", choices=["rule", "ollama"], default="rule")
    parser.add_argument("--max-llm-calls", type=int, default=6)
    parser.add_argument("--groups", choices=["all", "destination"], default="all")
    args = parser.parse_args()
    if args.steps < 1 or args.max_llm_calls < 0:
        parser.error("steps must be positive")
    root = Path(__file__).resolve().parents[1]
    source = root.parent / "datasets" / "flatland-core" / args.dataset_version / args.scenario
    env, _ = RailEnvPersister.load_new(str(source))
    members = tuple(str(handle) for handle in range(len(env.agents)))
    mailbox = Mailbox()
    model = ModelBudget(args.max_llm_calls) if args.backend == "ollama" else None
    destinations = {identity: tuple(env.agents[int(identity)].target) for identity in members}
    resources = {identity: {state[0] for path in routes(env, env.agents[int(identity)]) for state in path}
                 for identity in members} if args.groups == "destination" else {}
    groups = {identity: tuple(peer for peer in members if args.groups == "all" or destinations[peer] == destinations[identity])
              for identity in members}
    agents = [Agent(identity, members, FlatlandTask(env, int(identity), model=model, public_resources=resources),
                    mailbox, task_group=groups[identity]) for identity in members]
    for agent in agents:
        agent.task.menu_limit = 1 if args.method == "single" else 3
        agent.task.repair_weight = 0 if args.method == "menus_no_repair" else 1
    output = root / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S-%f")+"-flatland-distributed")
    output.mkdir(parents=True)
    for path in [root.parent.parent / "核心源码" / "agent.py", *Path(__file__).parent.glob("*.py")]:
        (output / ("core_agent.py" if path.parent.name == "核心源码" else path.name)).write_bytes(path.read_bytes())
    started = time.perf_counter()
    arrivals = {}
    reward = 0
    phases = 0
    with (output / "trajectory.jsonl").open("w", encoding="utf-8") as trace:
        for now in range(min(args.steps, env._max_episode_steps)):
            eligible = [agent for agent in agents if agent.task_group[now % len(agent.task_group)] == agent.identity
                        and agent.task.train.state.name != "DONE"]
            initiator = eligible[(now // max(1, len(members))) % len(eligible)].identity if eligible else None
            for agent in agents:
                agent.task.can_initiate = args.groups == "all" or agent.identity == initiator
                if args.method == "independent":
                    observation = agent.task.observe()
                    if agent.task.infeasible(observation):
                        agent.task.revoke(observation)
                    if not observation["done"] and not observation["fault"] and agent.task.needs_revision(observation):
                        options = agent.task.local_options(now)
                        if options:
                            plan = min(options, key=lambda item: agent.task.cost(item, now))
                            agent.task.install(Response(True, 0, {}, {"version": agent.task.version, "plan": plan}))
                else:
                    agent.step(now)
            for phase in range(200):
                batches = {agent.identity: mailbox.receive(agent.identity) for agent in agents}
                for agent in agents:
                    for message in batches[agent.identity]:
                        agent.think(message)
                phases += 1
                if not any(mailbox.queues.values()):
                    break
            else:
                raise RuntimeError("Negotiation failed to quiesce")
            actions = {int(agent.identity): agent.act() for agent in agents}
            _, rewards, dones, _ = env.step(actions)
            reward += sum(float(value) for value in rewards.values())
            for handle, train in enumerate(env.agents):
                if train.state.name == "DONE":
                    arrivals.setdefault(handle, now+1)
            trace.write(json.dumps({"step": now, "actions": actions,
                                    "positions": [train.position for train in env.agents]}, default=int)+"\n")
            if dones["__all__"]:
                break
    summary = {"args": vars(args), "agents": len(agents), "arrived": len(arrivals),
               "implementation": "response-menu-alignment-v1",
               "capped_completion_steps": sum(arrivals.get(handle, env._max_episode_steps) for handle in range(len(agents))),
               "unfinished_penalty": env._max_episode_steps,
               "message_bytes": sum(len(json.dumps(asdict(message), default=str).encode("utf-8")) for message in mailbox.messages),
               "arrival_steps": arrivals, "steps": now+1, "reward": reward,
               "messages": len(mailbox.messages), "communication_phases": phases,
               "installs": sum(agent.task.installs for agent in agents),
               "revocations": sum(agent.task.revocations for agent in agents),
               "repair_cost": sum(agent.task.repair_cost for agent in agents),
               "repair_installs": sum(agent.task.repair_installs for agent in agents),
               "committed_alternative_combinations": sum(
                   event.get("event") == "selected_combination" and event.get("uses_alternative", False)
                   and any(final.get("proposal") == event["proposal"] and final.get("decision") == "commit"
                           for final in agent.trace) for agent in agents for event in agent.trace),
               "combinations_checked": sum(event.get("checked", 0) for agent in agents for event in agent.trace),
               "alternative_combinations_found": sum(event.get("event") == "combination_found" and event.get("combinations_checked", 0) > 1
                                                     for agent in agents for event in agent.trace),
               "wall_seconds": time.perf_counter()-started,
               "scenario_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "backend": args.backend, "groups": groups,
               "llm_calls": len(model.client.calls) if model else 0,
               "budget_rule_fallbacks": model.fallbacks if model else 0,
               "input_tokens": sum(call["response"].get("prompt_eval_count", 0) for call in model.client.calls) if model else 0,
               "output_tokens": sum(call["response"].get("eval_count", 0) for call in model.client.calls) if model else 0,
               "scope": "destination delivery groups with publicly declared route resource dependencies" if resources else "single traffic group",
               "initiation": "one rotating eligible proposer per environment step; transport schedules no plans",
               "interpretation": "distributed core integration, not superiority evidence"}
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (output / "negotiation.json").write_text(json.dumps({agent.identity: agent.trace for agent in agents}, indent=2), encoding="utf-8")
    (output / "llm.json").write_text(json.dumps(model.client.calls if model else [], indent=2), encoding="utf-8")
    (output / "public_resources.json").write_text(json.dumps({peer: sorted(cells) for peer, cells in resources.items()}, default=int), encoding="utf-8")
    (output / "messages.json").write_text(json.dumps([asdict(message) for message in mailbox.messages], default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    print(output, flush=True)


if __name__ == "__main__":
    main()
