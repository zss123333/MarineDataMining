"""同构Agent协议：任务层生成局部方案，核心只协调公开条件与提交顺序。

建议先读run_agent、Agent.start、Agent.think、Agent.act，再看数据对象。
铁路路线、工具调用和语言模型均不在本文件硬编码。
"""

from dataclasses import dataclass, field
import math
import heapq
import copy
import json
from typing import Any, Protocol


@dataclass(frozen=True)
class Candidate:
    """发起方公开的局部变化；key用于匹配响应，不承载队友私有计划。"""
    key: str
    public: dict


@dataclass
class Response:
    """成员对一个候选的答复；private_plan只保存在答复者本地。"""
    feasible: bool
    delta_cost: float
    public: dict
    private_plan: Any = field(repr=False)


@dataclass(frozen=True)
class PlanPatch:
    """base_versions为相关读集合，updates为写集合；无关任务不随补丁重置。"""
    base_versions: dict[str, int]
    updates: dict[str, Any]


class SegmentedPlan:
    """按任务片段维护内容与版本，支持局部乐观并发检查。"""
    def __init__(self, segments):
        self.segments = copy.deepcopy(segments)
        self.versions = dict.fromkeys(segments, 0)

    def valid(self, patch):
        # 写入前必须验证所有相关读取，而不是仅验证本次写入的片段。
        return (bool(patch.updates) and set(patch.updates) <= set(patch.base_versions)
                and all(key in self.versions and self.versions[key] == version
                        for key, version in patch.base_versions.items()))

    def apply(self, patch):
        # 深拷贝后安装，避免调用方继续修改补丁而改变已确认的本地计划。
        if not self.valid(patch):
            raise ValueError("Local patch read/write versions are stale or incomplete")
        updates = copy.deepcopy(patch.updates)
        for key, value in updates.items():
            self.segments[key] = value
            self.versions[key] += 1


@dataclass(frozen=True)
class Proposal:
    """一次不可变协商快照；扩组或反馈重试必须创建新key。"""
    key: str
    owner: str
    round: int
    candidates: tuple[Candidate, ...]
    participants: tuple[str, ...]
    attempt: int = 0
    constraints: Any = None


@dataclass
class Commitment:
    key: str
    owner: str
    version: int
    property: Any
    valid_from: int
    valid_until: int
    assumptions: Any = None
    status: str = "active"


@dataclass
class Dependency:
    key: str
    consumer: str
    provider: str
    commitment: str
    version: int
    use_from: int
    use_until: int
    status: str = "active"


class Ledger:
    """记录已知承诺与未来使用需求，不从自然语言自动推断依赖。"""
    def __init__(self):
        self.commitments = {}
        self.dependencies = {}

    def register_commitment(self, commitment):
        # 对外安排换版本后，原版本的依赖不能自动继承为有效。
        previous = self.commitments.get(commitment.key)
        if commitment.valid_until <= commitment.valid_from:
            raise ValueError("Commitment requires a nonempty validity interval")
        if previous and (previous.owner != commitment.owner or commitment.version <= previous.version):
            raise ValueError("Commitment replacement requires same owner and newer version")
        if previous:
            previous.status = "replaced"
            for dependency in self.dependencies.values():
                if dependency.commitment == previous.key and dependency.status == "active":
                    dependency.status = "invalidated"
        self.commitments[commitment.key] = copy.deepcopy(commitment)

    def register_dependency(self, dependency):
        # 未来使用窗必须落在对应版本承诺的有效窗内。
        commitment = self.commitments.get(dependency.commitment)
        if (not commitment or commitment.status != "active" or commitment.owner != dependency.provider
                or commitment.version != dependency.version or dependency.use_from < commitment.valid_from
                or dependency.use_until > commitment.valid_until or dependency.use_until <= dependency.use_from):
            raise ValueError("Dependency requires a matching commitment covering its future use window")
        self.dependencies[dependency.key] = copy.deepcopy(dependency)

    def release(self, key):
        if key in self.dependencies:
            self.dependencies[key].status = "released"

    def release_commitment(self, key):
        if key in self.commitments:
            self.commitments[key].status = "released"
            for dependency in self.dependencies.values():
                if dependency.commitment == key and dependency.status == "active":
                    dependency.status = "invalidated"

    def advance(self, now):
        for commitment in self.commitments.values():
            if commitment.status == "active" and now >= commitment.valid_until:
                commitment.status = "expired"
        for dependency in self.dependencies.values():
            commitment = self.commitments[dependency.commitment]
            if dependency.status == "active":
                if now >= dependency.use_until:
                    dependency.status = "expired"
                elif commitment.status != "active":
                    dependency.status = "invalidated"

    def peers(self, identity):
        return {dependency.consumer if dependency.provider == identity else dependency.provider
                for dependency in self.dependencies.values() if dependency.status == "active"
                and identity in (dependency.consumer, dependency.provider)} - {identity}

    def revoke(self, owner):
        for commitment in self.commitments.values():
            if commitment.owner == owner and commitment.status == "active":
                commitment.status = "revoked"
        for dependency in self.dependencies.values():
            if self.commitments[dependency.commitment].status == "revoked" and dependency.status == "active":
                dependency.status = "invalidated"


