import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import subprocess
import os
from datetime import datetime
from threading import Lock
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
EXPERIMENTS = ROOT.parent / 'expr'
LOGGER = logging.getLogger('viewer')
RUN_LOCK = Lock()
CURRENT = {}


def start_task(task):
    if task not in ('basic', 'dynamic'):
        raise ValueError('unknown task')
    with RUN_LOCK:
        if CURRENT.get('process') and CURRENT['process'].poll() is None:
            raise ValueError('A task is already running')
        target = EXPERIMENTS / 'live-ui' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        target.mkdir(parents=True)
        python = EXPERIMENTS / '003-flatland-core/.venv/Scripts/python.exe'
        environment = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
        with (target / 'console.log').open('w', encoding='utf-8') as output:
            process = subprocess.Popen([str(python), '-u', str(ROOT / 'live_task.py'), task, str(target)],
                                       stdout=output, stderr=subprocess.STDOUT, env=environment,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        CURRENT.update(process=process, source=str((target / 'local-0/events.jsonl').relative_to(EXPERIMENTS)), task=task)
        return dict(source=CURRENT['source'], task=task, pid=process.pid)


def sources():
    return sorted(path for path in EXPERIMENTS.rglob('*.json')
                  if not any(part in ('.venv', 'node_modules') for part in path.parts)
                  and (path.name in ('result.json', 'results.json', 'events.jsonl')
                       or path.name.endswith('-result.json'))) + sorted(EXPERIMENTS.rglob('events.jsonl'))


def resolve_source(name):
    path = (EXPERIMENTS / name).resolve()
    if not path.is_relative_to(EXPERIMENTS.resolve()) or not path.is_file():
        raise ValueError('source must be an existing file within expr')
    if path.suffix not in ('.json', '.jsonl'):
        raise ValueError('unsupported source')
    return path


def load_events(path):
    events = []
    def add(kind, data, agent=None, time=None, peer=None):
        events.append(dict(sequence=len(events), kind=kind, agent=agent, peer=peer,
                           time=time, data=data, source=str(path.relative_to(EXPERIMENTS))))
    if path.suffix == '.jsonl':
        current_time = None
        for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
            try:
                row = json.loads(line)
                if row.get('time') is not None:
                    current_time = row['time']
                add(row.get('kind', 'event'), row, row.get('agent'), row.get('time', current_time), row.get('peer'))
            except (ValueError, AttributeError) as error:
                add('parse_error', dict(line=number, error=str(error)))
        return events
    content = json.loads(path.read_text(encoding='utf-8-sig'))
    for run_index, result in enumerate(content if isinstance(content, list) else [content]):
        if not isinstance(result, dict):
            continue
        add('summary', dict(run=run_index, **{key: value for key, value in result.items()
                     if key not in ('trajectory', 'rounds', 'trace', 'calls', 'artifacts')}))
        for step in result.get('trajectory', result.get('rounds', [])):
            if not isinstance(step, dict):
                add('snapshot', step)
                continue
            add('snapshot', step, time=step.get('time', step.get('round')))
        for agent, trace in result.get('trace', {}).items():
            for row in trace:
                add('coordination', row, agent=agent, time=row.get('time', row.get('round')))
    call_path = path.with_name(path.name.replace('-result.json', '-calls.json')) if path.name.endswith('-result.json') else path.with_name('calls.json')
    if call_path != path and call_path.exists():
        for row in json.loads(call_path.read_text(encoding='utf-8-sig')):
            add('model', row, agent=row.get('identity'))
    return events


class Handler(SimpleHTTPRequestHandler):
    def do_POST(self):
        try:
            if self.path != '/api/start':
                self.send_error(404)
                return
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + self.headers.get('Host', ''):
                raise ValueError('cross-origin start denied')
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size < 2048:
                raise ValueError('invalid request size')
            result = start_task(json.loads(self.rfile.read(size))['task'])
            data = json.dumps(result).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(data)
        except Exception as error:
            LOGGER.exception('start failed')
            self.send_error(400, str(error))

    def do_GET(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith('/api/'):
            if parsed.path not in ('/', '/index.html', '/sequence.js'):
                self.send_error(404)
                return
            return super().do_GET()
        try:
            if parsed.path == '/api/sources':
                result = [str(path.relative_to(EXPERIMENTS)) for path in sources()]
            elif parsed.path == '/api/status':
                process = CURRENT.get('process')
                result = dict(running=process is not None and process.poll() is None,
                              exit_code=process.poll() if process else None, source=CURRENT.get('source'))
            elif parsed.path == '/api/events':
                name = parse_qs(parsed.query).get('source', [''])[0]
                result = load_events(resolve_source(name))
            else:
                self.send_error(404)
                return
            data = json.dumps(result, ensure_ascii=False, default=str).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)
        except Exception as error:
            LOGGER.exception('request failed: %s', parsed.path)
            self.send_error(400, str(error))

    def log_message(self, format, *args):
        LOGGER.info(format, *args)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(), logging.FileHandler(ROOT / 'server.log', encoding='utf-8')])
    server = ThreadingHTTPServer(('127.0.0.1', args.port), partial(Handler, directory=str(ROOT)))
    LOGGER.info('viewer http://127.0.0.1:%s ; root=%s', args.port, EXPERIMENTS)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
