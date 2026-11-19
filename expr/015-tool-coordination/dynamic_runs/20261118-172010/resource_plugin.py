from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent.parent / "核心源码"))
from agent import Agent, Candidate, Response, PlanPatch, SegmentedPlan
from llm import OllamaDecisionModel
sys.path.insert(0, str(ROOT.parent / "004-distributed-agent-core/src"))
from demo import Mailbox, run_round


class ResourceTask:
    def __init__(self, identity, count, periodic, release):
        self.identity = identity
        self.count = count
        self.periodic = periodic
        self.release = release
        self.installs = 0
        self.executed = []
        self.plan = SegmentedPlan({"shared": None, "other": {"job": "preserve", "version": 7}})

    def observe(self):
        return {"version": self.plan.versions["shared"]}

    def needs_revision(self, observation):
        return self.identity == "0" and (self.periodic or not self.installs)

    def decision_context(self, stage, observation, **details):
        if stage == "revise":
            return {"task": "Request a shared-resource reservation for the group", "schema": {"request": "coordinate"},
                    "output_schema": {"type": "object", "properties": {"request": {"type": "string", "enum": ["coordinate"]}}, "required": ["request"]}}
        proposal = details["proposal"]
        reports = (proposal.constraints or {}).get("slots", {})
        forbidden = sorted({slot for peer, slot in reports.items() if int(peer) < int(self.identity)})
        previous = reports.get(self.identity, self.plan.segments["shared"])
        allowed = [slot for slot in range(self.release, self.release+self.count+4) if slot not in forbidden]
        if previous in allowed:
            allowed = [previous]
        return {"task": "Propose your own integer time slot for one unit of work on a capacity-one shared resource. Keep previous_own_slot when it is an integer and remains valid; otherwise choose the smallest valid slot. Do not plan for other agents.",
                "release": self.release, "latest": self.release+self.count+3,
                "forbidden_slots": forbidden, "previous_own_slot": previous,
                "coordination_feedback": proposal.constraints, "validation_errors": details["errors"],
                "schema": {"slot": "integer between release and latest, not forbidden"},
                "output_schema": {"type": "object", "properties": {"slot": {"type": "integer", "enum": allowed}}, "required": ["slot"]}}

    def candidates_from_decision(self, decision, observation):
        if decision.get("request") != "coordinate":
            raise ValueError("Model must request coordination")
        return (Candidate("reservation", {"capacity": 1}),)

    def response_from_decision(self, decision, proposal, candidate, observation):
        slot = decision["slot"]
        if type(slot) is not int or not self.release <= slot <= self.release+self.count+3:
            raise ValueError("Slot outside the permitted integer range")
        reports = (proposal.constraints or {}).get("slots", {})
        if slot in {value for peer, value in reports.items() if int(peer) < int(self.identity)}:
            raise ValueError("Slot conflicts with the published higher-priority reservation")
        return Response(True, slot-self.release, {"slot": slot},
                        PlanPatch({"shared": observation["version"]}, {"shared": slot}))

    def negotiation_constraints(self, proposal, reports, reason):
        return {"reason": reason, "slots": {peer: values["reservation"]["public"]["slot"]
                                             for peer, values in reports.items()},
                "rule": "Keep lower numeric identities' announced slots clear; choose your own slot again"}

    def compatible(self, candidate, reports):
        slots = [report["public"]["slot"] for report in reports.values()]
        return len(set(slots)) == len(slots)

    def valid(self, response, observation):
        return self.plan.valid(response.private_plan)

    def install(self, response):
        self.plan.apply(response.private_plan)
        self.installs += 1

    def infeasible(self, observation):
        return False

    def act(self, observation):
        return self.plan.segments["shared"]


def execute(count, periodic, release, target=None):
    model = OllamaDecisionModel()
    mailbox = Mailbox()
    members = tuple(str(index) for index in range(count))
    tasks = [ResourceTask(identity, count, periodic, release) for identity in members]
    agents = [Agent(identity, members, task, mailbox, max_negotiation_rounds=8,
                    decision_model=model) for identity, task in zip(members, tasks)]
    trajectories = []
    for round_index in range(count*2+1):
        try:
            actions = run_round(agents, mailbox, round_index)
        finally:
            if target is not None:
                (target / f"calls-{count}-{periodic}.json").write_text(json.dumps(model.calls, ensure_ascii=False, indent=2), encoding="utf-8")
        trajectories.append(actions)
        print("progress", count, periodic, round_index, len(model.calls), actions, flush=True)
    slots = [task.plan.segments["shared"] for task in tasks]
    valid = all(type(slot) is int for slot in slots) and len(set(slots)) == count
    execution = []
    for now in range(release+count+4):
        active = [task.identity for task in tasks if task.plan.segments["shared"] == now]
        if len(active) > 1:
            raise RuntimeError("Execution capacity violation")
        execution.append({"time": now, "workers": active})
    return {"agents": count, "periodic": periodic, "release": release,
            "completed": sum(len(row["workers"]) for row in execution), "valid": valid,
            "selected_slots": slots, "waiting_cost": sum(slot-release for slot in slots) if valid else None,
            "execution": execution, "messages": len(mailbox.messages),
            "message_bytes": sum(len(json.dumps(vars(message), default=lambda value: vars(value), ensure_ascii=False).encode("utf-8")) for message in mailbox.messages),
            "llm_calls": len(model.calls), "input_tokens": sum(call["response"].get("prompt_eval_count", 0) for call in model.calls),
            "output_tokens": sum(call["response"].get("eval_count", 0) for call in model.calls),
            "model_seconds": sum(call["seconds"] for call in model.calls), "rule_fallbacks": 0,
            "unrelated_preserved": all(task.plan.segments["other"] == {"job": "preserve", "version": 7}
                                       and task.plan.versions["other"] == 0 for task in tasks),
            "trace": {agent.identity: agent.trace for agent in agents}, "calls": model.calls}


def main():
    target = ROOT / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target.mkdir(parents=True)
    for name in ["agent.py", "llm.py"]:
        (target / name).write_bytes((ROOT.parent.parent / "核心源码" / name).read_bytes())
    (target / "runner.py").write_bytes(Path(__file__).read_bytes())
    results = []
    for count, release in [(3, 0), (4, 2)]:
        for periodic in [False, True]:
            try:
                row = execute(count, periodic, release, target)
                results.append(row)
            except Exception as error:
                (target / "error.txt").write_text(repr(error), encoding="utf-8")
                raise
            (target / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(target, flush=True)


if __name__ == "__main__":
    main()
