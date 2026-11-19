import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import runpy
import sys
import time
import types
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--model', default='ollama_chat/qwen2.5:7b')
    parser.add_argument('--iterations', type=int, default=1)
    args = parser.parse_args()
    source = args.source.resolve()
    output = Path(__file__).resolve().parent / 'runs' / time.strftime('%Y%m%d-%H%M%S')
    output.mkdir(parents=True)
    os.environ['OLLAMA_API_BASE'] = 'http://localhost:11434'
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    sys.path.insert(0, str(source))
    package = types.ModuleType('marble.environments')
    package.__path__ = [str(source / 'marble' / 'environments')]
    sys.modules[package.__name__] = package
    for module_name, class_name in [
        ('base_env', 'BaseEnvironment'),
        ('coding_env', 'CodingEnvironment'),
        ('web_env', 'WebEnvironment'),
    ]:
        module = importlib.import_module(f'marble.environments.{module_name}')
        setattr(package, class_name, getattr(module, class_name))

    class UnusedEnvironment:
        def __init__(self, *args, **kwargs):
            raise RuntimeError('This launcher supports the coding scenario only.')

    for class_name in ['DBEnvironment', 'MinecraftEnvironment', 'ResearchEnvironment', 'WorldSimulationEnvironment']:
        setattr(package, class_name, UnusedEnvironment)
    import litellm

    original_completion = litellm.completion
    call_count = 0

    def logged_completion(*positional, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count > 200:
            raise RuntimeError('Local smoke-test model-call limit reached: 200')
        kwargs['timeout'] = 180
        kwargs['num_ctx'] = 16384
        started = time.time()
        record = {'call': call_count, 'started': started, 'request': kwargs}
        print(f'LLM call {call_count} started', flush=True)
        try:
            response = original_completion(*positional, **kwargs)
            record['response'] = response.model_dump()
            return response
        except Exception as error:
            record['error'] = f'{type(error).__name__}: {error}'
            raise
        finally:
            record['elapsed_seconds'] = time.time() - started
            with (output / 'model_calls.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(record, ensure_ascii=False, default=str) + '\n')
            print(f'LLM call {call_count} finished in {record["elapsed_seconds"]:.1f}s', flush=True)

    litellm.completion = logged_completion
    archive = source.parent / 'source.zip'
    metadata = {
        'source': str(source), 'model': args.model,
        'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest() if archive.exists() else None,
        'commit': zipfile.ZipFile(archive).comment.decode() if archive.exists() else None,
        'adaptations': ['coding-only environment imports', 'local Ollama backend', 'logged calls with timeout and 200-call guard'],
        'purpose': 'native coding task 1, graph coordination, pipeline acceptance only',
    }
    (output / 'metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    os.chdir(output)
    sys.argv = ['run_benchmark.py', '--scenario', 'coding', '--model', args.model,
                '--task_ids', '1', '--max_iterations', str(args.iterations),
                '--coordinate_mode', 'graph', '--output_dir', str(output / 'results')]
    runpy.run_path(str(source / 'scripts' / 'run_benchmark.py'), run_name='__main__')


if __name__ == '__main__':
    main()
