import json
from pathlib import Path
import sys

from run import problem, validate

root = Path(sys.argv[1])
rows = json.loads((root/'results.json').read_text(encoding='utf-8'))
manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
for row in rows:
    errors = validate(problem(row['phase']), row['plans'])
    assert row['valid'] == (not errors)
    assert row['completed_operations'] == (6 if not errors else 0)
    assert row['calls'] <= manifest['args']['budget']
for method in {row['method'] for row in rows}:
    calls = json.loads((root/(method+'-calls.json')).read_text(encoding='utf-8'))
    assert len(calls) == sum(row['calls'] for row in rows if row['method'] == method)
    assert all('request' in call and 'response' in call for call in calls)
print(f'Audited {len(rows)} stages, raw call counts and feasibility agree.')
