import asyncio
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from autogen_core.models import CreateResult, RequestUsage
from run import problem, validate, baseline, output_schema, LoggedClient, Recorder


class FakeRecorder:
    limit = 18
    phase_start = 0

    def __init__(self):
        self.calls = []

    def decide(self, identity, stage, content):
        self.calls.append(content)
        if stage == 'revise': return {'request': 'coordinate'}
        plans = {'0': [0, 1], '1': [1, 3], '2': [3, 5]}
        return {'plans': plans} if identity == 'central' else {'starts': plans[identity]}


class ValidationTests(unittest.TestCase):
    def test_timeout_logged_and_budget_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            recorder = Recorder('test', Path(directory)/'calls.json', 1)
            with patch('urllib.request.urlopen', side_effect=TimeoutError('timeout')):
                with self.assertRaises(TimeoutError): recorder.decide('0', 'respond', {})
            self.assertIn('error', recorder.calls[0])
            with self.assertRaises(RuntimeError): recorder.decide('0', 'respond', {})
            self.assertEqual(len(recorder.calls), 1)

    def test_central_malformed_then_valid(self):
        class RepairRecorder(FakeRecorder):
            def decide(self, identity, stage, content):
                self.calls.append(content)
                if len(self.calls) == 1: return {'wrong_field': []}
                return {'plans': {'0': [0, 1], '1': [1, 3], '2': [3, 5]}}
        recorder = RepairRecorder()
        board, metadata = asyncio.run(baseline('central', problem(0), {}, recorder))
        self.assertEqual(validate(problem(0), board), [])
        self.assertTrue(recorder.calls[1]['validation_errors'])

    def test_autogen_conflict_feedback_and_recovery(self):
        class ScriptedClient(LoggedClient):
            async def create(self, messages, **kwargs):
                turn = len(self.recorder.calls)
                self.recorder.calls.append([message.model_dump() for message in messages])
                owner = str(turn % 3)
                plans = {'0': [0, 1], '1': [1, 3], '2': [3, 5]}
                starts = [0, 1] if turn < 3 else plans[owner]
                return CreateResult(finish_reason='stop', content=json.dumps({'starts': starts}),
                                    usage=RequestUsage(prompt_tokens=0, completion_tokens=0), cached=False)
        recorder = FakeRecorder()
        recorder.model = 'qwen2.5:1.5b'
        board, metadata = asyncio.run(baseline('autogen', problem(0), {}, recorder, ScriptedClient))
        self.assertEqual(validate(problem(0), board), [])
        self.assertEqual(len(recorder.calls), 6)
        self.assertIn('overlap', str(recorder.calls[3]))

    def test_central_conflict_feedback_and_recovery(self):
        class RepairRecorder(FakeRecorder):
            def decide(self, identity, stage, content):
                self.calls.append(content)
                if len(self.calls) == 1: return {'plans': {str(index): [0, 1] for index in range(3)}}
                return {'plans': {'0': [0, 1], '1': [1, 3], '2': [3, 5]}}
        recorder = RepairRecorder()
        board, metadata = asyncio.run(baseline('central', problem(0), {}, recorder))
        self.assertEqual(validate(problem(0), board), [])
        self.assertTrue(recorder.calls[1]['validation_errors'])

    def test_independent_local_repair_without_peer_board(self):
        class RepairRecorder(FakeRecorder):
            def decide(self, identity, stage, content):
                previous = sum(row['owner'] == identity for row in self.calls)
                self.calls.append(content)
                plans = {'0': [0, 1], '1': [1, 3], '2': [3, 5]}
                return {'starts': [-1, -1] if not previous else plans[identity]}
        recorder = RepairRecorder()
        board, metadata = asyncio.run(baseline('independent', problem(0), {}, recorder))
        self.assertEqual(validate(problem(0), board), [])
        self.assertTrue(all(not row['public_board'] for row in recorder.calls))

    def test_protocol_conflict_feedback_and_recovery(self):
        class RepairRecorder(FakeRecorder):
            def decide(self, identity, stage, content):
                self.calls.append(content)
                if stage == 'revise': return {'request': 'coordinate'}
                return {'starts': ({'0': [0, 1], '1': [1, 3], '2': [3, 5]}[identity]
                                   if content['public_board'] else [1, 3])}
        recorder = RepairRecorder()
        board, metadata = asyncio.run(baseline('protocol', problem(0), {}, recorder))
        self.assertEqual(validate(problem(0), board), [])
        self.assertTrue(any(row.get('validation_errors') for row in recorder.calls))

    def test_central_timeout_is_not_hidden(self):
        class TimeoutRecorder(FakeRecorder):
            def decide(self, *args): raise TimeoutError('test timeout')
        with self.assertRaises(TimeoutError):
            asyncio.run(baseline('central', problem(0), {}, TimeoutRecorder()))

    def test_protocol_with_known_valid_model(self):
        board, metadata = asyncio.run(baseline('protocol', problem(0), {}, FakeRecorder()))
        self.assertEqual(validate(problem(0), board), [])
        self.assertGreater(metadata['protocol_messages'], 0)

    def test_central_with_known_valid_model(self):
        board, metadata = asyncio.run(baseline('central', problem(0), {}, FakeRecorder()))
        self.assertEqual(validate(problem(0), board), [])

    def test_schema_exact_pair_and_owners(self):
        self.assertEqual(output_schema('0')['properties']['starts']['maxItems'], 2)
        self.assertEqual(output_schema('central')['properties']['plans']['required'], ['0', '1', '2'])

    def test_invalid_top_level(self):
        self.assertTrue(validate(problem(0), []))
        self.assertTrue(validate(problem(0), None))

    def test_protocol_repair_with_known_valid_model(self):
        class RepairRecorder(FakeRecorder):
            def decide(self, identity, stage, content):
                self.calls.append(content)
                if stage == 'revise': return {'request': 'coordinate'}
                return {'starts': {'0': [0, 1], '1': [1, 9], '2': [3, 11]}[identity]}
        board, metadata = asyncio.run(baseline('protocol', problem(1), {}, RepairRecorder()))
        self.assertEqual(validate(problem(1), board), [])

    def test_feasible(self):
        self.assertEqual(validate(problem(0), {'0': [0, 1], '1': [1, 3], '2': [3, 5]}), [])

    def test_closed_window(self):
        self.assertTrue(validate(problem(1), {'0': [0, 1], '1': [1, 3], '2': [3, 5]}))

    def test_repair(self):
        self.assertEqual(validate(problem(1), {'0': [0, 1], '1': [1, 9], '2': [3, 11]}), [])

    def test_conflicts_and_missing(self):
        self.assertTrue(validate(problem(0), {'0': [0, 1], '1': [1, 1], '2': [1, 2]}))
        self.assertTrue(validate(problem(0), {}))
        self.assertTrue(validate(problem(0), {'0': [True, 1]}))


if __name__ == '__main__': unittest.main()
