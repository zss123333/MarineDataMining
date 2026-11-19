import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "006-mpc-flatland"))
from prepare import prepare, DATA
from task import MPCTask
from agent import Agent, Candidate, Response, PlanPatch, SegmentedPlan
from demo import Mailbox
from planning import Plan, action, predict, routes
from flatland.envs.persistence import RailEnvPersister

spec = importlib.util.spec_from_file_location("permit_environment", ROOT.parent / "006-mpc-flatland/run.py")
environment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(environment)


class PermitTask:
    def __init__(self, identity, members, resources, status, clock, periodic):
        self.identity = identity
        self.members = members
        self.resources = resources
        self.status = status
        self.clock = clock
        self.periodic = periodic
        self.plan = SegmentedPlan({"permit": False, "other_work": {"untouched": True}})
        self.installs = 0
        self.evaluations = 0

    def peers(self):
        return tuple(peer for peer in self.members if peer == self.identity or
                     self.resources[self.identity] & self.resources[peer])

    def eligible(self):
        return all(self.status[peer] == "done" for peer in self.peers() if int(peer) < int(self.identity))

    def observe(self):
        return {"step": self.clock[0]}

    def needs_revision(self, observation):
        if self.periodic:
            return observation["step"] % self.periodic == 0 and self.status[self.identity] != "done"
        return self.status[self.identity] == "waiting" and self.eligible() and not self.plan.segments["permit"]

    def candidates(self, observation):
        return (Candidate("permit", {"owner": self.identity}),)

    def proposal_participants(self, candidates, observation):
        return self.peers()

    def respond(self, proposal, candidate, observation):
        self.evaluations += 1
        owner = proposal.owner
        safe = self.status[self.identity] != "active" or owner == self.identity
        if int(self.identity) < int(owner) and self.status[self.identity] != "done":
            safe = False
        updates = {"permit": True} if owner == self.identity else {"permit": self.plan.segments["permit"]}
        return Response(safe, 0, {"permission": safe},
                        PlanPatch({"permit": self.plan.versions["permit"]}, updates))

    def compatible(self, candidate, reports):
        return all(report["public"]["permission"] for report in reports.values())

    def valid(self, response, observation):
        return self.plan.valid(response.private_plan)

    def install(self, response):
        if response.private_plan.updates["permit"] != self.plan.segments["permit"]:
            self.plan.apply(response.private_plan)
            self.installs += 1

    def infeasible(self, observation):
        return False

    def act(self, observation):
        return self.plan.segments["permit"]


def execute(case, method, steps):
    env, _ = RailEnvPersister.load_new(str(DATA / case["scenario"]))
    env._max_episode_steps = steps
    environment.disable_native_malfunctions(env)
    events = json.loads((DATA / case["events"]).read_text(encoding="utf-8"))
    paths = [routes(env, train, limit=1)[0] for train in env.agents]
    members = tuple(str(index) for index in range(len(paths)))
    resources = {identity: {state[0] for state in paths[int(identity)]} for identity in members}
    status = dict.fromkeys(members, "waiting")
    clock = [0]
    mailbox = Mailbox()
    agents = [Agent(identity, members, PermitTask(identity, members, resources, status, clock,
                                                8 if method == "periodic" else 1 if method == "periodic1" else 0), mailbox)
              for identity in members]
    arrivals = {}
    frames = []
    public_messages = 0
    public_bytes = 0
    permissions = []
    max_active = 0
    start = time.perf_counter()
    for now in range(steps):
        clock[0] = now
        if method != "serial":
            for member in agents:
                member.step(now)
            for phase in range(200):
                for member in agents:
                    member.communicate()
                if not any(mailbox.queues.values()):
                    break
            else:
                raise RuntimeError("Protocol failed to quiesce")
        actions = {}
        authorized = {}
        for index, train in enumerate(env.agents):
            identity = str(index)
            paused = any(event["step"] <= now < event["step"]+event["duration"] and index in event["agents"] for event in events)
            permit = (all(str(peer) in status and status[str(peer)] == "done" for peer in range(index))
                      if method == "serial" else agents[index].task.plan.segments["permit"])
            authorized[index] = permit
            if identity in [str(handle) for handle in arrivals] or paused or not permit:
                actions[index] = environment.held_action(train)
            else:
                plan = Plan(paths[index], now, now, [], "route_permit")
                actions[index] = action(train, plan, now)
        before = [train.position for train in env.agents]
        _, _, dones, _ = env.step(actions)
        for index, train in enumerate(env.agents):
            identity = str(index)
            new = "done" if train.state.name == "DONE" else "active" if train.position is not None else "waiting"
            if new != status[identity]:
                record = {"owner": identity, "status": new, "step": now+1}
                public_messages += len(members)-1
                public_bytes += (len(members)-1)*len(json.dumps(record).encode())
                status[identity] = new
            if new == "done":
                arrivals.setdefault(index, now+1)
            if before[index] is None and train.position is not None and not authorized[index]:
                permissions.append({"step": now, "agent": index})
        max_active = max(max_active, sum(value == "active" for value in status.values()))
        frames.append({"step": now, "positions": [train.position for train in env.agents], "actions": actions})
        if dones["__all__"]:
            break
    protocol_bytes = sum(len(json.dumps(asdict(message), default=str).encode()) for message in mailbox.messages)
    traces = {member.identity: member.trace for member in agents}
    result = {"case": case, "method": method, "arrived": len(arrivals), "agents": len(members),
              "completion_penalty": sum(arrivals.get(index, steps) for index in range(len(members))),
              "steps": now+1, "arrival_steps": arrivals,
              "protocol_messages": len(mailbox.messages), "protocol_bytes": protocol_bytes,
              "status_messages": public_messages, "status_bytes": public_bytes,
              "total_bytes": protocol_bytes+public_bytes,
              "response_evaluations": sum(member.task.evaluations for member in agents),
              "proposals": sum(message.kind == "propose" and message.sender == message.receiver for message in mailbox.messages),
              "occupancy_violations": environment.occupancy_audit(frames), "unauthorized_entries": permissions,
              "unchanged_other_tasks": all(member.task.plan.versions["other_work"] == 0 for member in agents),
              "max_active": max_active, "wall_seconds": time.perf_counter()-start,
              "llm_calls": 0}
    return result, frames, traces


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--levels", type=int, default=3)
    parser.add_argument("--steps", type=int, default=1000)
    args = parser.parse_args()
    manifest = prepare()
    output = ROOT / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    output.mkdir(parents=True)
    core = ROOT.parent.parent / "核心源码/agent.py"
    (output / "core_agent.py").write_bytes(core.read_bytes())
    (output / "runner.py").write_bytes(Path(__file__).read_bytes())
    (output / "config.json").write_text(json.dumps({"args": vars(args), "core_sha256": hashlib.sha256(core.read_bytes()).hexdigest(),
                                                   "protocol": "development-fixed-order-whole-route-permits-v1"}, indent=2), encoding="utf-8")
    results = []
    for case in manifest["cases"][:args.levels*3]:
        for method in ["serial", "periodic", "periodic1", "event"]:
            result, frames, traces = execute(case, method, args.steps)
            results.append(result)
            name = f"{Path(case['scenario']).stem}-{case['tier']}-{method}"
            (output / (name+"-trajectory.json")).write_text(json.dumps(frames, default=int), encoding="utf-8")
            (output / (name+"-negotiation.json")).write_text(json.dumps(traces), encoding="utf-8")
            (output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
            print(name, result["arrived"], result["completion_penalty"], result["total_bytes"], flush=True)
    print(output, flush=True)


if __name__ == "__main__":
    main()
