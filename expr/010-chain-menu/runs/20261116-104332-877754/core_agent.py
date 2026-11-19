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


# 候选只描述发起方希望改变的公开条件，不装入其他人的私有行动链。
# frozen只禁止字段重新赋值；public内部的dict仍可修改，因此调用方应把它当快照使用。
@dataclass(frozen=True)
class Candidate:
    """发起方公开的局部变化；key用于匹配响应，不承载队友私有计划。"""
    # 本次候选唯一编号，响应和提交用它对应同一个局部变化。
    key: str
    # 供相关成员判断影响的共享条件；不应塞入完整私有上下文。
    public: dict


# 这是某一成员对某一候选的本地回答，局部可行还需要经过跨成员组合检查。
# private_plan保存在答复者本地；repr=False只影响打印，消息隐私依靠后续显式挑选公开字段。
@dataclass
class Response:
    """成员对一个候选的答复；private_plan只保存在答复者本地。"""
    # 本人局部是否可接受；跨成员组合是否可行还要检查compatible。
    feasible: bool
    # 相对本人保持安排的增量代价，可为负，但必须使用约定尺度且为有限数。
    delta_cost: float
    # 给别人检查兼容性的条件摘要；核心显式复制这些字段进入消息。
    public: dict
    # 只在本人安装时使用的完整响应；repr=False不会自动限制对象访问。
    private_plan: Any = field(repr=False)


# base_versions是读集合版本，updates是写集合；读集合可比写集合大。
# 例如修改交付时间还依赖准备步骤，则两者都应记版本，但只写入交付步骤。
@dataclass(frozen=True)
class PlanPatch:
    """base_versions为相关读集合，updates为写集合；无关任务不随补丁重置。"""
    # 生成补丁时读取的相关片段版本，包括只读但影响可行性的片段。
    base_versions: dict[str, int]
    # 实际覆盖的片段及新内容；没有出现在这里的任务不会被重做。
    updates: dict[str, Any]


class SegmentedPlan:
    """按任务片段维护内容与版本，支持局部乐观并发检查。"""
    # 初始化本实例的状态；self字段属于当前对象，不是所有Agent共享的全局变量。
    def __init__(self, segments):
        self.segments = copy.deepcopy(segments)
        # 把segments的每个键映射到初始版本0；不是复制计划内容，而是建立单独版本表。
        self.versions = dict.fromkeys(segments, 0)

    # 检查补丁非空、每个写入键都带读取版本、所有读取版本与当前一致。
    # 这是乐观并发控制：生成时不锁整个计划，安装前用版本发现条件是否已经变化。
    def valid(self, patch):
        # 写入前必须验证所有相关读取，而不是仅验证本次写入的片段。
        return (bool(patch.updates) and set(patch.updates) <= set(patch.base_versions)
                and all(key in self.versions and self.versions[key] == version
                        for key, version in patch.base_versions.items()))

    # 先完成整份补丁的读取版本校验，再开始写入，避免校验失败时留下部分修改。
    # 深拷贝updates后只迭代写集合，无关任务片段内容和版本都不会改变。
    def apply(self, patch):
        # 深拷贝后安装，避免调用方继续修改补丁而改变已确认的本地计划。
        if not self.valid(patch):
            raise ValueError("Local patch read/write versions are stale or incomplete")
        updates = copy.deepcopy(patch.updates)
        # items产生键值对，由左侧两个变量解包；只遍历补丁写集合，不会重置无关任务。
        for key, value in updates.items():
            self.segments[key] = value
            # 读取当前版本、加1再写回，使持有旧版本的后续补丁无法通过valid。
            self.versions[key] += 1


# 一次协商的上下文快照；参与者或约束变化时创建新key，隔离迟到的旧确认。
@dataclass(frozen=True)
class Proposal:
    """一次不可变协商快照；扩组或反馈重试必须创建新key。"""
    # 独立事务编号，扩组和反馈重试必须换编号。
    key: str
    # 本次临时发起人，并非固定中央控制器。
    owner: str
    # 创建提案时的环境轮次，与模型token数、HTTP时间无关。
    round: int
    # 候选元组；每个参与者分别对其中每一项给出本人响应。
    candidates: tuple[Candidate, ...]
    # 本事务必须响应和确认的成员集合，序列顺序用排序保持稳定。
    participants: tuple[str, ...]
    # 当前轮内尝试次数，从0开始，用于限制连续协商。
    attempt: int = 0
    # 上一轮公开冲突反馈；结构由具体任务插件解释。
    constraints: Any = None


# 承诺说明谁在指定时间窗内维持什么条件；assumptions的语义由任务插件解释。
# 时间使用左闭右开的约定：到valid_until就到期，不再允许按该承诺继续执行。
@dataclass
class Commitment:
    # 可跨版本识别同一个对外承诺的键。
    key: str
    # 承诺提供者。
    owner: str
    # 同键版本号；替换时必须严格递增。
    version: int
    # 承诺保持的具体条件，由任务定义而非核心解释。
    property: Any
    # 承诺生效的环境时刻。
    valid_from: int
    # 承诺到期的环境时刻，不包含这一时刻本身。
    valid_until: int
    # 承诺成立前提，由插件负责核验与维护。
    assumptions: Any = None
    # 生命周期状态：活动、到期、撤销、释放或被替换。
    status: str = "active"


