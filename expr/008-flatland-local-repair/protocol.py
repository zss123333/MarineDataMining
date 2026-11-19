import copy
from datetime import datetime
import json
from pathlib import Path

from run import ROOT, initial_plans, local_response, overlaps
from agent import Agent, Candidate, Response
from demo import Mailbox, run_round
from flatland.envs.persistence import RailEnvPersister


class RailPatchTask:
    def __init__(self, identity, plan, public_schedule, delay):
        self.identity = identity
        self.plan = plan
        self.public_schedule = public_schedule
        self.delay = delay
        self.installs = 0

    def observe(self):
        return {}

    def needs_revision(self, observation):
        return self.identity == "0" and self.installs == 0

    def candidates(self, observation):
        return (Candidate("delay", {"delay": self.delay}),)

    def proposal_participants(self, candidates, observation):
        return (self.identity,)

    def affected(self, windows):
        return tuple(peer for peer, schedule in self.public_schedule.items() if int(peer) > int(self.identity)
                     and any(first["resource"] == second["resource"]
                             and overlaps((first["enter"], first["exit"]), (second["enter"], second["exit"]))
                             for first in windows.values() for second in schedule.values()))

    def respond(self, proposal, candidate, observation):
        constraints = (proposal.constraints or {}).get("quotes", {})
        quotes = [quote for peer, quote in constraints.items() if int(peer) < int(self.identity)]
        patch = local_response(self.plan, quotes, self.delay if self.identity == "0" else 0)
        windows = copy.deepcopy(self.plan.segments)
        if patch:
            windows.update(patch.updates)
        return Response(True, sum(value["enter"]-self.plan.segments[key]["enter"] for key, value in (patch.updates.items() if patch else [])),
                        {"windows": windows}, patch)

    def response_dependencies(self, proposal, candidate, response, observation):
        return self.affected(response.public["windows"]) if response.private_plan else ()

    def compatible(self, candidate, responses):
        quotes = [reply["public"]["windows"] for reply in responses.values()]
        return not any(first["resource"] == second["resource"]
                       and overlaps((first["enter"], first["exit"]), (second["enter"], second["exit"]))
                       for index, left in enumerate(quotes) for right in quotes[index+1:]
                       for first in left.values() for second in right.values())

    def negotiation_constraints(self, proposal, reports, reason):
        return {"quotes": {peer: report["delay"]["options"][0]["public"]["windows"] for peer, report in reports.items()}}

    def valid(self, response, observation):
        return response.private_plan is None or self.plan.valid(response.private_plan)

    def install(self, response):
        if response.private_plan:
            self.plan.apply(response.private_plan)
        self.installs += 1

    def infeasible(self, observation):
        return False

    def act(self, observation):
        return None


def main():
    results = []
    for level in range(3):
        for delay in [40, 120, 240]:
            source = ROOT.parent / f"datasets/mpc-flatland-v1/Test_00_Level_{level}.pkl"
            env, _ = RailEnvPersister.load_new(str(source))
            plans = initial_plans(env)
            public = {str(index): copy.deepcopy(plan.segments) for index, plan in enumerate(plans)}
            members = tuple(public)
            mailbox = Mailbox()
            agents = [Agent(identity, members, RailPatchTask(identity, plans[int(identity)], public, delay), mailbox,
                            max_negotiation_rounds=7) for identity in members]
            run_round(agents, mailbox, 0)
            results.append({"level": level, "delay": delay,
                            "recipients": sorted({message.receiver for message in mailbox.messages}),
                            "installs": {member.identity: member.task.installs for member in agents},
                            "versions": [plan.versions for plan in plans],
                            "trace": {member.identity: member.trace for member in agents}})
            print(level, delay, results[-1]["recipients"], results[-1]["installs"], flush=True)
    target = ROOT / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S-%f")+"-protocol")
    target.mkdir()
    (target / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
