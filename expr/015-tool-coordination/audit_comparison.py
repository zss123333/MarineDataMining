import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    target = sorted((root / 'comparisons').iterdir())[-1]
    results = json.loads((target / 'results.json').read_text(encoding='utf-8'))
    pairs = []
    for seed in sorted(set(row['seed'] for row in results)):
        group = {row['periodic']: row for row in results if row['seed'] == seed}
        if len(group) != 2:
            continue
        local, periodic = group[False], group[True]
        pairs.append(dict(seed=seed, both_success=local['success'] and periodic['success'],
                          same_trajectory=local['trajectory'] == periodic['trajectory'],
                          same_durations=local['durations'] == periodic['durations'],
                          event_makespan=local['makespan'], periodic_makespan=periodic['makespan']))
    totals = {str(periodic): {key: sum(row[key] for row in results if row['periodic'] == periodic)
                              for key in ('llm_calls', 'messages', 'input_tokens', 'output_tokens')}
              for periodic in (False, True)}
    summary = dict(scope='internal trigger ablation, not external baseline', pairs=pairs, totals=totals)
    (target / 'audit.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
