import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    target = sorted((root / 'dynamic_runs').iterdir())[-1]
    results = json.loads((target / 'results.json').read_text(encoding='utf-8'))
    checks = []
    for row in results:
        completed = set()
        legal = True
        for step in row['trajectory']:
            for receipt in step['submitted']:
                if receipt['task_id'] == 'publish' and not {'analyse', 'verify'} <= completed:
                    legal = False
            completed.update(step['completed'])
        versions = [step['versions']['3'] for step in row['trajectory']]
        checks.append(dict(method=row['method'], configuration=row['configuration'],
                           legal_publish=legal, success=row['success'],
                           independent_plan_version=max(versions, default=0)))
    totals = {method: {key: sum(row[key] for row in results if row['method'] == method)
                      for key in ('calls', 'input_tokens', 'output_tokens', 'protocol_messages')}
              for method in ('local', 'global', 'autogen')}
    pairs = []
    for configuration in (0, 1):
        group = {row['method']: row for row in results if row['configuration'] == configuration}
        if len(group) == 3:
            execution = {method: [(step['submitted'], step['completed']) for step in row['trajectory']]
                         for method, row in group.items()}
            pairs.append(dict(configuration=configuration, same_execution=execution['local'] == execution['global'] == execution['autogen']))
    summary = dict(checks=checks, totals=totals, pairs=pairs)
    (target / 'audit.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
