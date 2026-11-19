import asyncio
from datetime import datetime
import importlib.metadata
import json
from pathlib import Path
from typing import Literal

import run as shared
from compare import ComparisonTask
from agent import Agent
from demo import Mailbox, run_round
from llm import OllamaDecisionModel
from tools import ToolRuntime, ToolSpec, ToolResult
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.messages import StructuredMessage
from autogen_ext.models.openai import OpenAIChatCompletionClient
from pydantic import create_model
from telemetry import EventLog, LoggedTransport


class SharedModel:
    def __init__(self, client, event_log=None):
        self.client = client
        self.calls = client.calls
        self.loop = asyncio.get_running_loop()
        self.event_log = event_log

    def decide(self, identity, stage, context):
        from autogen_core.models import SystemMessage, UserMessage
        schema = context['output_schema']
        field, specification = next(iter(schema['properties'].items()))
        output = create_model('ProtocolDecision', **{field: (Literal[tuple(specification['enum'])], ...)})
        messages = [SystemMessage(content='Decide only your own work. Return required JSON.'),
                    UserMessage(content=json.dumps(dict(identity=identity, stage=stage, **context)), source='task')]
        result = asyncio.run_coroutine_threadsafe(self.client.create(messages, json_output=output), self.loop).result()
        if self.event_log:
            self.event_log.emit('model_decision', agent=identity, stage=stage,
                                content=result.content, context=context)
        return json.loads(result.content)


INITIAL = dict(collect=('0', ()), analyse=('1', ('collect',)),
               publish=('2', ('analyse',)), reference=('3', ()))


class DynamicTask(ComparisonTask):
    def proposal_participants(self, candidates, observation):
        if self.periodic:
            return tuple(sorted({owner for owner, dependencies in shared.JOBS.values()}))
        owners = {'0'}
        for name, (owner, dependencies) in shared.JOBS.items():
            if name not in self.runtime.artifacts and name not in self.runtime.pending:
                if all(task in self.runtime.artifacts for task in dependencies):
                    owners.add(owner)
        return tuple(sorted(owners))


class LoggedClient(OpenAIChatCompletionClient):
    def __init__(self):
        super().__init__(model='qwen2.5:1.5b', base_url='http://localhost:11434/v1', api_key='ollama',
                         model_info=dict(vision=False, function_calling=False, json_output=True,
                                         family='unknown', structured_output=True),
                         temperature=0, max_tokens=256, max_retries=0, timeout=180)
        self.calls = []

    async def create(self, messages, **kwargs):
        record = dict(request=[message.model_dump() for message in messages])
        self.calls.append(record)
        try:
            result = await super().create(messages, **kwargs)
            record.update(response=result.model_dump(), input_tokens=result.usage.prompt_tokens,
                          output_tokens=result.usage.completion_tokens)
            return result
        except Exception as error:
            record['error'] = repr(error)
            raise


async def external_round(tasks, client):
    assistants = []
    output_types = []
    for task in tasks:
        context = task.decision_context('respond', task.observe(), errors=[])
        choices = context['output_schema']['properties']['job']['enum']
        output = create_model('Decision' + task.identity, job=(Literal[tuple(choices)], ...))
        output_types.append(output)
        assistants.append(AssistantAgent('owner_' + task.identity, client,
                          output_content_type=output,
                          system_message='Decide only your own work. Return the required JSON. ' + json.dumps(context)))
    team = RoundRobinGroupChat(assistants, max_turns=len(tasks),
                              custom_message_types=[StructuredMessage[output] for output in output_types])
    result = await team.run(task='Coordinate next work using the supplied completed-state snapshot. Do not assume requests are completed.')
    for message in result.messages:
        if message.source.startswith('owner_'):
            identity = message.source.removeprefix('owner_')
            task = tasks[int(identity)]
            content = message.content.model_dump() if hasattr(message.content, 'model_dump') else json.loads(message.content)
            response = task.response_from_decision(content, None, None, task.observe())
            task.install(response)
    return {task.identity: task.act(task.observe()) for task in tasks}


