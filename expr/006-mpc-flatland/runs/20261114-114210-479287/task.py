import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "004-distributed-agent-core/src"))
from flatland_task import FlatlandTask
from planning import Plan, predict


class MPCTask(FlatlandTask):
    def __init__(self, env, handle, route, events, mode, resources):
        super().__init__(env, handle, public_resources=resources)
        self.fixed_route = route
        self.events = events
        self.mode = mode
        self.menu_limit = 1 if mode == "single" else 3
        self.repair_weight = 1
        self.public_progress = {}
        self.fallback = None
        self.guard_waits = 0
        self.fallback_uses = 0

    def blocking_peers(self):
        own = self.public_resources.get(str(self.handle), set())
        return tuple(peer for peer, resources in self.public_resources.items()
                     if int(peer) < self.handle and own & resources
                     and self.public_progress.get(peer, "pending") != "done")

    def execution_valid(self, observation):
        return observation["done"] or (not observation["fault"] and self.plan is not None
                                       and not self.infeasible(observation)
                                       and (self.train.position is not None or not self.blocking_peers()))

    def safe_action(self, observation):
        if self.plan is not None and not observation["fault"] and not self.infeasible(observation) and (self.train.position is not None or not self.blocking_peers()):
            self.fallback_uses += 1
            return super().act(observation)
        return 0 if self.train.position is None else 4

    def install(self, response):
        super().install(response)
        if self.plan is not None:
            self.fallback = self.plan

    def revoke(self, observation):
        super().revoke(observation)
        self.fallback = None

    def act(self, observation):
        if observation["fault"]:
            return self.safe_action(observation)
        if self.train.position is None and self.blocking_peers():
            self.guard_waits += 1
            return 0
        if self.plan is None and not observation["done"]:
            options = self.local_options(observation["step"])
            if options:
                self.plan = options[0]
                self.fallback = self.plan
                self.fallback_uses += 1
        return super().act(observation)

    def observe(self):
        observation = super().observe()
        observation["fault"] = observation["fault"] or any(
            event["step"] <= observation["step"] < event["step"]+event["duration"]
            and self.handle in event["agents"] for event in self.events)
        return observation

    def local_options(self, now):
        if self.train.state.name == "DONE":
            return []
        route = self.fixed_route
        if self.train.position is not None:
            state = (tuple(self.train.position), int(self.train.direction))
            if state not in route:
                return []
            route = route[route.index(state):]
        result = []
        delays = [0, 4, 8, 16, 24]
        if self.plan:
            delays = [max(0, self.plan.wait_until-now)] + delays
        for delay in dict.fromkeys(delays):
            result.append(Plan(route, now+delay, now,
                               predict(self.train, route, now, now+delay, self.horizon),
                               "keep" if self.plan and now+delay == max(now, self.plan.wait_until) else "timing"))
        return result

    def needs_revision(self, observation):
        if not self.can_initiate or observation["done"] or observation["fault"]:
            return False
        if self.train.position is None and self.blocking_peers():
            return False
        if self.mode == "periodic":
            return observation["step"] % 8 == 0 or self.plan is None
        return super().needs_revision(observation)

    def feedback_boundary(self, response, observation):
        return None

    def compatible(self, candidate, responses):
        if not super().compatible(candidate, responses):
            return False
        for peer, report in responses.items():
            if self.public_progress.get(peer) == "done":
                continue
            own_resources = self.public_resources.get(peer, set())
            blocked = any(int(other) < int(peer) and own_resources & resources
                          and self.public_progress.get(other) != "done"
                          for other, resources in self.public_resources.items())
            if blocked and any(cell is not None for cell in report["public"]["cells"]):
                return False
        return True

    def renew_guarded_arrangement(self, observation):
        if self.plan is None or observation["fault"]:
            return False
        if self.train.position is not None and self.infeasible(observation):
            return False
        self.expires = observation["step"]+8
        self.dirty = False
        return True

    def negotiation_constraints(self, proposal, reports, reason):
        if self.mode != "feedback":
            return None
        return {"attempt": proposal.attempt+1, "reason": reason,
                "blocked_by": self.blocking_peers(),
                "windows": [option["public"].get("passage_windows", [])
                            for report in reports.values() for reply in report.values()
                            for option in reply["options"]]}

    def response_options(self, proposal, candidate, observation, primary):
        original = self.menu_limit
        if proposal.constraints:
            self.menu_limit = min(7, original+2*proposal.attempt)
        try:
            return super().response_options(proposal, candidate, observation, primary)
        finally:
            self.menu_limit = original