@dataclass
class Message:
    sender: str
    receiver: str
    kind: str
    proposal: str
    payload: Any


class Task(Protocol):
    """任务插件的基本契约：核心决定何时问，插件决定怎样做才可行。"""
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


class AdaptiveTask(Task, Protocol):
    """可选扩展。未实现的回调通过getattr跳过，不代表相应任务能力成立。"""
    def proposal_participants(self, candidates, observation) -> tuple[str, ...]: ...
    def response_options(self, proposal, candidate, observation, primary) -> list[Response]: ...
    def local_revision(self, candidates, observation) -> Response | None: ...
    def external_conditions_unchanged(self, response, observation) -> bool: ...
    def feedback_boundary(self, response, observation) -> int: ...
    def execution_valid(self, observation) -> bool: ...
    def safe_action(self, observation) -> Any: ...
    def evaluation_key(self, proposal, candidate, observation) -> Any: ...
    def repair_options(self, proposal, candidate, observation, primary) -> list[Response]: ...
    def negotiation_constraints(self, proposal, reports, reason) -> Any: ...
    def commitment_records(self, observation) -> tuple[list[Commitment], list[Dependency]]: ...
    def response_dependencies(self, proposal, candidate, response, observation) -> tuple[str, ...]: ...


class Transport(Protocol):
    def send(self, message: Message) -> None: ...
    def receive(self, receiver: str) -> list[Message]: ...


class Clock(Protocol):
    def finished(self) -> bool: ...
    def round(self) -> int: ...
    def exchange(self, agent: Any) -> None: ...
    def execute(self, identity: str, action: Any) -> None: ...


def run_agent(agent: Any, clock: Clock):
    """观察/决策→同步交换至结束→近期动作；exchange须落实提交屏障。"""
    while not clock.finished():
        agent.step(clock.round())
        clock.exchange(agent)
        clock.execute(agent.identity, agent.act())


