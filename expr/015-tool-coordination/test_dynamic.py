import unittest

import run as shared
from dynamic import DynamicTask, INITIAL
from tools import ToolRuntime


class DynamicTests(unittest.TestCase):
    def setUp(self):
        self.previous = dict(shared.JOBS)
        shared.JOBS.clear()
        shared.JOBS.update(INITIAL)

    def tearDown(self):
        shared.JOBS.clear()
        shared.JOBS.update(self.previous)

    def test_local_scope_preserves_unrelated_worker(self):
        runtime = ToolRuntime([])
        runtime.artifacts['collect'] = dict()
        runtime.pending['reference'] = ('3', 9, None)
        task = DynamicTask('0', runtime, False)
        self.assertEqual(task.proposal_participants(None, task.observe()), ('0', '1'))

    def test_new_dependency_blocks_old_completion(self):
        runtime = ToolRuntime([])
        runtime.artifacts['analyse'] = dict()
        shared.JOBS['verify'] = ('1', ('collect',))
        shared.JOBS['publish'] = ('2', ('analyse', 'verify'))
        task = DynamicTask('2', runtime, False)
        with self.assertRaises(ValueError):
            task.response_from_decision(dict(job='publish'), None, None, task.observe())


if __name__ == '__main__':
    unittest.main()
