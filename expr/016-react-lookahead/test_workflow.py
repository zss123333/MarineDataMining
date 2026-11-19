import unittest
from run import Workflow


class WorkflowTests(unittest.TestCase):
    def test_irreversible_effect_not_hidden(self):
        world = Workflow('review')
        world.act('draft')
        self.assertIn('rejected',world.act('inspect'))
        self.assertIn('rejected',world.act('publish'))
        self.assertFalse(world.done)

    def test_feasible_plan(self):
        world = Workflow('review')
        for action in ('inspect','draft','publish'):
            world.act(action)
        self.assertTrue(world.done)

    def test_no_review_control(self):
        world = Workflow('direct')
        world.act('draft')
        world.act('publish')
        self.assertTrue(world.done)


if __name__ == '__main__':
    unittest.main()
