import hashlib
import json
from pathlib import Path
import random
import sys
import time
from dataclasses import asdict

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "004-distributed-agent-core" / "src"))
from agent import Agent, Candidate, Response
from demo import Mailbox


class World:
    def __init__(self, jobs):
        self.jobs = jobs
        self.now = 0
        self.completed = [0]*len(jobs)
        self.remaining = [0]*len(jobs)
        self.plans = [None]*len(jobs)
        self.version = [0]*len(jobs)
        self.wait = 0
        self.conflicts = 0

    def advance(self):
        active = {}
        for identity, plan in enumerate(self.plans):
            if plan and self.now >= plan[1] and self.completed[identity] < len(self.jobs[identity]):
                active.setdefault(plan[0], []).append(identity)
        for identities in active.values():
            if len(identities) > 1:
                self.conflicts += len(identities)
                continue
            identity = identities[0]
            if self.remaining[identity] == 0:
                self.remaining[identity] = self.jobs[identity][self.completed[identity]][1]
            self.remaining[identity] -= 1
            if self.remaining[identity] == 0:
                self.completed[identity] += 1
                self.plans[identity] = None
                self.version[identity] += 1
        progressed = sum(len(identities) == 1 for identities in active.values())
        self.wait += sum(done < len(self.jobs[index]) for index, done in enumerate(self.completed))-progressed
        self.now += 1


class ResourceTask:
    def __init__(self, world, identity, menu, feedback):
        self.world = world
        self.identity = identity
        self.menu = menu
        self.feedback = feedback

    def observe(self):
        return {"step": self.world.now, "version": self.world.version[self.identity]}

    def needs_revision(self, observation):
        return self.world.completed[self.identity] < len(self.world.jobs[self.identity]) and self.world.plans[self.identity] is None

    def own_options(self):
        world = self.world
        identity = self.identity
        if world.completed[identity] == len(world.jobs[identity]):
            return [None]
        current = world.plans[identity]
        if current and current[1] <= world.now:
            return [(current[0], world.now, world.now+(world.remaining[identity] or current[2]-current[1]))]
        resource, duration = world.jobs[identity][world.completed[identity]]
        return ([current] if current else []) + [(resource, world.now+offset, world.now+offset+duration) for offset in range(24-duration)]

    def candidates(self, observation):
        return tuple(Candidate(str(index), {"slot": plan}) for index, plan in enumerate(self.own_options()[:3]))

    def response(self, plan, observation):
        return Response(True, 0 if plan is None else plan[1]-self.world.now,
                        {"slot": plan}, {"version": observation["version"], "slot": plan})

    def respond(self, proposal, candidate, observation):
        if proposal.owner == str(self.identity):
            return self.response(candidate.public["slot"], observation)
        return self.response(self.own_options()[0], observation)

    def response_options(self, proposal, candidate, observation, primary):
        if proposal.owner == str(self.identity):
            return [primary]
        options = self.own_options()
        if proposal.constraints:
            occupied = proposal.constraints["occupied"]
            options = sorted(options, key=lambda plan: (sum(conflict(plan, other) for other in occupied),
                                                       0 if plan is None else plan[1]))
        return [self.response(plan, observation) for plan in options[:self.menu]]

    def compatible(self, candidate, reports):
        slots = [report["public"]["slot"] for report in reports.values()]
        return not any(conflict(first, second) for index, first in enumerate(slots) for second in slots[index+1:])

    def negotiation_constraints(self, proposal, reports, reason):
        if not self.feedback:
            return None
        return {"occupied": [reply[candidate.key]["options"][0]["public"]["slot"]
                              for candidate in proposal.candidates for reply in reports.values()]}

    def valid(self, response, observation):
        return response.private_plan["version"] == observation["version"]

    def install(self, response):
        self.world.plans[self.identity] = response.private_plan["slot"]
        self.world.version[self.identity] += 1

    def infeasible(self, observation):
        return False

    def revoke(self, observation):
        self.world.plans[self.identity] = None

    def dependency_changed(self, peer, observation):
        pass

    def act(self, observation):
        return None


