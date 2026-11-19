import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    results = []
    for folder in sorted((root / 'runs').iterdir()):
        if not folder.is_dir():
            continue
        summary_path = folder / 'summary.json'
        calls_path = folder / 'calls.json'
        calls = json.loads(calls_path.read_text(encoding='utf-8')) if calls_path.exists() else []
        row = {
            'run': folder.name,
            'entry': json.loads(summary_path.read_text(encoding='utf-8')) if summary_path.exists() else {'status': 'running_or_interrupted'},
            'chat_calls': sum(call['kind'] == 'chat' for call in calls),
            'embedding_calls': sum(call['kind'] == 'embedding' for call in calls),
            'call_errors': sum('error' in call for call in calls),
            'episodes': [],
        }
        for path in sorted((folder / 'data').rglob('*.json')):
            episode = json.loads(path.read_text(encoding='utf-8'))
            if 'total_timestamp' not in episode:
                continue
            row['episodes'].append({
                'file': str(path.relative_to(root)),
                'steps': len(episode['total_timestamp']),
                'score': episode.get('total_score'),
                'finished_orders': episode.get('total_order_finished'),
                'actions': episode.get('total_action_list'),
            })
        results.append(row)
    (root / 'audit.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