# 把未来需要显式记录下来：consumer将在使用窗口内依赖provider的某版本承诺。
# 登记依赖不要求consumer已经开始行动，因此能表达尚未执行但已形成的需求。
@dataclass
class Dependency:
    # 依赖记录编号。
    key: str
    # 未来要使用该承诺的成员。
    consumer: str
    # 提供承诺的成员，必须匹配承诺owner。
    provider: str
    # 引用账本里的承诺键。
    commitment: str
    # 引用的承诺版本，不自动跟随提供者换版。
    version: int
    # 未来使用窗口起点，不要求当前已经开始使用。
    use_from: int
    # 使用窗口终点，必须不晚于承诺到期时刻。
    use_until: int
    # 活动依赖才参与邻居提取；invalidated会阻止使用方继续旧执行。
    status: str = "active"


class Ledger:
    """记录已知承诺与未来使用需求，不从自然语言自动推断依赖。"""
    # 初始化本实例的状态；self字段属于当前对象，不是所有Agent共享的全局变量。
    def __init__(self):
        self.commitments = {}
        self.dependencies = {}

    # 同键更新必须是原所有者的新版本；不能把旧版本记录直接覆盖成貌似仍有效。
    # 换版时让旧活动依赖失效，消费方需重新核验并登记依赖，不能自动继承新版本。
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

    # 依赖必须指向存在、活动、所有者和版本均匹配的承诺。
    # 使用窗口必须完整落在承诺有效窗口内，否则未来动作可能落到承诺不再保证的时间。
    def register_dependency(self, dependency):
        # 未来使用窗必须落在对应版本承诺的有效窗内。
        commitment = self.commitments.get(dependency.commitment)
        if (not commitment or commitment.status != "active" or commitment.owner != dependency.provider
                or commitment.version != dependency.version or dependency.use_from < commitment.valid_from
                or dependency.use_until > commitment.valid_until or dependency.use_until <= dependency.use_from):
            raise ValueError("Dependency requires a matching commitment covering its future use window")
        self.dependencies[dependency.key] = copy.deepcopy(dependency)

    # 只标记该依赖已释放，保留记录用于追踪；后续peers不会把它视为活动关系。
    def release(self, key):
        if key in self.dependencies:
            self.dependencies[key].status = "released"

    # 释放承诺时同步使活动依赖失效，避免提供方退出而消费方继续认为可用。
    def release_commitment(self, key):
        if key in self.commitments:
            self.commitments[key].status = "released"
            for dependency in self.dependencies.values():
                if dependency.commitment == key and dependency.status == "active":
                    dependency.status = "invalidated"

    # 时间推进不是重新规划：只更新承诺和依赖的生命周期状态。
    # 依赖先检查自己是否已用完；尚未用完而提供方承诺失效时才标为invalidated。
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

    # 只从活动依赖提取另一端成员；当前成员既可能是提供方，也可能是使用方。
    # 结果用集合去重并减去自己，不包括已经释放、到期或失效的关系。
    def peers(self, identity):
        return {dependency.consumer if dependency.provider == identity else dependency.provider
                for dependency in self.dependencies.values() if dependency.status == "active"
                and identity in (dependency.consumer, dependency.provider)} - {identity}

    # 先撤销指定所有者的活动承诺，再使关联活动依赖失效，以便消费方阻止过期执行。
    def revoke(self, owner):
        for commitment in self.commitments.values():
            if commitment.owner == owner and commitment.status == "active":
                commitment.status = "revoked"
        for dependency in self.dependencies.values():
            if self.commitments[dependency.commitment].status == "revoked" and dependency.status == "active":
                dependency.status = "invalidated"


# 消息信封只负责标记谁给谁发送哪类事务消息；payload内容随kind变化。
@dataclass
class Message:
    # 发送者身份，用于成员校验和事务所有者校验。
    sender: str
    # 明确的接收者，非本人消息不处理。
    receiver: str
    # 协议阶段，例如propose、respond、prepare、ready、commit。
    kind: str
    # 关联的提案编号，使并存或迟到消息不会串事务。
    proposal: str
    # 本消息内容；协议分支规定其结构。
    payload: Any


