from dataclasses import dataclass
import copy


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    task_id: str
    tool: str
    requires: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolResult:
    outputs: dict
    duration: int = 1


@dataclass(frozen=True)
class ToolSpec:
    name: str
    actors: frozenset[str]
    handler: object


@dataclass(frozen=True)
class Receipt:
    task_id: str
    status: str
    missing: tuple[str, ...] = ()
    detail: str = ''


class ToolRuntime:
    def __init__(self, tools):
        self.tools = {}
        for tool in tools:
            if tool.name in self.tools:
                raise ValueError('duplicate tool')
            self.tools[tool.name] = tool
        self.artifacts = {}
        self.pending = {}
        self.accepted = {}
        self.tick = 0

    def capabilities(self, actor):
        return sorted(name for name, tool in self.tools.items() if actor in tool.actors)

    def submit(self, actor, call):
        if call.call_id in self.accepted:
            if self.accepted[call.call_id] != (actor, call):
                raise ValueError('call id reused with different work')
            return Receipt(call.task_id, 'duplicate')
        tool = self.tools.get(call.tool)
        if tool is None or actor not in tool.actors:
            return Receipt(call.task_id, 'unavailable')
        if call.task_id in self.artifacts or call.task_id in self.pending:
            return Receipt(call.task_id, 'duplicate')
        missing = tuple(name for name in call.requires if name not in self.artifacts)
        if missing:
            return Receipt(call.task_id, 'blocked', missing)
        if any(owner == actor for owner, _, _ in self.pending.values()):
            return Receipt(call.task_id, 'busy')
        try:
            inputs = copy.deepcopy({name: self.artifacts[name] for name in call.requires})
            result = tool.handler(inputs)
            if not isinstance(result, ToolResult) or not isinstance(result.outputs, dict):
                raise ValueError('handler must return ToolResult with dict outputs')
            if type(result.duration) is not int or result.duration < 1:
                raise ValueError('duration must be a positive integer')
            result = copy.deepcopy(result)
        except Exception as error:
            return Receipt(call.task_id, 'failed', detail=str(error))
        self.accepted[call.call_id] = (actor, call)
        self.pending[call.task_id] = (actor, self.tick + result.duration, result)
        return Receipt(call.task_id, 'running')

    def advance(self):
        self.tick += 1
        events = []
        for task_id, (actor, due, result) in list(self.pending.items()):
            if due <= self.tick:
                self.artifacts[task_id] = result.outputs
                del self.pending[task_id]
                events.append(Receipt(task_id, 'completed'))
        return events
