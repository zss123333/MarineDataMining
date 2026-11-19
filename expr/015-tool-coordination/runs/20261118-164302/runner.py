from dataclasses import asdict
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
CORE = ROOT.parents[1] / '核心源码'
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(ROOT.parent / '004-distributed-agent-core/src'))
from agent import Agent, Candidate, Response, PlanPatch
from demo import Mailbox, run_round
from llm import OllamaDecisionModel
from tools import ToolCall, ToolResult, ToolRuntime, ToolSpec

spec = importlib.util.spec_from_file_location('existing_resource_plugin', ROOT.parent / '011-llm-coordination/run.py')
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)

JOBS = {'collect': ('0', ()), 'analyse': ('1', ('collect',)),
        'publish': ('2', ('analyse',)), 'reference': ('2', ())}


class ToolTask(plugin.ResourceTask):
    def __init__(self, identity, runtime):
        super().__init__(identity, 3, False, 0)
        self.runtime = runtime

    def observe(self):
        return dict(version=self.plan.versions['shared'], completed=sorted(self.runtime.artifacts),
                    running=sorted(self.runtime.pending), time=self.runtime.tick)

    def needs_revision(self, observation):
        return self.identity == '0' and len(self.runtime.artifacts) < len(JOBS)

    def decision_context(self, stage, observation, **details):
        if stage == 'revise':
            return super().decision_context(stage, observation, **details)
        available = [name for name, (owner, dependencies) in JOBS.items()
                     if owner == self.identity and name not in observation['completed']
                     and name not in observation['running']]
        return dict(task='Choose your own work whose dependencies are completed; otherwise wait. Prefer work to waiting. A promise is not completion. Never choose work for others.',
                    jobs={name: dict(owner=owner, requires=dependencies) for name, (owner, dependencies) in JOBS.items()},
                    observation=observation, validation_errors=details['errors'],
                    output_schema=dict(type='object', properties=dict(job=dict(type='string', enum=available + ['wait'])), required=['job']))

    def response_from_decision(self, decision, proposal, candidate, observation):
        job = decision['job']
        if job != 'wait':
            if job not in JOBS or JOBS[job][0] != self.identity:
                raise ValueError('Choose only your own work')
            if job in observation['completed'] or job in observation['running']:
                raise ValueError('Work already completed or running')
            if any(name not in observation['completed'] for name in JOBS[job][1]):
                raise ValueError('Dependency is not completed; wait or choose independent work')
        return Response(True, 0, dict(job=job), PlanPatch(dict(shared=observation['version']), dict(shared=job)))

    def compatible(self, candidate, reports):
        return True

    def act(self, observation):
        job = self.plan.segments['shared']
        if job in (None, 'wait') or job in self.runtime.artifacts or job in self.runtime.pending:
            return None
        return ToolCall(job, job, job, JOBS[job][1])


def main():
    target = ROOT / 'runs' / datetime.now().strftime('%Y%m%d-%H%M%S')
    target.mkdir(parents=True)
    for name in ('agent.py', 'llm.py', 'tools.py'):
        (target / name).write_bytes((CORE / name).read_bytes())
    (target / 'runner.py').write_bytes(Path(__file__).read_bytes())
    (target / 'resource_plugin.py').write_bytes(Path(plugin.__file__).read_bytes())
    runtime = ToolRuntime([ToolSpec(name, frozenset([owner]),
                                  lambda inputs: ToolResult(dict(input_tasks=sorted(inputs)), 2))
                           for name, (owner, dependencies) in JOBS.items()])
    model = OllamaDecisionModel()
    mailbox = Mailbox()
    members = ('0', '1', '2')
    tasks = [ToolTask(identity, runtime) for identity in members]
    agents = [Agent(identity, members, task, mailbox, decision_model=model)
              for identity, task in zip(members, tasks)]
    rows = []
    error = None
    try:
        for round_index in range(12):
            actions = run_round(agents, mailbox, round_index)
            receipts = [runtime.submit(identity, action) for identity, action in actions.items() if action]
            events = runtime.advance()
            rows.append(dict(round=round_index, receipts=[asdict(row) for row in receipts],
                             events=[asdict(row) for row in events], completed=sorted(runtime.artifacts)))
            print(rows[-1], flush=True)
            if len(runtime.artifacts) == len(JOBS):
                break
    except Exception as failure:
        error = repr(failure)
    finally:
        result = dict(scope='existing Agent and ResourceTask integration; not external baseline or framework ranking',
                      success=len(runtime.artifacts) == len(JOBS), error=error, rounds=rows,
                      llm_calls=len(model.calls), messages=len(mailbox.messages),
                      input_tokens=sum(call['response'].get('prompt_eval_count', 0) for call in model.calls),
                      output_tokens=sum(call['response'].get('eval_count', 0) for call in model.calls),
                      artifacts=runtime.artifacts, trace={agent.identity: agent.trace for agent in agents})
        (target / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        (target / 'calls.json').write_text(json.dumps(model.calls, ensure_ascii=False, indent=2), encoding='utf-8')
        print(target, flush=True)
    if error:
        raise RuntimeError(error)


if __name__ == '__main__':
    main()
