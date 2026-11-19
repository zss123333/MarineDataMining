import argparse
import asyncio
from datetime import datetime
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import sys
import urllib.request

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_ext.models.openai import OpenAIChatCompletionClient

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('resource', ROOT.parent / '011-llm-coordination/run.py')
resource = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resource)


def problem(phase):
    return {'jobs': {str(index): [{'resource': 'prep', 'duration': 1 + index % 2, 'release': index % 2},
                                {'resource': 'finish', 'duration': 2, 'release': 0}] for index in range(3)},
            'dependencies': [['0:0', '1:1'], ['1:0', '2:1']], 'horizon': 24,
            'closures': {'finish': [[3, 9]] if phase else []}}


def validate(task, plans, complete=True):
    errors, intervals = [], []
    for owner, starts in plans.items():
        if owner not in task['jobs'] or not isinstance(starts, list) or len(starts) != 2 or any(type(value) is not int for value in starts):
            errors.append(f'{owner}: expected two integer start times')
            continue
        jobs = task['jobs'][owner]
        for index, (start, job) in enumerate(zip(starts, jobs)):
            end = start + job['duration']
            if start < job['release'] or end > task['horizon']:
                errors.append(f'{owner}:{index}: release or horizon violation')
            if index and start < starts[index-1] + jobs[index-1]['duration']:
                errors.append(f'{owner}:{index}: own precedence violation')
            for lower, upper in task['closures'].get(job['resource'], []):
                if start < upper and end > lower:
                    errors.append(f'{owner}:{index}: resource closed [{lower},{upper})')
            intervals.append((owner, index, start, end, job['resource']))
    for position, first in enumerate(intervals):
        for second in intervals[position+1:]:
            if first[4] == second[4] and first[2] < second[3] and second[2] < first[3]:
                errors.append(f'overlap {first[0]}:{first[1]} and {second[0]}:{second[1]}')
    for predecessor, successor in task['dependencies']:
        owner, index = predecessor.split(':')
        following, step = successor.split(':')
        valid_owners = all(peer in plans and isinstance(plans[peer], list) and len(plans[peer]) == 2 and all(type(value) is int for value in plans[peer]) for peer in (owner, following))
        if valid_owners and plans[following][int(step)] < plans[owner][int(index)] + task['jobs'][owner][int(index)]['duration']:
            errors.append(f'dependency {predecessor} -> {successor}')
    if complete and set(plans) != set(task['jobs']):
        errors.append('missing owner plans')
    return errors


def context(task, owner, board, errors):
    return {'task': 'Schedule operations on capacity-one resources. Minimize sum of final completion times. '
                   'Respect durations, releases, own ordering, dependencies and closures. Intervals are half-open. '
                   'Do not overlap operations on the same resource. Lower numeric owner has priority in conflict repair. '
                   'Choose times yourself; no solver supplies candidates. Return JSON only.',
            'owner': owner, 'problem': task, 'public_board': board, 'validation_errors': errors,
            'schema': {'plans': {'0': ['integer', 'integer'], '1': ['integer', 'integer'], '2': ['integer', 'integer']}}
            if owner == 'central' else {'starts': ['integer', 'integer']}}


