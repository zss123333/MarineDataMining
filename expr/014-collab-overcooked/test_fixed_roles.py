import unittest
from fixed_roles import ARITIES, canonical_action


class InterfaceTests(unittest.TestCase):
    def test_all_declared_actions(self):
        for name, count in ARITIES.items():
            values = ['1'] if name == 'wait' else ['egg', 'counter'][:count]
            action = name + '(' + ','.join(values) + ')'
            self.assertEqual(canonical_action(action), action)

    def test_format_and_aliases(self):
        self.assertEqual(canonical_action(' pickup(\'egg\', counter1) '), 'pickup(egg,counter)')
        self.assertEqual(canonical_action('place_obj_in_utensil(pot0)'), 'put_obj_in_utensil(pot0)')

    def test_invalid_calls_not_executed(self):
        for action in ('wait(20)', 'pickup(egg)', 'unknown()', 'cook(pot0);deliver_soup()', 'request(cook(pot0))'):
            with self.assertRaises((ValueError, SyntaxError)):
                canonical_action(action)


if __name__ == '__main__':
    unittest.main()
