import copy
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "004-distributed-agent-core/src"))
from agent import Agent, Candidate, Response, PlanPatch, SegmentedPlan
from demo import Mailbox, run_round


class ChainTask:
    def __init__(self, identity, count, menus):
        self.identity = identity
        self.count = count
        self.menus = menus
        self.plan = SegmentedPlan({"shared": 0, "unrelated": {"work": "keep"}})
        self.installs = 0

    def observe(self):
        return {}

    def needs_revision(self, observation):
        return self.identity == "0" and not self.installs

    def candidates(self, observation):
        return (Candidate("coordinate", {"resource": "shared"}),)

    def proposal_participants(self, candidates, observation):
        return ("0",)

    def respond(self, proposal, candidate, observation):
        if proposal.constraints:
            return self.option(int(self.identity))
        return self.option(0)

    def negotiation_constraints(self, proposal, reports, reason):
        return {"reason": reason, "priority": sorted(proposal.participants),
                "rule": "each member selects its own distinct waiting slot"}

    def option(self, slot):
        return Response(True, slot, {"slot": slot},
                        PlanPatch({"shared": self.plan.versions["shared"]}, {"shared": slot}))

    def response_options(self, proposal, candidate, observation, primary):
        return [primary, self.option(int(self.identity)+1)] if self.menus else [primary]

    def response_dependencies(self, proposal, candidate, response, observation):
        following = int(self.identity)+1
        return (str(following),) if following < self.count else ()

    def compatible(self, candidate, reports):
        slots = [report["public"]["slot"] for report in reports.values()]
        return len(slots) == len(set(slots))

    def valid(self, response, observation):
        return self.plan.valid(response.private_plan)

    def install(self, response):
        self.plan.apply(response.private_plan)
        self.installs += 1

    def infeasible(self, observation):
        return False

    def act(self, observation):
        return self.plan.segments["shared"]


def execute(count, menus):
    members = tuple(str(index) for index in range(count+1))
    mailbox = Mailbox()
    agents = [Agent(identity, members, ChainTask(identity, count, menus), mailbox) for identity in members]
    before = [copy.deepcopy(member.task.plan.segments["unrelated"]) for member in agents]
    for step in range(6):
        run_round(agents, mailbox, step)
        if all(member.task.installs == 1 for member in agents[:count]):
            break
    selected = [member.task.plan.segments["shared"] for member in agents[:count]]
    committed = all(member.task.installs == 1 for member in agents[:count])
    return {"chain_length": count, "menus": menus, "committed": committed,
            "conflict_free": committed and len(set(selected)) == count,
            "selected_slots": selected, "messages": len(mailbox.messages),
            "coordination_steps": step+1, "total_wait_cost": sum(selected),
            "unrelated_preserved": all(member.task.plan.segments["unrelated"] == before[index]
                                       and member.task.plan.versions["unrelated"] == 0 for index, member in enumerate(agents)),
            "outsider_contacted": any(message.receiver == str(count) for message in mailbox.messages),
            "trace": {member.identity: member.trace for member in agents}}


def main():
    target = ROOT / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target.mkdir(parents=True)
    results = [execute(count, menus) for count in [3, 4, 5] for menus in [False, True]]
    for row in results:
        print(row["chain_length"], row["menus"], row["committed"], row["conflict_free"], flush=True)
    (target / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (target / "runner.py").write_bytes(Path(__file__).read_bytes())
    (target / "core_agent.py").write_bytes((ROOT.parent.parent / "核心源码/agent.py").read_bytes())


if __name__ == "__main__":
    main()
