import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "004-distributed-agent-core/src"))
from agent import Agent, Candidate, Response, PlanPatch, SegmentedPlan
from demo import ExampleTask, Mailbox, run_round


class LocalTask(ExampleTask):
    def __init__(self, identity):
        super().__init__(identity if identity in ("A", "B", "C") else "C")
        self.identity = identity
        self.plan = SegmentedPlan({"shared": {"slot": 10}, "independent": {"payload": "private work", "slot": 90}})
        self.generations = 0
        self.applied = 0

    def needs_revision(self, observation):
        return self.identity == "A" and self.applied == 0

    def candidates(self, observation):
        return (Candidate("move", {"task": "shared", "slot": 12}),)

    def respond(self, proposal, candidate, observation):
        self.generations += 1
        patch = PlanPatch({"shared": self.plan.versions["shared"]}, {"shared": {"slot": candidate.public["slot"]}})
        return Response(True, 2, {"task": "shared", "slot": candidate.public["slot"]}, patch)

    def response_dependencies(self, proposal, candidate, response, observation):
        return {"B": ("C",), "C": ("D",)}.get(self.identity, ())

    def valid(self, response, observation):
        return self.plan.valid(response.private_plan)

    def install(self, response):
        self.plan.apply(response.private_plan)
        self.applied += 1

    def act(self, observation):
        return self.plan.segments["shared"]["slot"]


def build_local():
    members = ("A", "B", "C", "D", "E")
    mailbox = Mailbox()
    agents = [Agent(identity, members, LocalTask(identity), mailbox,
                    task_group=("A", "B") if identity in ("A", "B") else ("C", "D", "E")) for identity in members]
    return agents, mailbox


def main():
    agents, mailbox = build_local()
    run_round(agents, mailbox, 0)
    result = {"agents": {member.identity: {"segments": member.task.plan.segments,
                                          "versions": member.task.plan.versions,
                                          "applied": member.task.applied} for member in agents},
              "recipients": sorted({message.receiver for message in mailbox.messages}),
              "trace": {member.identity: member.trace for member in agents}}
    target = Path(__file__).resolve().parent / "runs"
    target.mkdir(exist_ok=True)
    (target / "local-chain.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
