from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
CORE = ROOT.parents[1] / '核心源码'
sys.path.insert(0, str(CORE))
from llm import OllamaDecisionModel
from tools import ToolCall, ToolResult, ToolRuntime, ToolSpec


class Workflow:
    def __init__(self, case):
        self.case = case
        self.raw = True
        self.reviewed = False
        self.done = False
        self.runtime = ToolRuntime([ToolSpec(name, frozenset(['worker']), lambda inputs, name=name:
            ToolResult(dict(action=name))) for name in ('inspect', 'draft', 'publish', 'wait')])

    def observe(self):
        return dict(raw_material_available=self.raw, reviewed=self.reviewed, done=self.done,
                    draft_completed=not self.raw,
                    required_review=self.case != 'direct', time=self.runtime.tick)

    def act(self, action):
        if action == 'inspect':
            if not self.raw:
                return 'rejected: inspection needs original material, already consumed'
            self.reviewed = True
        elif action == 'draft':
            if not self.raw:
                return 'rejected: material already consumed'
            self.raw = False
        elif action == 'publish':
            if self.raw or (self.case != 'direct' and not self.reviewed):
                return 'rejected: need draft and required review'
            self.done = True
        elif action != 'wait':
            return 'rejected: unknown tool'
        call = ToolCall(str(self.runtime.tick), str(self.runtime.tick), action)
        receipt = self.runtime.submit('worker', call)
        self.runtime.advance()
        return receipt.status + '; actual action completed after one logical tick'


def execute(method, case, target):
    model = OllamaDecisionModel()
    world = Workflow(case)
    history = []
    error = None
    try:
        for step in range(6):
            schema = dict(type='object', properties=dict(action=dict(type='string', enum=['inspect','draft','publish','wait'])), required=['action'])
            schema['properties']['decision_summary'] = dict(type='string')
            schema['required'].append('decision_summary')
            instruction = 'Use a ReAct-style observation-action loop. Choose the next tool action using the task and interaction history. Give a brief decision summary, not detailed internal reasoning. You may plan as needed.'
            if method == 'lookahead':
                instruction += ' Explicitly propose the next 2-3 tool actions in future_plan. Check prerequisites and irreversible effects across the plan. Execute only action (the first planned action), then replan from real feedback.'
                schema['properties']['future_plan'] = dict(type='array', items=dict(type='string', enum=['inspect','draft','publish','wait']), minItems=1, maxItems=3)
                schema['required'].append('future_plan')
                del schema['properties']['action']
                schema['required'].remove('action')
                instruction += ' Output only future_plan and decision_summary; its first item is executed.'
            context = dict(task='Prepare and publish a report. Tool operation details are encapsulated.',
                instruction=instruction, observation=world.observe(), history=history,
                tools=dict(inspect='Checks original material without consuming it; requires raw material.',
                           draft='Creates report draft and irreversibly consumes original material.',
                           publish='Requires a draft and review when required_review=true.', wait='No progress.'),
                output_schema=schema)
            decision = model.decide('worker','next_action',context)
            action = decision['future_plan'][0] if method == 'lookahead' else decision['action']
            feedback = world.act(action)
            history.append(dict(step=step, decision=decision, feedback=feedback, observation=world.observe()))
            if world.done:
                break
    except Exception as failure:
        error = repr(failure)
    row = dict(method=method, case=case, success=world.done, error=error, steps=len(history),
               calls=len(model.calls), input_tokens=sum(call['response'].get('prompt_eval_count',0) for call in model.calls),
               output_tokens=sum(call['response'].get('eval_count',0) for call in model.calls), history=history)
    (target / (method+'-'+case+'-calls.json')).write_text(json.dumps(model.calls,indent=2),encoding='utf-8')
    return row


def main():
    target = ROOT / 'runs' / datetime.now().strftime('%Y%m%d-%H%M%S')
    target.mkdir(parents=True)
    for name in ('llm.py','tools.py'):
        (target/name).write_bytes((CORE/name).read_bytes())
    (target/'runner.py').write_bytes(Path(__file__).read_bytes())
    results = []
    for case in ('direct','review'):
        for method in ('react','lookahead'):
            row = execute(method,case,target)
            results.append(row)
            (target/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
            print({key:row[key] for key in ('case','method','success','steps','calls','error')},flush=True)
    print(target,flush=True)


if __name__ == '__main__':
    main()
