import unittest

from compare import ComparisonTask
from run import ToolRuntime, ToolSpec, ToolResult, ToolCall


class TriggerTests(unittest.TestCase):
    def test_no_recoordination_while_all_ready_work_running(self):
        runtime = ToolRuntime([ToolSpec('collect', frozenset(['0']), lambda inputs: ToolResult(dict(), 4)),
                               ToolSpec('reference', frozenset(['2']), lambda inputs: ToolResult(dict(), 4))])
        runtime.submit('0', ToolCall('collect', 'collect', 'collect'))
        runtime.submit('2', ToolCall('reference', 'reference', 'reference'))
        event_task = ComparisonTask('0', runtime, False)
        periodic_task = ComparisonTask('0', runtime, True)
        self.assertFalse(event_task.needs_revision(event_task.observe()))
        self.assertTrue(periodic_task.needs_revision(periodic_task.observe()))
        for step in range(4):
            runtime.advance()
        self.assertTrue(event_task.needs_revision(event_task.observe()))


if __name__ == '__main__':
    unittest.main()