class Agent:
    """每个成员运行同一类；发起者只是本次提案的临时组合选择者。"""
    def __init__(self, identity: str, members: tuple[str, ...], task: Task, transport: Transport, task_group: tuple[str, ...] | None = None, max_negotiation_rounds=3, delta_messages=False, decision_model=None):
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
        if max_negotiation_rounds < 1:
            raise ValueError("Negotiation rounds must be positive")
        self.max_negotiation_rounds = max_negotiation_rounds
        self.delta_messages = delta_messages
        self.sent_public = {}
        self.received_public = {}
        self.evaluations = {}
        self.ledger = Ledger()
        self.execute_until = None
        self.active_round = 0
        self.pending_revision = None
        self.decision_model = decision_model

    def model_decision(self, stage, observation, **details):
        context = self.task.decision_context(stage, observation, **details)
        return self.decision_model.decide(self.identity, stage, context)

    def generate_response(self, proposal, candidate, observation):
        if self.decision_model is None:
            return self.task.respond(proposal, candidate, observation)
        errors = []
        for attempt in range(3):
            decision = self.model_decision("respond", observation, proposal=proposal,
                                           candidate=candidate, errors=errors)
            try:
                response = self.task.response_from_decision(decision, proposal, candidate, observation)
                if not self.task.valid(response, observation):
                    raise ValueError("Response no longer valid")
                self.trace.append({"event": "model_response", "attempt": attempt, "proposal": proposal.key})
                return response
            except (ValueError, KeyError, TypeError) as error:
                errors.append(str(error))
        raise RuntimeError("Model failed response validation after three attempts; no rule substitution")

    def continue_coordination(self, proposal, reason):
        """结束的只是旧事务；预算用完后保留修订请求，下一观察轮继续。"""
        callback = getattr(self.task, "negotiation_constraints", None)
        constraints = callback(proposal, self.responses.get(proposal.key, {}), reason) if callback else None
        if constraints is not None and proposal.attempt+1 < self.max_negotiation_rounds:
            self.launch(proposal.round, proposal.candidates, proposal.participants,
                        proposal.attempt+1, constraints)
        else:
            self.pending_revision = (proposal.participants, constraints)
            self.trace.append({"proposal": proposal.key, "event": "coordination_deferred", "reason": reason})

    def sync_records(self, observation):
        self.ledger.advance(self.active_round)
        callback = getattr(self.task, "commitment_records", None)
        if callback:
            commitments, dependencies = callback(observation)
            for commitment in commitments:
                previous = self.ledger.commitments.get(commitment.key)
                if previous is None or commitment.version > previous.version:
                    self.ledger.register_commitment(commitment)
            for dependency in dependencies:
                previous = self.ledger.dependencies.get(dependency.key)
                if previous is None or dependency.version > previous.version:
                    self.ledger.register_dependency(dependency)

    def install(self, response, observation):
        """安装本人已确认响应，并刷新反馈边界和本地依赖记录。"""
        callback = getattr(self.task, "feedback_boundary", None)
        boundary = callback(response, observation) if callback else None
        if boundary is not None and boundary <= self.active_round:
            raise ValueError("Feedback boundary must be in the future")
        self.task.install(response)
        self.execute_until = boundary
        self.evaluations.clear()
        self.sync_records(self.task.observe())

    def emergency(self, observation):
        """不可履约时先撤销，再通知相关方，不等待队友批准。"""
        self.sync_records(observation)
        callback = getattr(self.task, "coordination_peers", None)
        peers = self.ledger.peers(self.identity) | self.related(None, observation)
        if callback is None and not self.ledger.commitments:
            peers |= set(self.task_group)
        self.ledger.revoke(self.identity)
        self.task.revoke(observation)
        self.execute_until = None
        self.evaluations.clear()
        for peer in peers - {self.identity}:
            self.send(peer, "revoke", f"revoke:{self.identity}:{self.active_round}", None)

    def safe_action(self, observation):
        callback = getattr(self.task, "safe_action", None)
        if callback is None:
            raise RuntimeError("Expired execution requires task.safe_action")
        return callback(observation)

    def execution_allowed(self, observation):
        callback = getattr(self.task, "execution_valid", None)
        return ((callback is None or callback(observation))
                and (self.execute_until is None or self.active_round < self.execute_until)
                and all(commitment.status == "active" for commitment in self.ledger.commitments.values()
                        if commitment.owner == self.identity and commitment.status not in ("released", "replaced", "revoked"))
                and not any(dependency.consumer == self.identity and dependency.status == "invalidated"
                            for dependency in self.ledger.dependencies.values()))

    def related(self, proposal, observation):
        callback = getattr(self.task, "coordination_peers", None)
        peers = (set(callback(proposal, observation)) if callback else set()) | self.ledger.peers(self.identity)
        if not peers <= set(self.members):
            raise ValueError("Dependency peer must be a known member")
        return peers

    def launch(self, round, candidates, participants, attempt=0, constraints=None):
        """创建新提案；不复用旧key，防止旧确认批准新参与集合。"""
        self.sequence += 1
        key = f"{round}:{self.identity}:{self.sequence}"
        proposal = Proposal(key, self.identity, round, candidates, tuple(sorted(participants)), attempt, constraints)
        self.proposals[key] = proposal
        self.responses[key] = {}
        self.broadcast("propose", key, proposal)

    def send(self, peer, kind, proposal, payload):
        if kind == "respond" and self.delta_messages:
            previous = self.sent_public.get(peer)
            current = copy.deepcopy(payload)
            version = previous[0]+1 if previous else 1
            if previous:
                changed = {key: value for key, value in current.items() if previous[1].get(key) != value}
                envelope = {"base": previous[0], "version": version, "changed": changed,
                            "removed": [key for key in previous[1] if key not in current]}
                if len(json.dumps(envelope)) < len(json.dumps(current)):
                    kind, payload = "respond_delta", envelope
            if kind == "respond":
                kind, payload = "respond_full", {"version": version, "data": current}
            self.sent_public[peer] = (version, current)
        self.transport.send(Message(self.identity, peer, kind, proposal, payload))

    def broadcast(self, kind, proposal, payload):
        scope = self.proposals[proposal].participants if proposal in self.proposals else self.task_group
        for peer in scope:
            self.send(peer, kind, proposal, payload)

    def start(self, round):
        """检查条件；可内部处理则不通信，否则按轮换发起局部协商。"""
        if self.started_round == round:
            return
        self.started_round = round
        self.active_round = round
        observation = self.task.observe()
        self.sync_records(observation)
        if self.task.infeasible(observation):
            self.emergency(observation)
            return
        if self.locked or (self.pending_revision is None and not self.task.needs_revision(observation) and self.execution_allowed(observation)):
            return
        if self.decision_model is None:
            candidates = self.task.candidates(observation)
        else:
            if self.task_group[round % len(self.task_group)] != self.identity:
                return
            errors = []
            for attempt in range(3):
                decision = self.model_decision("revise", observation, errors=errors)
                try:
                    candidates = self.task.candidates_from_decision(decision, observation)
                    break
                except (ValueError, KeyError, TypeError) as error:
                    errors.append(str(error))
            else:
                raise RuntimeError("Model failed candidate validation; no rule substitution")
        if not candidates or len({item.key for item in candidates}) != len(candidates):
            raise ValueError("Candidates must be nonempty with distinct keys, including keep")
        local = getattr(self.task, "local_revision", None)
        unchanged = getattr(self.task, "external_conditions_unchanged", None)
        response = local(candidates, observation) if local and unchanged else None
        if response is not None and response.feasible and unchanged(response, observation) and self.task.valid(response, observation):
            self.install(response, observation)
            self.trace.append({"event": "local_revision", "round": round})
            return
        if self.task_group[round % len(self.task_group)] != self.identity:
            return
        selector = getattr(self.task, "proposal_participants", None)
        participants = tuple(selector(candidates, observation)) if selector else self.task_group
        if self.identity not in participants or not set(participants) <= set(self.members):
            raise ValueError("Proposal participants must include self and only known members")
        constraints = None
        if self.pending_revision is not None:
            previous, constraints = self.pending_revision
            participants = tuple(sorted(set(participants) | set(previous)))
            self.pending_revision = None
        self.launch(round, candidates, participants, constraints=constraints)

    def think(self, message):
        """消息状态机：提案→各自响应→组合→准备→提交，失败则中止。"""
        if message.sender not in self.members or message.receiver != self.identity:
            return
        observation = self.task.observe()
        key = message.proposal
        if message.kind in ("respond_full", "respond_delta"):
            if key in self.final or key not in self.responses or message.sender not in self.proposals[key].participants:
                return
            envelope = message.payload
            if message.kind == "respond_full":
                payload = copy.deepcopy(envelope["data"])
            else:
                previous = self.received_public.get(message.sender)
                if previous is None or previous[0] != envelope["base"]:
                    self.broadcast("abort", key, None)
                    self.trace.append({"proposal": key, "event": "delta_base_mismatch"})
                    return
                payload = copy.deepcopy(previous[1])
                for removed in envelope["removed"]:
                    payload.pop(removed, None)
                payload.update(copy.deepcopy(envelope["changed"]))
            self.received_public[message.sender] = (envelope["version"], payload)
            message = Message(message.sender, message.receiver, "respond", key, payload)
        if message.kind == "revoke":
            self.ledger.revoke(message.sender)
            self.evaluations.clear()
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
            evaluated = {}
            generated = {}
            cache_key = getattr(self.task, "evaluation_key", None)
            repairs = getattr(self.task, "repair_options", None)
            alternatives = getattr(self.task, "response_options", None)
            for candidate in proposal.candidates:
                token = cache_key(proposal, candidate, observation) if cache_key else None
                signature = repr((token, candidate.key, candidate.public, proposal.owner,
                                  proposal.participants, proposal.constraints)) if token is not None else None
                cached = self.evaluations.get(signature) if signature is not None else None
                if cached and all(self.task.valid(option, observation) for option in cached):
                    options = copy.deepcopy(cached)
                    self.trace.append({"proposal": key, "event": "evaluation_reused"})
                else:
                    primary = self.generate_response(proposal, candidate, observation)
                    options = alternatives(proposal, candidate, observation, primary) if alternatives else [primary]
                    if repairs:
                        options = list(options) + list(repairs(proposal, candidate, observation, primary))
                    if not options:
                        options = [primary]
                    if signature is not None:
                        if len(self.evaluations) >= 256:
                            self.evaluations.pop(next(iter(self.evaluations)))
                        self.evaluations[signature] = copy.deepcopy(options)
                evaluated[candidate.key] = options[0]
                generated[candidate.key] = options
            dependencies = getattr(self.task, "response_dependencies", None)
            # 先生成自己的响应，才能发现“为了配合A，我会进一步影响C”。
            # 新依赖必须在提交前补齐，不能安装后再把冲突留给第三方。
            response_peers = set()
            if dependencies:
                for candidate in proposal.candidates:
                    for response in generated[candidate.key]:
                        if response.feasible:
                            response_peers.update(dependencies(proposal, candidate, response, observation))
                if not response_peers <= set(self.members):
                    raise ValueError("Response dependency must be a known member")
                extra = response_peers - set(proposal.participants)
                if extra:
                    self.blocked.add(key)
                    self.send(proposal.owner, "expand", key, tuple(sorted(extra)))
                    self.trace.append({"proposal": key, "event": "response_dependency_expansion", "peers": sorted(extra)})
                    return
            self.alternatives = getattr(self, "alternatives", {})
            self.alternatives[key] = generated
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
            self.launch(proposal.round, proposal.candidates, set(proposal.participants) | extra,
                        proposal.attempt, proposal.constraints)
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
            # 只枚举各成员自己给出的公开选项，不能替队友生成私有动作。
            exhausted = False
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
                exhausted = exhausted or bool(queue and checked >= 128)
            if not feasible:
                self.broadcast("abort", key, None)
                reason = "budget_exhausted" if exhausted else "menu_exhausted"
                self.trace.append({"proposal": key, "event": "no_combination", "reason": reason})
                self.continue_coordination(proposal, reason)
                return
            _, chosen, selection = min(feasible, key=lambda item: (item[0], item[1]))
            self.trace.append({"proposal": key, "event": "selected_combination", "candidate": chosen,
                               "selection": selection,
                               "uses_alternative": any(index > 0 for index in selection.values())})
            self.ready[key] = {}
            for peer in proposal.participants:
                self.send(peer, "prepare", key, {"candidate": chosen, "option": selection[peer]})
        elif message.kind == "prepare" and key in self.local:
            # 二次核验并加准备锁；回答后的版本变化必须阻止本轮提交。
            proposal = self.proposals[key]
            if message.sender != proposal.owner:
                return
            choice = message.payload if isinstance(message.payload, dict) else {"candidate": message.payload, "option": 0}
            options = self.alternatives[key].get(choice["candidate"], [])
            response = options[choice["option"]] if 0 <= choice["option"] < len(options) else None
            valid = (key not in self.blocked and self.locked in [None, key]
                     and response is not None and response.feasible and self.task.valid(response, observation))
            boundary = getattr(self.task, "feedback_boundary", None)
            if valid and boundary:
                limit = boundary(response, observation)
                valid = limit is None or limit > self.active_round
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
                if decision == "abort":
                    self.continue_coordination(self.proposals[key], "preparation_invalidated")
        elif message.kind in ["commit", "abort"] and key in self.proposals:
            if message.sender != self.proposals[key].owner:
                return
            if message.kind == "commit":
                candidate = self.prepared.get(key)
                if candidate is None:
                    raise RuntimeError("Commit without locally prepared response")
                self.install(candidate, observation)
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
        """只执行已完成协商且仍有效的近期动作；准备锁未释放时禁止行动。"""
        if self.locked is not None:
            raise RuntimeError("Cannot execute before synchronous negotiation completes")
        observation = self.task.observe()
        self.sync_records(observation)
        if self.task.infeasible(observation):
            self.emergency(observation)
        if not self.execution_allowed(observation):
            self.trace.append({"event": "execution_blocked", "round": self.active_round})
            return self.safe_action(observation)
        return self.task.act(observation)