class Recorder(resource.OllamaDecisionModel):
    def __init__(self, model, path, limit):
        super().__init__(model=model)
        self.path, self.limit, self.phase_start = path, limit, 0

    def check(self):
        if len(self.calls)-self.phase_start >= self.limit:
            raise RuntimeError('per-phase model call budget exhausted')

    def flush(self):
        self.path.write_text(json.dumps(self.calls, ensure_ascii=False, indent=2, default=str), encoding='utf-8')

    def decide(self, identity, stage, content):
        self.check()
        payload = {'model': self.model, 'stream': False, 'format': 'json',
                   'messages': [{'role': 'system', 'content': 'Follow the scheduling task. Return JSON only.'},
                                {'role': 'user', 'content': json.dumps(content)}],
                   'options': {'temperature': 0, 'num_predict': 256, 'num_ctx': 32768}}
        try:
            request = urllib.request.Request(self.endpoint, json.dumps(payload).encode(), {'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=180) as response:
                result = json.load(response)
            self.calls.append({'identity': identity, 'stage': stage, 'request': payload, 'response': result})
            decision = json.loads(result['message']['content'])
            if not isinstance(decision, dict): raise ValueError('expected JSON object')
            return decision
        finally:
            self.flush()


class Task:
    def __init__(self, identity, task):
        self.identity, self.task = identity, task
        self.plan = resource.SegmentedPlan({'shared': None, 'unrelated': {'keep': 7}})
        self.board, self.installs = {}, 0

    def observe(self): return self.plan.versions['shared']
    def needs_revision(self, observation): return self.identity == '0' and not self.installs
    def infeasible(self, observation): return False
    def coordination_peers(self, proposal, observation): return ('0', '1', '2')
    def candidates_from_decision(self, decision, observation): return (resource.Candidate('schedule', {}),)
    def decision_context(self, stage, observation, **details):
        if stage == 'revise':
            return {'task': 'Request group scheduling. Return JSON with request equal to coordinate.'}
        constraints = details['proposal'].constraints or {}
        return context(self.task, self.identity, constraints.get('board', self.board), constraints.get('errors', []) + details['errors'])
    def response_from_decision(self, decision, proposal, candidate, observation):
        starts = decision['starts']
        errors = validate(self.task, {self.identity: starts}, complete=False)
        if errors: raise ValueError('; '.join(errors))
        return resource.Response(True, starts[1]+2, {'starts': starts}, resource.PlanPatch({'shared': observation}, {'shared': starts}))
    def valid(self, response, observation): return self.plan.valid(response.private_plan)
    def install(self, response):
        self.plan.apply(response.private_plan)
        self.installs += 1
    def compatible(self, candidate, reports):
        return not validate(self.task, {owner: row['public']['starts'] for owner, row in reports.items()})
    def negotiation_constraints(self, proposal, reports, reason):
        board = {owner: row['schedule']['public']['starts'] for owner, row in reports.items()}
        return {'board': board, 'errors': validate(self.task, board)}
    def act(self, observation): return self.plan.segments['shared']


class LoggedClient(OpenAIChatCompletionClient):
    def __init__(self, recorder):
        super().__init__(model=recorder.model, base_url='http://localhost:11434/v1', api_key='ollama',
                         model_info={'vision': False, 'function_calling': False, 'json_output': True, 'family': 'unknown', 'structured_output': False},
                         temperature=0, max_tokens=256, response_format={'type': 'json_object'}, max_retries=0)
        self.recorder = recorder

    async def create(self, messages, **kwargs):
        self.recorder.check()
        result = await super().create(messages, **kwargs)
        self.recorder.calls.append({'request': [message.model_dump() for message in messages], 'response': result.model_dump(),
                                    'input_tokens': result.usage.prompt_tokens, 'output_tokens': result.usage.completion_tokens})
        self.recorder.flush()
        return result


async def baseline(method, task, previous, recorder):
    board, errors = dict(previous), []
    if method == 'protocol':
        mailbox = resource.Mailbox()
        tasks = [Task(str(index), task) for index in range(3)]
        for item in tasks: item.board = previous
        agents = [resource.Agent(item.identity, ('0', '1', '2'), item, mailbox, decision_model=recorder,
                                 max_negotiation_rounds=6) for item in tasks]
        for round_index in range(3):
            resource.run_round(agents, mailbox, round_index)
            if all(item.installs for item in tasks): break
        return {item.identity: item.plan.segments['shared'] for item in tasks}, {'protocol_messages': len(mailbox.messages)}
    if method == 'autogen':
        client = LoggedClient(recorder)
        team = RoundRobinGroupChat([AssistantAgent('owner_'+str(index), client,
                    system_message='You schedule only owner '+str(index)+'. '+json.dumps(context(task, str(index), previous, [])))
                    for index in range(3)], max_turns=3)
        try:
            for cycle in range(recorder.limit//3):
                result = await team.run(task=json.dumps({'public_board': board, 'validation_feedback': errors,
                                                        'instruction': 'Each owner returns JSON with starts: [integer, integer].'}))
                for message in result.messages:
                    if message.source.startswith('owner_'):
                        try: board[message.source.removeprefix('owner_')] = json.loads(message.content)['starts']
                        except (ValueError, KeyError, TypeError): pass
                errors = validate(task, board)
                if not errors: break
        finally:
            await client.close()
        return board, {'validation_errors': errors}
    if method == 'central':
        while True:
            try: board = recorder.decide('central', 'respond', context(task, 'central', board, errors))['plans']
            except (ValueError, KeyError, TypeError) as error:
                errors = [str(error)]
                continue
            errors = validate(task, board)
            if not errors: return board, {}
    board = {}
    for owner in task['jobs']:
        local_errors = []
        for attempt in range(recorder.limit//3):
            try:
                starts = recorder.decide(owner, 'respond', context(task, owner, {}, local_errors))['starts']
                local_errors = validate(task, {owner: starts}, complete=False)
                if not local_errors:
                    board[owner] = starts
                    break
            except (ValueError, KeyError, TypeError) as error: local_errors = [str(error)]
    return board, {}


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='qwen2.5:1.5b')
    parser.add_argument('--budget', type=int, default=18)
    parser.add_argument('--methods', nargs='+', default=['independent', 'central', 'autogen', 'protocol'])
    args = parser.parse_args()
    target = ROOT/'runs'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    target.mkdir(parents=True)
    manifest = {'args': vars(args), 'instances': [problem(phase) for phase in range(2)],
                'packages': {name: importlib.metadata.version(name) for name in ['autogen-agentchat','autogen-ext']},
                'status': 'preliminary development pilot; not a benchmark or full paper reproduction'}
    (target/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    for source in [Path(__file__), ROOT.parent.parent/'核心源码/agent.py', ROOT.parent.parent/'核心源码/llm.py']:
        (target/source.name).write_bytes(source.read_bytes())
    results = []
    for method in args.methods:
        previous = {}
        recorder = Recorder(args.model, target/(method+'-calls.json'), args.budget)
        for phase in range(2):
            recorder.phase_start = len(recorder.calls)
            board, metadata = {}, {}
            try:
                board, metadata = await baseline(method, problem(phase), previous, recorder)
            except Exception as error: metadata['error'] = repr(error)
            errors = validate(problem(phase), board)
            calls = recorder.calls[recorder.phase_start:]
            row = {'method': method, 'phase': phase, 'plans': board, 'valid': not errors, 'errors': errors,
                   'completed_operations': 6 if not errors else 0,
                   'completion_sum': sum(starts[1]+2 for starts in board.values()) if not errors else None,
                   'calls': len(calls), 'input_tokens': sum(call.get('input_tokens', call.get('response', {}).get('prompt_eval_count', 0)) for call in calls),
                   'output_tokens': sum(call.get('output_tokens', call.get('response', {}).get('eval_count', 0)) for call in calls), **metadata}
            results.append(row)
            if not errors: previous = board
            (target/'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
            print(json.dumps(row), flush=True)
    print(target, flush=True)


if __name__ == '__main__':
    asyncio.run(main())