# Protocol是接口形状说明，不会自动提供实现，也不会运行时验证所有方法。
# 规则生成、约束检查与任务执行由插件实现；模型扩展接口见Agent.model_decision。
class Task(Protocol):
    """任务插件的基本契约：核心决定何时问，插件决定怎样做才可行。"""
    # 返回本人当前观察；核心不假设观察是铁路状态或语言文本。
    def observe(self) -> Any: ...
    # 判断任务是否需要普通修订；有效旧安排可直接复用，避免模型调用。
    def needs_revision(self, observation: Any) -> bool: ...
    # 规则路径生成候选；模型路径改用candidates_from_decision。
    def candidates(self, observation: Any) -> tuple[Candidate, ...]: ...
    # 规则路径生成本人的响应；模型路径改用generate_response内的模型分支。
    def respond(self, proposal: Proposal, candidate: Candidate, observation: Any) -> Response: ...
    # 只根据公开候选及各方公开响应检查组合硬约束，不生成队友私有动作。
    def compatible(self, candidate: Candidate, responses: dict[str, dict]) -> bool: ...
    # 检查补丁非空、每个写入键都带读取版本、所有读取版本与当前一致。
    # 这是乐观并发控制：生成时不锁整个计划，安装前用版本发现条件是否已经变化。
    # 核验本人的响应在当前观察和版本下仍有效；不同于跨人compatible。
    def valid(self, response: Response, observation: Any) -> bool: ...
    # 这里安装的是本人已经确认的Response，不接收也不生成队友的私有计划。
    # 必须先检查反馈边界仍在未来，再委托插件安装；缓存清空避免重用安装前的状态计算。
    # 安装本人最终确认的局部响应，任务插件决定如何应用补丁。
    def install(self, response: Response) -> None: ...
    # 识别当前安排已无法履约的紧急情况，与普通优化修订区分。
    def infeasible(self, observation: Any) -> bool: ...
    # 先撤销指定所有者的活动承诺，再使关联活动依赖失效，以便消费方阻止过期执行。
    # 撤销本人的任务安排；核心另外处理账本状态与相关方通知。
    def revoke(self, observation: Any) -> None: ...
    # 收到他人撤销后更新本地依赖条件，不代表同意任何新方案。
    def dependency_changed(self, peer: str, observation: Any) -> None: ...
    # 动作前再次读取观察和账本，避免把先前确认误当成永远有效。
    # 准备锁还在说明交换屏障未结束，此时执行会破坏确认前提，因此直接报错。
    # 原安排失效时返回插件安全动作，而不是盲目执行过期计划。
    # 返回一个近期环境动作，不在此函数中统一操纵所有成员。
    def act(self, observation: Any) -> Any: ...
    # 根据本地任务状态报告相关成员；应覆盖当前及未来依赖。
    def coordination_peers(self, proposal: Proposal | None, observation: Any) -> tuple[str, ...]: ...


# 这里列的是可选增强接口；核心多用getattr检测，插件未实现时采用默认路径。
# 存在接口不等于任务自动获得该能力，必须正确实现状态、依赖和约束语义。
class AdaptiveTask(Task, Protocol):
    """可选扩展。未实现的回调通过getattr跳过，不代表相应任务能力成立。"""
    # 为候选选择初始协调集合，应包含本人；新依赖可在响应后扩组。
    def proposal_participants(self, candidates, observation) -> tuple[str, ...]: ...
    # 将主响应扩展为有限菜单；插件实现，不保证自动再次调用模型。
    def response_options(self, proposal, candidate, observation, primary) -> list[Response]: ...
    # 尝试仅在内部完成修改，仍需外部条件不变与版本检查。
    def local_revision(self, candidates, observation) -> Response | None: ...
    # 证明本次本地修订没有改变别人可依赖的公开条件。
    def external_conditions_unchanged(self, response, observation) -> bool: ...
    # 返回下一次必须获得新反馈的环境轮次，或运行时返回None表示不设固定边界。
    def feedback_boundary(self, response, observation) -> int: ...
    # 补充任务层的当前执行有效性条件；不是对整段未来的安全证明。
    def execution_valid(self, observation) -> bool: ...
    # 核心不懂不同任务里什么动作才安全，必须由任务插件提供。
    # 缺少实现明确报错，不能默认把某个数值当停止动作，也不保证安全动作一定能完成任务。
    # 旧安排不可执行时返回任务专属安全动作，不能任意猜一个停止编号。
    def safe_action(self, observation) -> Any: ...
    # 声明影响本地响应的状态标记；漏掉关键状态可能导致错误缓存复用。
    def evaluation_key(self, proposal, candidate, observation) -> Any: ...
    # 追加由本人生成的局部修复响应，不修改队友私有任务。
    def repair_options(self, proposal, candidate, observation, primary) -> list[Response]: ...
    # 依据公开失败报告生成下一轮约束；None表示暂不立即重开。
    def negotiation_constraints(self, proposal, reports, reason) -> Any: ...
    # 返回本人已知承诺及依赖，用于同步账本；核心不自动理解自然语言依赖。
    def commitment_records(self, observation) -> tuple[list[Commitment], list[Dependency]]: ...
    # 在生成本地响应后报告新影响的第三方，用来触发连锁扩组。
    def response_dependencies(self, proposal, candidate, response, observation) -> tuple[str, ...]: ...


