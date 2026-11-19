import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import time

from agent import Agent
from demo import Mailbox
from flatland_task import FlatlandTask
from flatland.envs.persistence import RailEnvPersister


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="Test_00_Level_0.pkl")
    parser.add_argument("--steps", type=int, default=300)
    args = parser.parse_args()
    if args.steps < 1:
        parser.error("steps must be positive")
    root = Path(__file__).resolve().parents[1]
    source = root.parent / "datasets" / "flatland-core" / "v1" / args.scenario
    env, _ = RailEnvPersister.load_new(str(source))
    members = tuple(str(handle) for handle in range(len(env.agents)))
    mailbox = Mailbox()
    agents = [Agent(identity, members, FlatlandTask(env, int(identity)), mailbox) for identity in members]
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
            for agent in agents:
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
               "arrival_steps": arrivals, "steps": now+1, "reward": reward,
               "messages": len(mailbox.messages), "communication_phases": phases,
               "installs": sum(agent.task.installs for agent in agents),
               "revocations": sum(agent.task.revocations for agent in agents),
               "wall_seconds": time.perf_counter()-started,
               "scenario_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "backend": "local deterministic task response, no LLM",
               "scope": "one seven-train shared traffic task group",
               "interpretation": "distributed core integration, not superiority evidence"}
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (output / "messages.json").write_text(json.dumps([asdict(message) for message in mailbox.messages], default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    print(output, flush=True)


if __name__ == "__main__":
    main()
