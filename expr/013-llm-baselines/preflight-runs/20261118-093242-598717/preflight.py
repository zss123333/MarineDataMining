import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path

from run import Recorder, context, problem, validate

ROOT = Path(__file__).resolve().parent


def cases():
    result = []
    for seed in [201, 202, 203]:
        for level in ['single', 'parallel', 'shared', 'dependency', 'closure']:
            task = problem(int(level == 'closure'))
            for jobs in task['jobs'].values():
                jobs[0]['duration'] = 1 + seed % 2
                jobs[0]['release'] = seed % 3
            if level in ['single', 'parallel', 'shared']:
                task['dependencies'] = []
            if level == 'single':
                task['jobs'] = {'0': task['jobs']['0']}
            if level == 'parallel':
                for owner, jobs in task['jobs'].items():
                    for job in jobs: job['resource'] += owner
            result.append({'seed': seed, 'level': level, 'task': task})
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='qwen2.5:1.5b')
    args = parser.parse_args()
    target = ROOT/'preflight-runs'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    target.mkdir(parents=True)
    suite = cases()
    manifest = {'model': args.model, 'cases': suite, 'calls_per_case': 2,
                'selection_rule': 'No formal comparison if single-owner feasibility is below 2/3. Development cases only; never select by protocol wins.',
                'holdout_seeds_not_used': [301, 302, 303, 304, 305],
                'source_hashes': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ['run.py', 'preflight.py']}}
    (target/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    for name in ['run.py', 'preflight.py']: (target/name).write_bytes((ROOT/name).read_bytes())
    recorder = Recorder(args.model, target/'calls.json', 2)
    results = []
    for case in suite:
        recorder.phase_start = len(recorder.calls)
        board, errors = {}, []
        task = case['task']
        owner = '0' if case['level'] == 'single' else 'central'
        for attempt in range(2):
            try:
                content = context(task, owner, board, errors)
                content['attempt'] = attempt
                decision = recorder.decide(owner, 'respond', content)
                board = {'0': decision['starts']} if owner == '0' else decision['plans']
                errors = validate(task, board)
            except Exception as error:
                errors = [repr(error)]
            if not errors: break
        row = {'seed': case['seed'], 'level': case['level'], 'valid': not errors, 'plans': board,
               'errors': errors, 'calls': len(recorder.calls)-recorder.phase_start}
        results.append(row)
        (target/'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
        print(json.dumps(row), flush=True)
    print(target, flush=True)


if __name__ == '__main__': main()