# 传输层不制定计划，只接收和投递Message；可靠同步投递由当前实验驱动保证。
class Transport(Protocol):
    # 只在respond且启用delta_messages时尝试差量；其他消息保持原样。
    # 差量基于发给同一接收者的上一版公开内容；字典副本隔离后续原地修改。
    # 是否较短按JSON字符串长度判断，不等于UTF-8网络字节；完整报文也附版本供下一次对齐。
    # 将一条消息加入指定接收者的传输通道，不直接执行对方私有方法。
    def send(self, message: Message) -> None: ...
    # 取出指定成员的待收消息；收件箱管理由传输实现负责。
    def receive(self, receiver: str) -> list[Message]: ...


# 时钟分隔协商阶段和行动阶段；exchange必须把准备/提交处理完成再让环境推进。
class Clock(Protocol):
    # 环境是否已经结束，不是某次事务是否取消。
    def finished(self) -> bool: ...
    # 返回当前环境逻辑轮次，供有效期、轮换及事务编号使用。
    def round(self) -> int: ...
    # 处理消息至同步确认完成；不能在准备锁仍存在时推进动作。
    def exchange(self, agent: Any) -> None: ...
    # 把本人的动作交给环境；多成员动作同步由具体时钟实现负责。
    def execute(self, identity: str, action: Any) -> None: ...


# 循环主线是本轮决策、消息交换、近期行动，而不是每轮都重新调用模型。
# 实际是否生成方案由start的条件检查决定；finished由环境定义，不以一次事务取消判断任务结束。
def run_agent(agent: Any, clock: Clock):
    """观察/决策→同步交换至结束→近期动作；exchange须落实提交屏障。"""
    # while重复缩进块；not对结束条件取反，所以环境未结束时才继续。
    while not clock.finished():
        agent.step(clock.round())
        clock.exchange(agent)
        clock.execute(agent.identity, agent.act())


