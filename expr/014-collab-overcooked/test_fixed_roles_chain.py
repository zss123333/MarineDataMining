import sys
import tempfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from fixed_roles import install


class ValidationChainTests(unittest.TestCase):
    def test_alias_reaches_validator_as_current_action(self):
        class FakeAgent:
            name = 'Chef'
            current_ml_action = ' place_obj_in_utensil(pot0) '

            def parse_ml_action(self, action):
                return True, action

            def generate_state_prompt(self, state):
                return ''

            def validate_current_ml_action(self, state):
                if self.current_ml_action != 'put_obj_in_utensil(pot0)':
                    raise ValueError('Wrong action')
                return 'success'

        module = ModuleType('collab.collab')
        module.LLMAgents = FakeAgent
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(sys.modules, {'collab.collab': module}):
                install(None, Path(directory))
            agent = FakeAgent()
            self.assertEqual(agent.validate_current_ml_action(None), 'success')
            self.assertEqual(agent.current_ml_action, 'put_obj_in_utensil(pot0)')
            agent.current_ml_action = 'invented(pot0)'
            self.assertIn('Unknown skill', agent.validate_current_ml_action(None))


if __name__ == '__main__':
    unittest.main()
