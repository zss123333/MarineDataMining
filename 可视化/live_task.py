import asyncio
from datetime import datetime
import json
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'expr/015-tool-coordination'))
from dynamic import execute
from telemetry import EventLog


async def main():
    task, folder = sys.argv[1:]
    target = Path(folder)
    log = EventLog(target / 'local-0/events.jsonl')
    log.emit('run_start', task=task, members=['0', '1', '2'])
    try:
        result = await execute('local', 0, target, dynamic_event=task == 'dynamic', member_count=3)
        if task == 'basic':
            result['success'] = len(result['artifacts']) == 4 and not result['error']
        log.emit('run_end', success=result['success'], error=result['error'])
        (target / 'live-result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    except Exception:
        log.emit('error', traceback=traceback.format_exc())
        raise


if __name__ == '__main__':
    asyncio.run(main())
