from dataclasses import dataclass, field
import math
import heapq
from typing import Any, Protocol


@dataclass(frozen=True)
class Candidate:
    key: str
    public: dict


@dataclass
class Response:
    feasible: bool
    delta_cost: float
    public: dict
    private_plan: Any = field(repr=False)


@dataclass(frozen=True)
class Proposal:
    key: str
    owner: str
    round: int
    candidates: tuple[Candidate, ...]
    participants: tuple[str, ...]


@dataclass
class Message:
    sender: str
    receiver: str
    kind: str
    proposal: str
    payload: Any


class Task(Protocol):
    def observe(self) -> Any: ...
    def needs_revision(self, observation: Any) -> bool: ...
    def candidates(self, observation: Any) -> tuple[Candidate, ...]: ...
    def respond(self, proposal: Proposal, candidate: Candidate, observation: Any) -> Response: ...
    def compatible(self, candidate: Candidate, responses: dict[str, dict]) -> bool: ...
    def valid(self, response: Response, observation: Any) -> bool: ...
    def install(self, response: Response) -> None: ...
    def infeasible(self, observation: Any) -> bool: ...
    def revoke(self, observation: Any) -> None: ...
    def dependency_changed(self, peer: str, observation: Any) -> None: ...
    def act(self, observation: Any) -> Any: ...
    def coordination_peers(self, proposal: Proposal | None, observation: Any) -> tuple[str, ...]: ...


class Transport(Protocol):
    def send(self, message: Message) -> None: ...
    def receive(self, receiver: str) -> list[Message]: ...


class Clock(Protocol):
    def finished(self) -> bool: ...
    def round(self) -> int: ...
    def exchange(self, agent: Any) -> None: ...
    def execute(self, identity: str, action: Any) -> None: ...


def run_agent(agent: Any, clock: Clock):
    while not clock.finished():
        agent.step(clock.round())
        clock.exchange(agent)
        clock.execute(agent.identity, agent.act())


