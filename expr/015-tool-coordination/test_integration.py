import unittest

from run import ToolTask, ToolRuntime, ToolSpec, ToolResult, JOBS
from agent import Candidate
from types import SimpleNamespace


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.runtime = ToolRuntime([ToolSpec(name, frozenset([owner]), lambda inputs: ToolResult(dict(), 2))
                                    for name, (owner, dependencies) in JOBS.items()])
        self.task = ToolTask('1', self.runtime)

    def test_dependency_not_satisfied_by_plan(self):
        with self.assertRaises(ValueError):
            self.task.response_from_decision(dict(job='analyse'), None, None, self.task.observe())

    def test_no_planning_for_others(self):
        with self.assertRaises(ValueError):
            self.task.response_from_decision(dict(job='collect'), None, None, self.task.observe())

    def test_installed_plan_becomes_tool_call(self):
        self.runtime.artifacts['collect'] = dict()
        response = self.task.response_from_decision(dict(job='analyse'), None, None, self.task.observe())
        self.task.install(response)
        call = self.task.act(self.task.observe())
        self.assertEqual(self.runtime.submit('1', call).status, 'running')
        self.assertNotIn('analyse', self.task.observe()['completed'])
        self.runtime.advance()
        self.runtime.advance()
        self.assertIn('analyse', self.task.observe()['completed'])
        self.assertIsNone(self.task.act(self.task.observe()))


if __name__ == '__main__':
    unittest.main()