async def execute(method, configuration, target, dynamic_event=True, member_count=4):
    shared.JOBS.clear()
    shared.JOBS.update(INITIAL)
    if member_count == 3:
        shared.JOBS['reference'] = ('0', ())
    initial_jobs = dict(shared.JOBS)
    members = tuple(str(index) for index in range(member_count))
    durations = dict(collect=3, analyse=4 + configuration, publish=2, reference=9, verify=2 + configuration)
    tools = [ToolSpec(name, frozenset([owner]), lambda inputs, duration=durations[name]:
                     ToolResult(dict(inputs=sorted(inputs)), duration))
             for name, (owner, dependencies) in dict(initial_jobs, verify=('1', ('collect',))).items()]
    runtime = ToolRuntime(tools)
    label = method + '-' + str(configuration)
    event_log = EventLog(target / label / 'events.jsonl')
    mailbox = Mailbox()
    transport = LoggedTransport(mailbox, event_log)
    client = LoggedClient()
    model = SharedModel(client, event_log)
    tasks = [DynamicTask(identity, runtime, method != 'local') for identity in members]
    agents = [Agent(task.identity, members, task, transport, decision_model=model) for task in tasks]
    rows = []
    error = None
    try:
        for now in range(32):
            event_log.emit('round', time=now)
            changed = dynamic_event and now == 2
            if changed:
                shared.JOBS['verify'] = ('1', ('collect',))
                shared.JOBS['publish'] = ('2', ('analyse', 'verify'))
                event_log.emit('dependency_change', time=now, jobs=shared.JOBS)
            if method == 'autogen':
                actions = await external_round(tasks, client) if now % 4 == 0 else {}
            else:
                actions = await asyncio.to_thread(run_round, agents, mailbox, now)
            submitted = []
            for identity, action in actions.items():
                if action:
                    receipt = runtime.submit(identity, action)
                    submitted.append(receipt.__dict__)
                    event_log.emit('tool', agent=identity, time=now, action=action, status=receipt.status, receipt=receipt)
            events = runtime.advance()
            for event in events:
                event_log.emit('tool', agent=shared.JOBS[event.task_id][0], time=now,
                               status=event.status, task_id=event.task_id)
            event_log.emit('snapshot', time=now, running=list(runtime.pending), completed=list(runtime.artifacts))
            rows.append(dict(time=now, dependency_changed=changed, submitted=submitted,
                             completed=[event.task_id for event in events],
                             versions={task.identity: task.plan.versions['shared'] for task in tasks}))
            if len(runtime.artifacts) == len(shared.JOBS):
                break
    except Exception as failure:
        error = repr(failure)
        import traceback
        event_log.emit('error', error=error, traceback=traceback.format_exc())
    finally:
        calls = client.calls
        row = dict(method=method, configuration=configuration, success=len(runtime.artifacts) == len(shared.JOBS),
                   error=error, makespan=runtime.tick, calls=len(calls),
                   input_tokens=sum(call.get('input_tokens', call.get('response', {}).get('prompt_eval_count', 0)) for call in calls),
                   output_tokens=sum(call.get('output_tokens', call.get('response', {}).get('eval_count', 0)) for call in calls),
                   protocol_messages=len(mailbox.messages), trajectory=rows,
                   artifacts=runtime.artifacts, trace={agent.identity: agent.trace for agent in agents})
        label = method + '-' + str(configuration)
        (target / (label + '-calls.json')).write_text(json.dumps(calls, indent=2), encoding='utf-8')
        (target / (label + '-result.json')).write_text(json.dumps(row, indent=2), encoding='utf-8')
        if client:
            await client.close()
    return row


async def main():
    target = shared.ROOT / 'dynamic_runs' / datetime.now().strftime('%Y%m%d-%H%M%S')
    target.mkdir(parents=True)
    for name in ('dynamic.py', 'run.py', 'compare.py'):
        (target / name).write_bytes((shared.ROOT / name).read_bytes())
    for name in ('agent.py', 'tools.py', 'llm.py'):
        (target / name).write_bytes((shared.CORE / name).read_bytes())
    (target / 'resource_plugin.py').write_bytes(Path(shared.plugin.__file__).read_bytes())
    (target / 'manifest.json').write_text(json.dumps(dict(packages={name: importlib.metadata.version(name)
            for name in ('autogen-agentchat', 'autogen-ext')}, model='qwen2.5:1.5b',
            external='Microsoft AutoGen official RoundRobinGroupChat; task adapter, not original paper task reproduction',
            limitations='All methods share OpenAI-compatible transport, temperature0, max_tokens256; AutoGen team reset each decision epoch; prompts and histories differ by framework'), indent=2), encoding='utf-8')
    results = []
    for configuration in range(2):
        for method in (('local', 'global', 'autogen') if configuration == 0 else ('autogen', 'global', 'local')):
            row = await execute(method, configuration, target)
            results.append(row)
            (target / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
            print({key: row[key] for key in ('method', 'configuration', 'success', 'makespan', 'calls', 'error')}, flush=True)
    print(target, flush=True)


if __name__ == '__main__':
    asyncio.run(main())