def conflict(first, second):
    return first is not None and second is not None and first[0] == second[0] and max(first[1], second[1]) < min(first[2], second[2])


def run(jobs, method):
    world = World(jobs)
    mailbox = Mailbox()
    members = tuple(str(index) for index in range(len(jobs)))
    agents = [Agent(identity, members, ResourceTask(world, int(identity), 1 if method == "single" else 3,
                                                   method == "feedback"), mailbox) for identity in members]
    started = time.perf_counter()
    for step in range(320):
        if method == "independent":
            for member in agents:
                observation = member.task.observe()
                if member.task.needs_revision(observation):
                    member.task.install(member.task.response(member.task.own_options()[0], observation))
        else:
            for member in agents:
                member.step(step)
            for phase in range(100):
                for member in agents:
                    member.communicate()
                if not any(mailbox.queues.values()):
                    break
            else:
                raise RuntimeError("Negotiation did not quiesce")
            for member in agents:
                member.act()
        world.advance()
        if all(done == len(jobs[index]) for index, done in enumerate(world.completed)):
            break
    events = [event for member in agents for event in member.trace]
    return {"method": method, "completed": sum(world.completed), "total": sum(map(len, jobs)),
            "finished_agents": sum(done == len(jobs[index]) for index, done in enumerate(world.completed)),
            "steps": world.now, "conflict_steps": world.conflicts, "waiting_steps": world.wait,
            "messages": len(mailbox.messages), "bytes": sum(len(json.dumps(asdict(message)).encode()) for message in mailbox.messages),
            "checks": sum(event.get("checked", 0) for event in events),
            "commits": sum(event.get("decision") == "commit" for event in events),
            "aborts": sum(event.get("decision") == "abort" for event in events),
            "feedback_proposals": len({message.proposal for message in mailbox.messages if message.kind == "propose" and message.payload.attempt > 0}),
            "seconds": time.perf_counter()-started, "events": {member.identity: member.trace for member in agents}}


def main():
    dataset = ROOT.parent / "datasets" / "high-conflict-v1"
    dataset.mkdir(exist_ok=True)
    output = ROOT / "runs"
    output.mkdir(exist_ok=True)
    cases = []
    for count in [6, 10]:
        for seed in [17, 29, 43]:
            generator = random.Random(seed)
            cases.append({"agents": count, "seed": seed, "jobs": [[[generator.randrange(2 if count == 6 else 3), generator.randint(2, 4)] for job in range(12)] for identity in range(count)]})
    manifest = json.dumps(cases, indent=2)
    path = dataset / "manifest.json"
    if path.exists() and path.read_text(encoding="utf-8") != manifest:
        raise ValueError("Dataset manifest differs")
    path.write_text(manifest, encoding="utf-8")
    results = []
    for case in cases:
        for method in ["independent", "single", "menus", "feedback"]:
            result = run(case["jobs"], method)
            events = result.pop("events")
            result.update(agents=case["agents"], seed=case["seed"])
            (output / f"{case['agents']}-{case['seed']}-{method}-events.json").write_text(json.dumps(events), encoding="utf-8")
            results.append(result)
            (output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
            print(case["agents"], case["seed"], method, result["completed"], result["checks"], flush=True)
    core = ROOT.parent.parent / "核心源码" / "agent.py"
    (output / "core_agent.py").write_bytes(core.read_bytes())
    (output / "runner.py").write_bytes(Path(__file__).read_bytes())
    (output / "fingerprints.json").write_text(json.dumps({"core": hashlib.sha256(core.read_bytes()).hexdigest(), "dataset": hashlib.sha256(path.read_bytes()).hexdigest()}), encoding="utf-8")


if __name__ == "__main__":
    main()
