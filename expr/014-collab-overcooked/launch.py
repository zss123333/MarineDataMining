import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--horizon', type=int, default=3)
    parser.add_argument('--model', default='qwen2.5:1.5b')
    parser.add_argument('--call-limit', type=int, default=200)
    parser.add_argument('--request-timeout', type=float, default=120)
    parser.add_argument('--local-execution', action='store_true')
    parser.add_argument('--fixed-roles', action='store_true')
    args = parser.parse_args()
    if args.local_execution:
        parser.error('--local-execution is retired: task-specific prompt repair is not a coordination comparison; use execution_gate.py for shared execution acceptance')
    source = Path(args.source).resolve()
    root = Path(__file__).resolve().parent
    target = root/'runs'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    target.mkdir(parents=True)
    manifest = {'upstream_commit': 'd7ae1aa5e63d8ec076e96ee437fcbbd095278ef4', 'args': vars(args),
                'entry': 'src/main.py LLMPair/LLMPair; original task, prompts, controllers and validators',
                'adaptations': ['route OpenAI client to local Ollama', 'record HTTP model calls',
                                'use local all-minilm embedding instead of OpenAI embedding',
                                'use bundled llama tokenizer for upstream local-model token estimates'],
                'source_hashes': {name: hashlib.sha256((source/name).read_bytes()).hexdigest()
                                  for name in ['src/main.py', 'src/collab/collab.py', 'src/collab/modules.py']}}
    (target/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (target/'launch.py').write_bytes(Path(__file__).read_bytes())
    import openai
    original_client = openai.OpenAI
    calls = []

    class LocalClient(original_client):
        def __init__(self, *values, **options):
            options['base_url'] = 'http://localhost:11434/v1'
            options['api_key'] = 'local-ollama'
            options['max_retries'] = 0
            options['timeout'] = args.request_timeout
            super().__init__(*values, **options)
            for endpoint, kind in [(self.chat.completions, 'chat'), (self.embeddings, 'embedding')]:
                original_create = endpoint.create

                def recorded(*values, _create=original_create, _kind=kind, **options):
                    if len(calls) >= args.call_limit:
                        raise KeyboardInterrupt('local safety call limit reached')
                    options['model'] = 'all-minilm' if _kind == 'embedding' else args.model
                    row = {'kind': _kind, 'request': options, 'started': time.time()}
                    calls.append(row)
                    try:
                        result = _create(*values, **options)
                        row['response'] = result.model_dump()
                        return result
                    except Exception as error:
                        row['error'] = repr(error)
                        raise
                    finally:
                        (target/'calls.json').write_text(json.dumps(calls, indent=2), encoding='utf-8')
                endpoint.create = recorded

    openai.OpenAI = LocalClient
    os.chdir(source/'src')
    sys.path.insert(0, str(source/'src'))
    if args.fixed_roles:
        from fixed_roles import install
        install(source, target)
        (target/'fixed_roles.py').write_bytes((root/'fixed_roles.py').read_bytes())
        manifest['adaptations'].append('revised task adapter: fixed initial responsibilities, explicit environment observations, canonical skill parser')
        (target/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    sys.argv = ['main.py', '--horizon', str(args.horizon), '--order', 'boiled_egg',
                '--gpt_model', 'qwen-local', '--model_dirname', '', '--local_server_api',
                'http://localhost:11434/v1', '--statistics_save_dir', str(target/'data')]
    summary = {'status': 'started'}
    try:
        runpy.run_path(str(source/'src/main.py'), run_name='__main__')
        summary['status'] = 'entry_returned'
    except BaseException as error:
        summary.update(status='failed', error=repr(error))
        raise
    finally:
        summary['calls'] = len(calls)
        summary['episodes'] = []
        for path in sorted((target/'data').rglob('*.json')):
            episode = json.loads(path.read_text(encoding='utf-8'))
            if 'total_score' in episode:
                summary['episodes'].append({
                    'file': str(path.relative_to(target)),
                    'steps': len(episode.get('total_timestamp', [])),
                    'score': episode['total_score'],
                    'finished_orders': episode.get('total_order_finished', []),
                    'actions': episode.get('total_action_list', []),
                })
        summary['task_completion_observed'] = any(
            episode['score'] > 0 and bool(episode['finished_orders'])
            for episode in summary['episodes'])
        summary['shared_executor_validated'] = False
        summary['acceptance_note'] = 'Task completion is necessary but not sufficient: LLMPair couples planning and coordination; a reusable shared executor requires separate interface validation.'
        (target/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
        print(target, flush=True)


if __name__ == '__main__': main()
