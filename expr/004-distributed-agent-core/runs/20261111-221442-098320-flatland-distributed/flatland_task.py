from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "003-flatland-core" / "src"))
from planning import action, candidates, collisions, predict
from agent import Candidate, Response
from coordination import Ollama


class ModelBudget:
    def __init__(self, limit):
        self.limit = limit
        self.client = Ollama()
        self.fallbacks = 0
        self.cache = {}

    def choose(self, owner, choices, context):
        key = (owner, context["step"], repr(choices))
        if key in self.cache:
            return self.cache[key]
        if len(self.client.calls) >= self.limit:
            self.fallbacks += 1
            return None
        selected = self.client.choose(owner, choices, context)
        self.cache[key] = selected
        return selected


class FlatlandTask:
    def __init__(self, env, handle, horizon=32, model=None, public_resources=None):
        self.env = env
        self.handle = handle
        self.horizon = horizon
        self.plan = None
        self.version = 0
        self.expires = 0
        self.dirty = True
        self.options = {}
        self.installs = 0
        self.revocations = 0
        self.model = model
        self.public_resources = public_resources or {}
        self.can_initiate = True
        self.repair_cost = 0.0
        self.repair_installs = 0
        self.menu_limit = 3
        self.repair_weight = 1.0
        self.resource_scoped = False

    def proposal_participants(self, candidates, observation):
        footprint = {tuple(cell) for candidate in candidates for cell in candidate.public["cells"] if cell is not None}
        footprint |= self.public_resources.get(str(self.handle), set())
        return tuple(sorted({str(self.handle)} | {peer for peer, resources in self.public_resources.items()
                                                  if footprint & resources}))

    def passage(self, cells, now):
        windows = []
        for offset, cell in enumerate(cells):
            if cell is None:
                continue
            if windows and windows[-1]["resource"] == cell and windows[-1]["exit"] == now+offset:
                windows[-1]["exit"] += 1
            else:
                windows.append({"resource": cell, "enter": now+offset, "exit": now+offset+1})
        return windows

    def response_options(self, proposal, candidate, observation, primary):
        if self.menu_limit == 1:
            return [primary]
        if proposal.owner == str(self.handle) or observation["done"] or observation["fault"]:
            return [primary]
        now = observation["step"]
        base = self.cost(self.plan, now) if self.plan else 0
        options = [primary] if primary.feasible else []
        unique = {tuple(primary.public["cells"])} if primary.feasible else set()
        feasible = sorted(self.local_options(now), key=lambda plan: self.cost(plan, now))
        for plan in feasible:
            signature = tuple(plan.cells)
            if signature in unique or collisions(plan.cells, candidate.public["cells"]):
                continue
            unique.add(signature)
            repair = self.plan is not None and self.forecast(self.plan, now) != plan.cells
            repair_units = 1.0 if repair else 0.0
            options.append(Response(True, self.cost(plan, now)-base+self.repair_weight*repair_units,
                {"cells": plan.cells, "passage_windows": self.passage(plan.cells, now),
                 "repair_cost": repair_units, "version": self.version},
                {"version": self.version, "plan": plan}))
            if len(options) >= self.menu_limit:
                break
        return options or [primary]

    @property
    def train(self):
        return self.env.agents[self.handle]

    def observe(self):
        train = self.train
        return {"step": self.env._elapsed_steps, "version": self.version,
                "done": train.state.name == "DONE",
                "fault": train.malfunction_handler.malfunction_down_counter > 0}

    def forecast(self, plan, now):
        path = plan.route
        if self.train.position is not None:
            state = (tuple(self.train.position), int(self.train.direction))
            if state not in path:
                return None
            path = path[path.index(state):]
        return predict(self.train, path, now, max(now, plan.wait_until), self.horizon)

    def needs_revision(self, observation):
        return self.can_initiate and not observation["done"] and (self.plan is None or self.dirty or observation["step"] >= self.expires)

    def local_options(self, now):
        if self.train.state.name == "DONE":
            return []
        return candidates(self.env, self.train, now, self.horizon, self.plan)

    def cost(self, plan, now):
        route = plan.route
        if self.train.position is not None:
            state = (tuple(self.train.position), int(self.train.direction))
            if state in route:
                route = route[route.index(state):]
        return max(0, plan.wait_until-now) + len(route)/float(self.train.speed_counter.max_speed)

    def candidates(self, observation):
        self.options = {str(index): plan for index, plan in enumerate(self.local_options(observation["step"]))}
        return tuple(Candidate(key, {"cells": plan.cells, "wait_until": plan.wait_until,
                                     "passage_windows": self.passage(plan.cells, observation["step"]),
                                     "commitment_version": self.version,
                                     "valid_until": observation["step"]+8}) for key, plan in self.options.items())

    def respond(self, proposal, candidate, observation):
        now = observation["step"]
        base = self.cost(self.plan, now) if self.plan else 0
        if observation["done"]:
            return Response(True, 0, {"cells": [None]*self.horizon}, {"version": self.version, "plan": None})
        if observation["fault"]:
            cells = [tuple(self.train.position) if self.train.position is not None else None]*self.horizon
            valid = not collisions(candidate.public["cells"], cells)
            return Response(valid, 0, {"cells": cells}, {"version": self.version, "plan": None})
        if proposal.owner == str(self.handle):
            plan = self.options[candidate.key]
            return Response(True, self.cost(plan, now)-base, {"cells": plan.cells},
                            {"version": self.version, "plan": plan})
        options = self.local_options(now)
        feasible = [plan for plan in options if not collisions(plan.cells, candidate.public["cells"])]
        if not feasible:
            return Response(False, 0, {"cells": []}, {"version": self.version, "plan": None})
        selected = min(feasible, key=lambda plan: self.cost(plan, now))
        if self.model and len(feasible) > 1:
            choices = [{"wait": max(0, plan.wait_until-now), "remaining_cost": self.cost(plan, now),
                        "label": plan.label, "route_cells": len(plan.route)} for plan in feasible]
            choice = self.model.choose(str(self.handle), choices, {"step": now,
                                      "role": "respond to a teammate proposal using your own feasible plans"})
            if choice is not None:
                selected = feasible[choice]
        repair = float(self.plan is not None and self.forecast(self.plan, now) != selected.cells)
        return Response(True, self.cost(selected, now)-base+self.repair_weight*repair,
                        {"cells": selected.cells, "passage_windows": self.passage(selected.cells, now),
                         "repair_cost": repair, "version": self.version},
                        {"version": self.version, "plan": selected})

    def compatible(self, candidate, responses):
        reports = list(responses.values())
        return all(not collisions(first["public"]["cells"], second["public"]["cells"])
                   for index, first in enumerate(reports) for second in reports[index+1:])

    def valid(self, response, observation):
        return response.private_plan["version"] == self.version

    def install(self, response):
        self.repair_cost += response.public.get("repair_cost", 0)
        self.repair_installs += response.public.get("repair_cost", 0) > 0
        self.plan = response.private_plan["plan"]
        self.version += 1
        self.expires = self.env._elapsed_steps+8
        self.dirty = False
        self.installs += 1

    def infeasible(self, observation):
        if observation["done"] or self.plan is None:
            return False
        if observation["fault"]:
            return True
        offset = observation["step"]-self.plan.published
        expected = self.plan.cells[offset] if offset < len(self.plan.cells) else None
        actual = tuple(self.train.position) if self.train.position is not None else None
        return offset < len(self.plan.cells) and actual != expected

    def revoke(self, observation):
        if self.plan is not None:
            self.plan = None
            self.version += 1
            self.revocations += 1
        self.dirty = True

    def coordination_peers(self, proposal, observation):
        if not self.public_resources:
            return ()
        footprint = self.public_resources[str(self.handle)]
        return tuple(peer for peer, resources in self.public_resources.items()
                     if peer != str(self.handle) and footprint & resources)

    def dependency_changed(self, peer, observation):
        self.dirty = True

    def act(self, observation):
        if observation["done"] or observation["fault"] or self.plan is None:
            return 4
        return action(self.train, self.plan, observation["step"])