class Agent:
    def __init__(self, identity: str, members: tuple[str, ...], task: Task, transport: Transport, task_group: tuple[str, ...] | None = None):
        if len(set(members)) < 3 or len(set(members)) != len(members) or identity not in members:
            raise ValueError("Distributed experiment requires at least three distinct agents")
        self.identity = identity
        self.members = tuple(sorted(members))
        self.task_group = tuple(sorted(task_group if task_group is not None else members))
        if identity not in self.task_group or not set(self.task_group) <= set(members):
            raise ValueError("Task group must contain self and only known members")
        self.task = task
        self.transport = transport
        self.local = {}
        self.proposals = {}
        self.responses = {}
        self.ready = {}
        self.prepared = {}
        self.final = set()
        self.sequence = 0
        self.trace = []
        self.locked = None
        self.blocked = set()
        self.started_round = None

    def related(self, proposal, observation):
        callback = getattr(self.task, "coordination_peers", None)
        peers = set(callback(proposal, observation)) if callback else set()
        if not peers <= set(self.members):
            raise ValueError("Dependency peer must be a known member")
        return peers

    def launch(self, round, candidates, participants):
        self.sequence += 1
        key = f"{round}:{self.identity}:{self.sequence}"
        proposal = Proposal(key, self.identity, round, candidates, tuple(sorted(participants)))
        self.proposals[key] = proposal
        self.responses[key] = {}
        self.broadcast("propose", key, proposal)

    def send(self, peer, kind, proposal, payload):
        self.transport.send(Message(self.identity, peer, kind, proposal, payload))

    def broadcast(self, kind, proposal, payload):
        scope = self.proposals[proposal].participants if proposal in self.proposals else self.task_group
        for peer in scope:
            self.send(peer, kind, proposal, payload)

    def start(self, round):
        if self.started_round == round:
            return
        self.started_round = round
        observation = self.task.observe()
        if self.task.infeasible(observation):
            self.task.revoke(observation)
            peers = set(self.task_group) | self.related(None, observation)
            for peer in peers:
                self.send(peer, "revoke", f"revoke:{self.identity}:{round}", None)
            return
        if self.locked or self.task_group[round % len(self.task_group)] != self.identity or not self.task.needs_revision(observation):
            return
        candidates = self.task.candidates(observation)
        if not candidates or len({item.key for item in candidates}) != len(candidates):
            raise ValueError("Candidates must be nonempty with distinct keys, including keep")
        selector = getattr(self.task, "proposal_participants", None)
        participants = tuple(selector(candidates, observation)) if selector else self.task_group
        if self.identity not in participants or not set(participants) <= set(self.members):
            raise ValueError("Proposal participants must include self and only known members")
        self.launch(round, candidates, participants)

    def think(self, message):
        if message.sender not in self.members or message.receiver != self.identity:
            return
        observation = self.task.observe()
        key = message.proposal
        if message.kind == "revoke":
            self.task.dependency_changed(message.sender, observation)
            for proposal_key, proposal in list(self.proposals.items()):
                if proposal_key not in self.final and message.sender in proposal.participants:
                    self.blocked.add(proposal_key)
                    self.send(proposal.owner, "cancel", proposal_key, None)
            return
        if key in self.final:
            return
        if message.kind == "propose":
            proposal = message.payload
            if (proposal.owner != message.sender or proposal.key != key
                    or self.identity not in proposal.participants
                    or not set(proposal.participants) <= set(self.members)):
                return
            if key in self.local:
                return
            self.proposals[key] = proposal
            extra = self.related(proposal, observation) - set(proposal.participants)
            if extra:
                self.send(proposal.owner, "expand", key, tuple(sorted(extra)))
            evaluated = {candidate.key: self.task.respond(proposal, candidate, observation)
                         for candidate in proposal.candidates}
            alternatives = getattr(self.task, "response_options", None)
            self.alternatives = getattr(self, "alternatives", {})
            self.alternatives[key] = {
                candidate.key: alternatives(proposal, candidate, observation, evaluated[candidate.key])
                if alternatives else [evaluated[candidate.key]] for candidate in proposal.candidates}
            if any(not math.isfinite(response.delta_cost) for response in evaluated.values()):
                raise ValueError("Each agent must report a finite own incremental cost")
            self.local[key] = evaluated
            public = {candidate: {"feasible": response.feasible, "delta_cost": response.delta_cost,
                                  "public": response.public, "cost_owner": self.identity}
                      for candidate, response in evaluated.items()}
            for candidate, options in self.alternatives[key].items():
                public[candidate]["options"] = [
                    {"feasible": option.feasible, "delta_cost": option.delta_cost,
                     "public": option.public, "cost_owner": self.identity, "option": index}
                    for index, option in enumerate(options)]
            self.send(proposal.owner, "respond", key, public)
        elif message.kind == "expand" and key in self.responses:
            proposal = self.proposals[key]
            if message.sender not in proposal.participants:
                return
            extra = set(message.payload) - set(proposal.participants)
            if not extra or not extra <= set(self.members):
                return
            self.broadcast("abort", key, None)
            self.final.add(key)
            self.launch(proposal.round, proposal.candidates, set(proposal.participants) | extra)
        elif message.kind == "cancel" and key in self.responses:
            if message.sender in self.proposals[key].participants:
                self.broadcast("abort", key, None)
        elif message.kind == "respond" and key in self.responses:
            if message.sender not in self.proposals[key].participants:
                return
            expected = {candidate.key for candidate in self.proposals[key].candidates}
            if set(message.payload) != expected or any(
                    reply.get("cost_owner") != message.sender
                    or not math.isfinite(reply["delta_cost"])
                    for reply in message.payload.values()):
                self.broadcast("abort", key, None)
                return
            self.responses[key][message.sender] = message.payload
            if set(self.responses[key]) != set(self.proposals[key].participants):
                return
            proposal = self.proposals[key]
            feasible = []
            for candidate in proposal.candidates:
                peers = tuple(sorted(self.responses[key]))
                menus = [sorted([option for option in self.responses[key][peer][candidate.key]["options"]
                                 if option["feasible"] and math.isfinite(option["delta_cost"])],
                                key=lambda option: option["delta_cost"]) for peer in peers]
                if not all(menus):
                    continue
                initial = tuple(0 for peer in peers)
                queue = [(sum(menu[0]["delta_cost"] for menu in menus), initial)]
                seen = {initial}
                checked = 0
                while queue and checked < 128:
                    cost, indices = heapq.heappop(queue)
                    reports = {peer: menus[index][indices[index]] for index, peer in enumerate(peers)}
                    checked += 1
                    if self.task.compatible(candidate, reports):
                        selection = {peer: report["option"] for peer, report in reports.items()}
                        feasible.append((cost, candidate.key, selection))
                        self.trace.append({"proposal": key, "event": "combination_found", "candidate": candidate.key,
                                           "combinations_checked": checked, "cost": cost, "selection": selection})
                        break
                    for index, menu in enumerate(menus):
                        neighbor = list(indices)
                        neighbor[index] += 1
                        neighbor = tuple(neighbor)
                        if neighbor[index] < len(menu) and neighbor not in seen:
                            seen.add(neighbor)
                            heapq.heappush(queue, (sum(menus[position][value]["delta_cost"]
                                                      for position, value in enumerate(neighbor)), neighbor))
                self.trace.append({"proposal": key, "event": "combination_search", "candidate": candidate.key,
                                   "checked": checked, "limit": 128})
            if not feasible:
                self.broadcast("abort", key, None)
                return
            _, chosen, selection = min(feasible, key=lambda item: (item[0], item[1]))
            self.trace.append({"proposal": key, "event": "selected_combination", "candidate": chosen,
                               "selection": selection,
                               "uses_alternative": any(index > 0 for index in selection.values())})
            self.ready[key] = {}
            for peer in proposal.participants:
                self.send(peer, "prepare", key, {"candidate": chosen, "option": selection[peer]})
        elif message.kind == "prepare" and key in self.local:
            proposal = self.proposals[key]
            if message.sender != proposal.owner:
                return
            choice = message.payload if isinstance(message.payload, dict) else {"candidate": message.payload, "option": 0}
            options = self.alternatives[key].get(choice["candidate"], [])
            response = options[choice["option"]] if 0 <= choice["option"] < len(options) else None
            valid = (key not in self.blocked and self.locked in [None, key]
                     and response is not None and response.feasible and self.task.valid(response, observation))
            if valid:
                self.prepared[key] = response
                self.locked = key
            self.send(proposal.owner, "ready", key, valid)
        elif message.kind == "ready" and key in self.ready:
            if message.sender not in self.proposals[key].participants:
                return
            self.ready[key][message.sender] = message.payload
            if set(self.ready[key]) == set(self.proposals[key].participants):
                decision = "commit" if all(self.ready[key].values()) else "abort"
                self.broadcast(decision, key, None)
        elif message.kind in ["commit", "abort"] and key in self.proposals:
            if message.sender != self.proposals[key].owner:
                return
            if message.kind == "commit":
                candidate = self.prepared.get(key)
                if candidate is None:
                    raise RuntimeError("Commit without locally prepared response")
                self.task.install(candidate)
            self.prepared.pop(key, None)
            if self.locked == key:
                self.locked = None
            self.final.add(key)
            self.trace.append({"proposal": key, "decision": message.kind})

    def step(self, round):
        self.start(round)

    def communicate(self):
        for message in self.transport.receive(self.identity):
            self.think(message)

    def act(self):
        if self.locked is not None:
            raise RuntimeError("Cannot execute before synchronous negotiation completes")
        observation = self.task.observe()
        if self.task.infeasible(observation):
            self.task.revoke(observation)
        return self.task.act(observation)
