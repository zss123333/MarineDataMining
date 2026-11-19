from datetime import datetime
import json
from pathlib import Path

import run as integration
from agent import Agent
from demo import Mailbox, run_round
from llm import OllamaDecisionModel
from tools import ToolRuntime, ToolSpec, ToolResult


class ComparisonTask(integration.ToolTask):
    def __init__(self, identity, runtime, periodic):
        super().__init__(identity, runtime)
        self.periodic = periodic

    def needs_revision(self, observation):
        if self.identity != '0':
            return False
        if self.periodic:
            return len(self.runtime.artifacts) < len(integration.JOBS)
        for name, (owner, dependencies) in integration.JOBS.items():
            busy = any(integration.JOBS[task][0] == owner for task in self.runtime.pending)
            if not busy and name not in self.runtime.artifacts and name not in self.runtime.pending:
                if all(task in self.runtime.artifacts for task in dependencies):
                    return True
        return False


def execute(seed, periodic, target):
    durations = {name: 2 + (index + seed) % 3 for index, name in enumerate(integration.JOBS)}
    durations['analyse'] += 3
    runtime = ToolRuntime([ToolSpec(name, frozenset([owner]),
                                  lambda inputs, duration=durations[name]: ToolResult(dict(inputs=sorted(inputs)), duration))
                           for name, (owner, dependencies) in integration.JOBS.items()])
    model = OllamaDecisionModel()
    mailbox = Mailbox()
    members = ('0', '1', '2')
    tasks = [ComparisonTask(identity, runtime, periodic) for identity in members]
    agents = [Agent(identity, members, task, mailbox, decision_model=model)
              for identity, task in zip(members, tasks)]
    rows = []
    failure = None
    label = str(seed) + '-' + str(periodic)
    try:
        for round_index in range(30):
            actions = run_round(agents, mailbox, round_index)
            receipts = [runtime.submit(identity, action) for identity, action in actions.items() if action]
            events = runtime.advance()
            rows.append(dict(round=round_index, submitted=[receipt.__dict__ for receipt in receipts],
                             completed=[event.task_id for event in events]))
            if len(runtime.artifacts) == len(integration.JOBS):
                break
    except Exception as error:
        failure = repr(error)
    finally:
        row = dict(seed=seed, periodic=periodic, durations=durations,
                   success=len(runtime.artifacts) == len(integration.JOBS), error=failure,
                   makespan=runtime.tick, completed=len(runtime.artifacts),
                   llm_calls=len(model.calls), messages=len(mailbox.messages),
                   input_tokens=sum(call['response'].get('prompt_eval_count', 0) for call in model.calls),
                   output_tokens=sum(call['response'].get('eval_count', 0) for call in model.calls),
                   trajectory=rows, trace={agent.identity: agent.trace for agent in agents})
        (target / (label + '-calls.json')).write_text(json.dumps(model.calls, indent=2), encoding='utf-8')
        (target / (label + '-result.json')).write_text(json.dumps(row, indent=2), encoding='utf-8')
    return row


def main():
    integration.JOBS.update(dict(audit=('0', ()), appendix=('2', ())))
    target = Path(__file__).resolve().parent / 'comparisons' / datetime.now().strftime('%Y%m%d-%H%M%S')
    target.mkdir(parents=True)
    for name in ('compare.py', 'run.py'):
        (target / name).write_bytes((integration.ROOT / name).read_bytes())
    for name in ('agent.py', 'llm.py', 'tools.py'):
        (target / name).write_bytes((integration.CORE / name).read_bytes())
    (target / 'resource_plugin.py').write_bytes(Path(integration.plugin.__file__).read_bytes())
    results = []
    for seed in range(3):
        for periodic in ((False, True) if seed % 2 == 0 else (True, False)):
            row = execute(seed, periodic, target)
            results.append(row)
            (target / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
            print({key: row[key] for key in ('seed', 'periodic', 'success', 'makespan', 'llm_calls', 'messages', 'error')}, flush=True)
    print(target, flush=True)


if __name__ == '__main__':
    main()
