from datetime import datetime
import importlib.util
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("resource_experiment", ROOT.parent / "011-llm-coordination/run.py")
resource = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resource)
Agent, Mailbox, run_round = resource.Agent, resource.Mailbox, resource.run_round


class DynamicTask(resource.ResourceTask):
    def __init__(self, identity, count, release, scoped):
        super().__init__(identity, count, False, release)
        self.scoped = scoped
        self.required_installs = 1
        self.notifications = []

    def needs_revision(self, observation):
        return self.identity == "0" and self.installs < self.required_installs

    def proposal_participants(self, candidates, observation):
        return ("0",) if self.scoped else tuple(str(index) for index in range(self.count+1))

    def response_dependencies(self, proposal, candidate, response, observation):
        following = int(self.identity)+1
        return (str(following),) if following < self.count else ()

    def coordination_peers(self, proposal, observation):
        if not self.scoped:
            return tuple(str(index) for index in range(self.count+1))
        if proposal is None:
            return tuple(str(index) for index in range(self.count))
        return ()

    def response_from_decision(self, decision, proposal, candidate, observation):
        response = super().response_from_decision(decision, proposal, candidate, observation)
        if int(self.identity) >= self.count:
            response.public["outsider"] = True
        return response

    def compatible(self, candidate, reports):
        relevant = {peer: report for peer, report in reports.items() if not report["public"].get("outsider")}
        return super().compatible(candidate, relevant)

    def revoke(self, observation):
        self.notifications.append("own_revoke")

    def valid(self, response, observation):
        slot = response.public.get("slot")
        return (type(slot) is int and self.release <= slot <= self.release+self.count+3
                and super().valid(response, observation))

    def dependency_changed(self, peer, observation):
        self.notifications.append(peer)

    def act(self, observation):
        return self.plan.segments["shared"]


def execute(seed, scoped, target):
    release = random.Random(seed).randint(0, 4)
    count = 3
    members = tuple(str(index) for index in range(count+1))
    model = resource.OllamaDecisionModel()
    mailbox = Mailbox()
    tasks = [DynamicTask(identity, count, release, scoped) for identity in members]
    agents = [Agent(identity, members, task, mailbox, max_negotiation_rounds=8, decision_model=model)
              for identity, task in zip(members, tasks)]
    stages = []
    try:
        for phase in range(2):
            if phase:
                # A resource closure invalidates all not-yet-executed reservations.
                for task in tasks:
                    task.release += 12
                    task.required_installs = 2
                agents[0].emergency(tasks[0].observe())
            for offset in range(12):
                now = phase*12+offset
                run_round(agents, mailbox, now)
                if all(task.installs >= phase+1 for task in tasks[:count]):
                    break
            slots = [task.plan.segments["shared"] for task in tasks[:count]]
            valid = (all(type(slot) is int and tasks[index].release <= slot <= tasks[index].release+count+3
                         for index, slot in enumerate(slots)) and len(set(slots)) == count)
            stages.append({"phase": phase, "slots": slots, "valid": valid,
                           "committed": all(task.installs >= phase+1 for task in tasks[:count]),
                           "calls_so_far": len(model.calls)})
            print(seed, scoped, phase, stages[-1], flush=True)
        final = stages[-1]
        execution = [{"time": now, "workers": [str(index) for index, slot in enumerate(final["slots"]) if slot == now]}
                     for now in range(tasks[0].release+count+4)]
        return {"seed": seed, "scoped": scoped, "stages": stages,
                "completed": sum(len(row["workers"]) for row in execution) if final["valid"] else 0,
                "execution": execution, "llm_calls": len(model.calls),
                "input_tokens": sum(call["response"].get("prompt_eval_count", 0) for call in model.calls),
                "output_tokens": sum(call["response"].get("eval_count", 0) for call in model.calls),
                "messages": len(mailbox.messages),
                "outsider_contacted": any(message.receiver == str(count) for message in mailbox.messages),
                "unrelated_preserved": all(task.plan.versions["other"] == 0 for task in tasks),
                "revocation_delivered": any(message.kind == "revoke" for message in mailbox.messages),
                "trace": {agent.identity: agent.trace for agent in agents}, "calls": model.calls}
    finally:
        (target / f"calls-{seed}-{scoped}.json").write_text(json.dumps(model.calls, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    target = ROOT / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target.mkdir(parents=True)
    manifest = {"seeds": [1046, 1047, 1048], "relevant_agents": 3, "outsiders": 1,
                "event": "resource closure before execution shifts legal slots by 12", "methods": ["scoped", "whole_group"]}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (target / "runner.py").write_bytes(Path(__file__).read_bytes())
    (target / "resource_task.py").write_bytes((ROOT.parent / "011-llm-coordination/run.py").read_bytes())
    for filename in ["agent.py", "llm.py"]:
        (target / filename).write_bytes((ROOT.parent.parent / "核心源码" / filename).read_bytes())
    results = []
    for seed in manifest["seeds"]:
        for scoped in [True, False]:
            try:
                results.append(execute(seed, scoped, target))
            except Exception as error:
                (target / "error.txt").write_text(repr(error), encoding="utf-8")
                raise
            (target / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(target, flush=True)


if __name__ == "__main__":
    main()
