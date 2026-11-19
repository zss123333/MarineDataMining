from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '核心源码'))
from tools import ToolCall, ToolResult, ToolRuntime, ToolSpec


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.runtime = ToolRuntime([
            ToolSpec('produce', frozenset(['A']), lambda inputs: ToolResult(dict(value=1), 2)),
            ToolSpec('consume', frozenset(['B']), lambda inputs: ToolResult(dict(value=inputs['input']['value'] + 1))),
        ])

    def test_dependency_requires_completion(self):
        call = ToolCall('second', 'output', 'consume', ('input',))
        self.assertEqual(self.runtime.submit('B', call).status, 'blocked')
        self.runtime.submit('A', ToolCall('first', 'input', 'produce'))
        self.runtime.advance()
        self.assertEqual(self.runtime.submit('B', call).missing, ('input',))
        self.runtime.advance()
        self.assertEqual(self.runtime.submit('B', call).status, 'running')
        self.runtime.advance()
        self.assertEqual(self.runtime.artifacts['output']['value'], 2)

    def test_capabilities(self):
        self.assertEqual(self.runtime.capabilities('B'), ['consume'])
        self.assertEqual(self.runtime.submit('B', ToolCall('one', 'input', 'produce')).status, 'unavailable')
        self.assertFalse(self.runtime.pending)

    def test_duplicate(self):
        call = ToolCall('one', 'input', 'produce')
        self.runtime.submit('A', call)
        self.assertEqual(self.runtime.submit('A', call).status, 'duplicate')
        with self.assertRaises(ValueError):
            self.runtime.submit('A', ToolCall('one', 'other', 'produce'))

    def test_failure(self):
        runtime = ToolRuntime([ToolSpec('bad', frozenset(['A']), lambda inputs: ToolResult(dict(), 0))])
        self.assertEqual(runtime.submit('A', ToolCall('one', 'input', 'bad')).status, 'failed')
        self.assertFalse(runtime.artifacts)


if __name__ == '__main__':
    unittest.main()
