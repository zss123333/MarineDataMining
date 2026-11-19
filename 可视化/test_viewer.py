import json
from pathlib import Path
import sys
import unittest

from server import load_events, resolve_source, EXPERIMENTS
from server import start_task

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '核心源码'))
from telemetry import EventLog, LoggedTransport
from types import SimpleNamespace


class ViewerTests(unittest.TestCase):
    def test_unknown_task_not_started(self):
        with self.assertRaises(ValueError):
            start_task('unknown')

    def test_reject_escape(self):
        with self.assertRaises(ValueError):
            resolve_source('../核心源码/agent.py')

    def test_history_adapter(self):
        path = resolve_source('015-tool-coordination/dynamic_runs/20261118-172010/local-0-result.json')
        events = load_events(path)
        self.assertTrue(any(row['kind'] == 'coordination' for row in events))
        self.assertTrue(any(row['kind'] == 'model' for row in events))

    def test_log_transport(self):
        import tempfile
        with tempfile.TemporaryDirectory(dir=EXPERIMENTS) as directory:
            path = Path(directory) / 'events.jsonl'
            log = EventLog(path)
            transport = LoggedTransport(SimpleNamespace(send=lambda message: None), log)
            transport.send(SimpleNamespace(sender='A', receiver='B'))
            event = load_events(path)[0]
            self.assertEqual(event['agent'], 'A')
            self.assertEqual(event['peer'], 'B')


if __name__ == '__main__':
    unittest.main()