class Agent:
    """每个成员运行同一类；发起者只是本次提案的临时组合选择者。"""
    # 初始化本实例的状态；self字段属于当前对象，不是所有Agent共享的全局变量。
    def __init__(self, identity: str, members: tuple[str, ...], task: Task, transport: Transport, task_group: tuple[str, ...] | None = None, max_negotiation_rounds=3, delta_messages=False, decision_model=None):
        if len(set(members)) < 3 or len(set(members)) != len(members) or identity not in members:
            raise ValueError("Distributed experiment requires at least three distinct agents")
        self.identity = identity
        # sorted先稳定排序，再用tuple转为不可增删的序列，保证成员轮换顺序一致。
        self.members = tuple(sorted(members))
        self.task_group = tuple(sorted(task_group if task_group is not None else members))
        if identity not in self.task_group or not set(self.task_group) <= set(members):
            raise ValueError("Task group must contain self and only known members")
        self.task = task
        self.transport = transport
        # 按提案key保存本人的主响应；不是其他成员的私有计划总表。
        self.local = {}
        # 保存本成员已知提案，供后续消息核验owner与participants。
        self.proposals = {}
        # 仅发起方用此表收集公开响应：提案key → 成员编号 → 候选响应。
        self.responses = {}
        # 记录各参与者对prepare的布尔确认；只有收齐且全真才能commit。
        self.ready = {}
        # 保存本成员已二次核验、等待最终决定的私有Response。
        self.prepared = {}
        # 事务结束编号用于忽略迟到的普通消息，避免旧确认重新触发安装。
        self.final = set()
        self.sequence = 0
        self.trace = []
        # None表示未准备锁定；否则保存锁所属提案编号，禁止协商中行动。
        self.locked = None
        # 记录因撤销或新依赖而不能再批准的旧提案。
        self.blocked = set()
        self.started_round = None
        if max_negotiation_rounds < 1:
            raise ValueError("Negotiation rounds must be positive")
        self.max_negotiation_rounds = max_negotiation_rounds
        self.delta_messages = delta_messages
        self.sent_public = {}
        self.received_public = {}
        # 可选响应缓存；只有插件提供evaluation_key且响应仍valid才复用。
        self.evaluations = {}
        self.ledger = Ledger()
        # None表示未设置固定反馈边界，不表示跳过其他执行有效性检查。
        self.execute_until = None
        self.active_round = 0
        # 没有待处理修订时为None；否则是上次参与者与约束组成的二元组。
        self.pending_revision = None
        # 显式注入模型对象；None保留规则基线，非None进入模型候选/响应流程。
        # 防止重复响应或确认导致同一事务重复发出决定；不替代接收时的锁清理。
        self.decided = set()
        self.decision_model = decision_model

    # stage区分revise候选请求和respond本人配合响应；details携带候选、提案或错误。
    # 先让插件选择本人可见信息并变成可序列化上下文，再调用注入的模型客户端。
    # 这些模型插件方法目前未声明在Task Protocol里；缺少实现会报AttributeError，不会静默走规则。
    def model_decision(self, stage, observation, **details):
        """插件整理本人的任务输入，模型负责产生结构化决策。"""
        # details由**关键字参数收集为字典，这里再按名称展开给插件。插件只组织本人可见信息。
        context = self.task.decision_context(stage, observation, **details)
        return self.decision_model.decide(self.identity, stage, context)

    # 模型与规则路径在此分流；调用者始终是当前成员自己的Agent实例。
    # 三次预算覆盖模型JSON格式/类型错误、输出转换和本地valid检查；网络异常仍直接上抛。
    # 响应即使本地valid，仍需发起方compatible检查跨成员条件，不能直接安装。
    def generate_response(self, proposal, candidate, observation):
        """本人生成响应；非法输出反馈重试，不替队友规划、不静默回退。"""
        # is None判断没有注入模型对象，不是判断某次模型回答为空；该分支保留规则基线。
        if self.decision_model is None:
            return self.task.respond(proposal, candidate, observation)
        # 创建本次生成专用的错误列表，下一次调用携带它让模型修正；不是完整对话历史。
        errors = []
        # range(3)依次产生0、1、2，最多尝试三次；日志attempt=2表示第三次。
        for attempt in range(3):
            try:
                decision = self.model_decision("respond", observation, proposal=proposal,
                                               candidate=candidate, errors=errors)
                response = self.task.response_from_decision(decision, proposal, candidate, observation)
                if not self.task.valid(response, observation):
                    raise ValueError("Response no longer valid")
                self.trace.append({"event": "model_response", "attempt": attempt, "proposal": proposal.key})
                return response
            # 仅捕捉值不合法、缺字段、类型错误；as把异常对象保存到error供下面提取文字。
            except (ValueError, KeyError, TypeError) as error:
                # str把异常转成可序列化文本；append追加错误，不覆盖此前尝试的原因。
                errors.append(str(error))
        raise RuntimeError("Model failed response validation after three attempts; no rule substitution")

    # 当前失败只结束旧提案，不清空整个任务；让插件根据公开报告给出下一轮约束。
    # 有新约束且还有轮内次数时立即重开事务，否则保留参与者与约束，等后续观察轮重试。
    # 不能为了保证提交而选择违反硬约束的组合；没有可行解时允许继续安全等待。
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

    # 先按当前轮次推进到期状态，再读取任务插件提供的承诺/依赖快照。
    # 只接纳新键或严格更高版本，避免同版本重复同步复活已经撤销或失效的记录。
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

    # 这里安装的是本人已经确认的Response，不接收也不生成队友的私有计划。
    # 必须先检查反馈边界仍在未来，再委托插件安装；缓存清空避免重用安装前的状态计算。
    def install(self, response, observation):
        """安装本人已确认响应，并刷新反馈边界和本地依赖记录。"""
        callback = getattr(self.task, "feedback_boundary", None)
        boundary = callback(response, observation) if callback else None
        if boundary is not None and boundary <= self.active_round:
            raise ValueError("Feedback boundary must be in the future")
        self.task.install(response)
        self.execute_until = boundary
        # 原地清空响应缓存，防止计划已修改后复用安装前计算的旧响应。
        self.evaluations.clear()
        self.sync_records(self.task.observe())

    # 紧急情况优先撤销自己的履约保证，不等待多数同意，否则别人可能继续依赖已失效条件。
    # 先找相关方再撤销账本，避免撤销后peers查不到原活动关系；缺少信息时保守通知任务组。
    def emergency(self, observation):
        """不可履约时先撤销，再通知相关方，不等待队友批准。"""
        self.sync_records(observation)
        callback = getattr(self.task, "coordination_peers", None)
        peers = self.ledger.peers(self.identity) | self.related(None, observation)
        if callback is None and not self.ledger.commitments:
            peers |= set(self.task_group)
        self.ledger.revoke(self.identity)
        self.task.revoke(observation)
        # None表示未设置固定反馈边界，不表示跳过其他执行有效性检查。
        self.execute_until = None
        # 原地清空响应缓存，防止计划已修改后复用安装前计算的旧响应。
        self.evaluations.clear()
        # 集合减法去掉本人；通知相关方不是直接调用他们的私有规划函数。
        for peer in peers - {self.identity}:
            self.send(peer, "revoke", f"revoke:{self.identity}:{self.active_round}", None)

    # 核心不懂不同任务里什么动作才安全，必须由任务插件提供。
    # 缺少实现明确报错，不能默认把某个数值当停止动作，也不保证安全动作一定能完成任务。
    def safe_action(self, observation):
        callback = getattr(self.task, "safe_action", None)
        if callback is None:
            raise RuntimeError("Expired execution requires task.safe_action")
        return callback(observation)

    # 返回的是多个必要条件的逻辑与：任务执行条件、反馈期限、自身承诺、输入依赖都要满足。
    # all遍历本人尚需检查的承诺，any查找本人消费的失效依赖；空集合分别得到True和False。
    def execution_allowed(self, observation):
        callback = getattr(self.task, "execution_valid", None)
        return ((callback is None or callback(observation))
                and (self.execute_until is None or self.active_round < self.execute_until)
                and all(commitment.status == "active" for commitment in self.ledger.commitments.values()
                        if commitment.owner == self.identity and commitment.status not in ("released", "replaced", "revoked"))
                and not any(dependency.consumer == self.identity and dependency.status == "invalidated"
                            for dependency in self.ledger.dependencies.values()))

    # 将插件从具体任务识别的邻居与账本中的活动依赖邻居取并集，防止只看其中一个来源。
    # 集合子集检查约束所有编号来自已知成员；这里不自动推断未报告的语义依赖。
    def related(self, proposal, observation):
        callback = getattr(self.task, "coordination_peers", None)
        peers = (set(callback(proposal, observation)) if callback else set()) | self.ledger.peers(self.identity)
        if not peers <= set(self.members):
            raise ValueError("Dependency peer must be a known member")
        return peers

    # sequence是本人递增序号，结合轮次和身份构成事务key，避免重试与旧消息混淆。
    # 建立responses空表表示本人开始收集本事务响应；propose也投递给本人，以同一协议处理自身响应。
    def launch(self, round, candidates, participants, attempt=0, constraints=None):
        """创建新提案；不复用旧key，防止旧确认批准新参与集合。"""
        self.sequence += 1
        # f字符串把表达式值插入文本，例如12:A:3，用于区分并存与迟到的事务消息。
        key = f"{round}:{self.identity}:{self.sequence}"
        proposal = Proposal(key, self.identity, round, candidates, tuple(sorted(participants)), attempt, constraints)
        self.proposals[key] = proposal
        self.responses[key] = {}
        self.broadcast("propose", key, proposal)

    # 只在respond且启用delta_messages时尝试差量；其他消息保持原样。
    # 差量基于发给同一接收者的上一版公开内容；字典副本隔离后续原地修改。
    # 是否较短按JSON字符串长度判断，不等于UTF-8网络字节；完整报文也附版本供下一次对齐。
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

    # 这里的广播范围是本事务participants；没有事务上下文时才退回task_group。
    # 循环调用send复用版本编码与投递逻辑，不是直接调用远端Agent的方法。
    def broadcast(self, kind, proposal, payload):
        scope = self.proposals[proposal].participants if proposal in self.proposals else self.task_group
        # 按事务参与集合逐个投递，集合包含本人时也投递给自己，使用同一消息处理流程。
        for peer in scope:
            self.send(peer, kind, proposal, payload)

    # 这是每轮发起入口：先排除重复轮次、故障、准备锁和无需修订的有效安排。
    # 模型路径先检查轮换再付模型调用成本；规则路径允许先生成本地候选再检查轮换。
    # 内部修订要同时满足外部条件不变与版本有效；否则选择相关参与者后启动消息协调。
    def start(self, round):
        """检查条件；可内部处理则不通信，否则按轮换发起局部协商。"""
        # 同轮入口去重；驱动反复调用也不重复支付模型调用或重复发提案。
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
        # is None判断没有注入模型对象，不是判断某次模型回答为空；该分支保留规则基线。
        if self.decision_model is None:
            candidates = self.task.candidates(observation)
        else:
            # %取除法余数作为组内位置，例如5%3=2；本轮只有对应成员获得发起机会。
            if self.task_group[round % len(self.task_group)] != self.identity:
                return
            # 创建本次生成专用的错误列表，下一次调用携带它让模型修正；不是完整对话历史。
            errors = []
            # range(3)依次产生0、1、2，最多尝试三次；日志attempt=2表示第三次。
            for attempt in range(3):
                try:
                    decision = self.model_decision("revise", observation, errors=errors)
                    candidates = self.task.candidates_from_decision(decision, observation)
                    # 跳出当前循环；若对应for后有else，成功break也会跳过该else错误处理。
                    break
                # 仅捕捉值不合法、缺字段、类型错误；as把异常对象保存到error供下面提取文字。
                except (ValueError, KeyError, TypeError) as error:
                    # str把异常转成可序列化文本；append追加错误，不覆盖此前尝试的原因。
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
        # %取除法余数作为组内位置，例如5%3=2；本轮只有对应成员获得发起机会。
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
            # 没有待处理修订时为None；否则是上次参与者与约束组成的二元组。
            self.pending_revision = None
        self.launch(round, candidates, participants, constraints=constraints)

    # 消息状态机一次只处理一条消息；不同成员通过传输层串起多个阶段，不共享私有响应对象。
    # 分支顺序重要：差量先恢复完整响应，撤销优先处理，已结束事务的迟到普通消息随后过滤。
    # propose生成响应；respond汇总组合；prepare/ready/commit保证各自二次核验后再安装。
    def think(self, message):
        """消息状态机：提案→各自响应→组合→准备→提交，失败则中止。"""
        if message.sender not in self.members or message.receiver != self.identity:
            return
        observation = self.task.observe()
        key = message.proposal
        # 先按基版本重建完整公开响应，后续统一进入respond分支，避免两套组合逻辑。
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
                # 先复制上一完整公开版本，再应用差量；差量信封本身不能直接当完整响应。
                payload = copy.deepcopy(previous[1])
                for removed in envelope["removed"]:
                    # pop删除字段；默认值None使字段已不存在时不抛KeyError。
                    payload.pop(removed, None)
                payload.update(copy.deepcopy(envelope["changed"]))
            self.received_public[message.sender] = (envelope["version"], payload)
            message = Message(message.sender, message.receiver, "respond", key, payload)
        # 撤销不等于批准新方案：先失效依赖，再通知任务插件并取消相关未结束事务。
        if message.kind == "revoke":
            self.ledger.revoke(message.sender)
            # 原地清空响应缓存，防止计划已修改后复用安装前计算的旧响应。
            self.evaluations.clear()
            self.task.dependency_changed(message.sender, observation)
            for proposal_key, proposal in list(self.proposals.items()):
                if proposal_key not in self.final and message.sender in proposal.participants:
                    self.blocked.add(proposal_key)
                    self.send(proposal.owner, "cancel", proposal_key, None)
            return
        # 旧事务已结束时忽略迟到消息；revoke在此前处理，因此不受此过滤限制。
        if key in self.final:
            return
        # 收到提案并不立即安装；先由本人生成和保存响应，等待prepare再次核验。
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
                self.blocked.add(key)
                self.send(proposal.owner, "expand", key, tuple(sorted(extra)))
                return
            evaluated = {}
            generated = {}
            cache_key = getattr(self.task, "evaluation_key", None)
            repairs = getattr(self.task, "repair_options", None)
            alternatives = getattr(self.task, "response_options", None)
            for candidate in proposal.candidates:
                token = cache_key(proposal, candidate, observation) if cache_key else None
                signature = repr((token, candidate.key, candidate.public, proposal.owner,
                                  proposal.participants, proposal.constraints)) if token is not None else None
                # 无可用状态签名就不缓存；None不是所有状态共享的缓存键。
                cached = self.evaluations.get(signature) if signature is not None else None
                # 命中键后仍逐项核验当前版本，避免缓存绕过时效性检查。
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
                        # 删除最先插入项以控制内存；这不是按最近访问更新的LRU策略。
                        if len(self.evaluations) >= 256:
                            # iter遍历字典插入顺序，next取首项，pop删除；这是先进先出淘汰而非LRU。
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
            # 延迟创建本地完整菜单表；已存在则复用旧字典，不覆盖其他事务。
            self.alternatives = getattr(self, "alternatives", {})
            self.alternatives[key] = generated
            if any(not math.isfinite(response.delta_cost) for response in evaluated.values()):
                raise ValueError("Each agent must report a finite own incremental cost")
            self.local[key] = evaluated
            # 在此显式构造公开字段，private_plan不会自动序列化进消息。
            public = {candidate: {"feasible": response.feasible, "delta_cost": response.delta_cost,
                                  "public": response.public, "cost_owner": self.identity}
                      for candidate, response in evaluated.items()}
            for candidate, options in self.alternatives[key].items():
                public[candidate]["options"] = [
                    {"feasible": option.feasible, "delta_cost": option.delta_cost,
                     "public": option.public, "cost_owner": self.identity, "option": index}
                    for index, option in enumerate(options)]
            self.send(proposal.owner, "respond", key, public)
        # 扩组只能由当前参与者提出；旧事务取消后，用扩大集合与新key重发相同候选。
        elif message.kind == "expand" and key in self.responses:
            proposal = self.proposals[key]
            if message.sender not in proposal.participants:
                return
            extra = set(message.payload) - set(proposal.participants)
            if not extra or not extra <= set(self.members):
                return
            self.broadcast("abort", key, None)
            # 标记旧事务结束，迟到普通消息不能再次提交同一个局部方案。
            self.decided.add(key)
            self.launch(proposal.round, proposal.candidates, set(proposal.participants) | extra,
                        proposal.attempt, proposal.constraints)
        # 参与者取消仅结束旧事务；此分支不自动调用continue_coordination。
        elif message.kind == "cancel" and key in self.responses:
            if message.sender in self.proposals[key].participants:
                self.broadcast("abort", key, None)
        # 只收当前参与者公开响应；候选集合和cost_owner必须匹配，代价必须有限。
        elif message.kind == "respond" and key in self.responses:
            if key in self.ready or key in self.decided:
                return
            if message.sender not in self.proposals[key].participants:
                return
            expected = {candidate.key for candidate in self.proposals[key].candidates}
            if set(message.payload) != expected or any(
                    reply.get("cost_owner") != message.sender
                    or not math.isfinite(reply["delta_cost"])
                    for reply in message.payload.values()):
                self.broadcast("abort", key, None)
                return
            # 按事务和成员两层索引存公开答复；重复消息覆盖同一槽，不会冒充更多人回复。
            self.responses[key][message.sender] = message.payload
            # 字典转集合得到成员键，必须与参与者集合完全相等，不能只数消息条数。
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
                # 生成(0,0,...)作为初始组合，各位置对应一个成员菜单中的最低代价项。
                initial = tuple(0 for peer in peers)
                queue = [(sum(menu[0]["delta_cost"] for menu in menus), initial)]
                seen = {initial}
                checked = 0
                # 最小堆每次取当前低代价组合；128是搜索预算，预算外存在可行解也可能没找到。
                while queue and checked < 128:
                    # 从最小堆取当前最小总代价组合并解包；不是一次遍历所有笛卡尔积组合。
                    cost, indices = heapq.heappop(queue)
                    reports = {peer: menus[index][indices[index]] for index, peer in enumerate(peers)}
                    checked += 1
                    if self.task.compatible(candidate, reports):
                        selection = {peer: report["option"] for peer, report in reports.items()}
                        feasible.append((cost, candidate.key, selection))
                        self.trace.append({"proposal": key, "event": "combination_found", "candidate": candidate.key,
                                           "combinations_checked": checked, "cost": cost, "selection": selection})
                        # 跳出当前循环；若对应for后有else，成功break也会跳过该else错误处理。
                        break
                    # 邻居组合每次仅增加一个人的菜单下标；seen避免同一组合重复入堆。
                    for index, menu in enumerate(menus):
                        # 元组不可修改，先转列表改一位，再转回可哈希元组，才能加入seen集合。
                        neighbor = list(indices)
                        # 只尝试把一个成员切换到下一个菜单选项，其余成员保持，形成邻接组合。
                        neighbor[index] += 1
                        neighbor = tuple(neighbor)
                        if neighbor[index] < len(menu) and neighbor not in seen:
                            # 入队前记录见过的组合，避免不同路径重复加入相同组合浪费搜索预算。
                            seen.add(neighbor)
                            heapq.heappush(queue, (sum(menus[position][value]["delta_cost"]
                                                      for position, value in enumerate(neighbor)), neighbor))
                self.trace.append({"proposal": key, "event": "combination_search", "candidate": candidate.key,
                                   "checked": checked, "limit": 128})
                exhausted = exhausted or bool(queue and checked >= 128)
            # 没有候选找到相容组合，撤销旧事务并尝试带新反馈继续，不以碰撞换提交。
            if not feasible:
                self.broadcast("abort", key, None)
                reason = "budget_exhausted" if exhausted else "menu_exhausted"
                self.trace.append({"proposal": key, "event": "no_combination", "reason": reason})
                self.continue_coordination(proposal, reason)
                return
            # 先比总代价再比候选键，得到稳定的同成本选择；不是生成队友行动链。
            _, chosen, selection = min(feasible, key=lambda item: (item[0], item[1]))
            self.trace.append({"proposal": key, "event": "selected_combination", "candidate": chosen,
                               "selection": selection,
                               "uses_alternative": any(index > 0 for index in selection.values())})
            self.ready[key] = {}
            for peer in proposal.participants:
                self.send(peer, "prepare", key, {"candidate": chosen, "option": selection[peer]})
        # 发起方只发候选及本人选项编号；本成员从本地菜单取回完整私有方案。
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
        # 把同一参与者的确认保存在同一个字典键上；集合相等才表示所有人已回复。
        elif message.kind == "ready" and key in self.ready:
            if key in self.decided:
                return
            if message.sender not in self.proposals[key].participants:
                return
            self.ready[key][message.sender] = message.payload
            if set(self.ready[key]) == set(self.proposals[key].participants):
                # 条件表达式在全员确认值均真时才提交；一人拒绝则取消旧事务，不允许代价抵消硬条件。
                decision = "commit" if all(self.ready[key].values()) else "abort"
                self.decided.add(key)
                self.broadcast(decision, key, None)
                if decision == "abort":
                    self.continue_coordination(self.proposals[key], "preparation_invalidated")
        # commit和abort都清理准备状态及锁；只有commit调用本地install。
        elif message.kind in ["commit", "abort"] and key in self.proposals:
            if message.sender != self.proposals[key].owner:
                return
            if message.kind == "commit":
                candidate = self.prepared.get(key)
                if candidate is None:
                    raise RuntimeError("Commit without locally prepared response")
                self.install(candidate, observation)
            # 清理本事务准备结果；默认None允许未准备的abort也能安全清理。
            self.prepared.pop(key, None)
            if self.locked == key:
                # None表示未准备锁定；否则保存锁所属提案编号，禁止协商中行动。
                self.locked = None
            # 标记旧事务结束，迟到普通消息不能再次提交同一个局部方案。
            self.final.add(key)
            self.trace.append({"proposal": key, "decision": message.kind})

    # 保留一个简洁的驱动入口；真正的判断集中在start，方便不同环境复用。
    def step(self, round):
        self.start(round)

    # 一次取出本成员当前收件箱，逐条进入think；新产生消息是否立即处理由交换驱动决定。
    def communicate(self):
        for message in self.transport.receive(self.identity):
            self.think(message)

    # 动作前再次读取观察和账本，避免把先前确认误当成永远有效。
    # 准备锁还在说明交换屏障未结束，此时执行会破坏确认前提，因此直接报错。
    # 原安排失效时返回插件安全动作，而不是盲目执行过期计划。
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
