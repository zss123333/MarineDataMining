import unittest

from local_execution import execution_messages, normalize_plan


class LocalExecutionTests(unittest.TestCase):
    def test_instruction_copy(self):
        messages = [dict(role='system', content='original')]
        result = execution_messages(messages)
        self.assertEqual(messages[0]['content'], 'original')
        self.assertIn('NOT inside request', result[0]['content'])

    def test_missing_system(self):
        self.assertEqual(execution_messages([])[0]['role'], 'system')

    def test_plan_whitespace(self):
        text = 'Chef analysis: think; wait\nChef plan: pickup(egg,counter); place_obj_on_counter();\nChef say: hello; friend'
        result = normalize_plan(text)
        self.assertIn('Chef plan:pickup(egg,counter);place_obj_on_counter()\n', result)
        self.assertIn('Chef say: hello; friend', result)
        self.assertIn('Chef analysis: think; wait', result)

    def test_no_semantic_rewrite(self):
        text = 'Assistant plan: request(cook(pot0))\nAssistant say: help'
        self.assertIn('request(cook(pot0))', normalize_plan(text))


if __name__ == '__main__':
    unittest.main()
