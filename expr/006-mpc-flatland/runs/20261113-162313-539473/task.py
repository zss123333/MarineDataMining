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
        if self.mode == "periodic":
            return observation["step"] % 8 == 0 or self.plan is None
        return super().needs_revision(observation)

    def feedback_boundary(self, response, observation):
        now = observation["step"]
        upcoming = [event["step"] for event in self.events if event["step"] > now
                    and self.handle in event["agents"]]
        return min([now+8] + upcoming)

    def negotiation_constraints(self, proposal, reports, reason):
        if self.mode != "feedback":
            return None
        return {"attempt": proposal.attempt+1, "reason": reason}

    def response_options(self, proposal, candidate, observation, primary):
        original = self.menu_limit
        if proposal.constraints:
            self.menu_limit = min(7, original+2*proposal.attempt)
        try:
            return super().response_options(proposal, candidate, observation, primary)
        finally:
            self.menu_limit = original
