import ast
import json
import re


ALIASES = {'place_obj_in_utensil': 'put_obj_in_utensil',
           'put_obj_on_counter': 'place_obj_on_counter'}
ARITIES = {'pickup': 2, 'put_obj_in_utensil': 1, 'fill_dish_with_food': 1,
           'cook': 1, 'bake': 1, 'cut': 1, 'stir': 1, 'wait': 1,
           'place_obj_on_counter': 0, 'deliver_soup': 0, 'check_recipe': 0}
CONTRACT = '''Fixed roles, assigned before execution; do not negotiate initialization.
Chef owns receiving ingredients from shared counters, pot/oven processing and serving.
Assistant owns fetching raw ingredients and dishes, chopping/blending when required
by the real recipe, and placing requested deliveries on shared counters.
Execute your own work directly. Request only teammate-owned work or missing information.
After placing a requested delivery, do not take it back unless explicitly reassigned.
Requests do not prove completion. Observe hands, counters and appliances every turn.
The authoritative_observation below is actual environment state, not a predicted plan.
Use the supplied original recipe; never add invented processing steps.
Canonical skills: pickup(obj,place), put_obj_in_utensil(utensil),
place_obj_on_counter(), fill_dish_with_food(utensil), cook(pot), bake(oven),
cut(chopping_board), stir(blender), deliver_soup(), check_recipe(), wait(1..5).
Only use your accessible appliances. Requests are communication, not automatic execution.
Put dependency/help requests in the say field, never use [NOTHING] when asking for help.
Plan/say/analysis must retain the original role-labelled format.
'''


def canonical_action(text):
    text = text.strip()
    expression = ast.parse(text, mode='eval').body
    if not isinstance(expression, ast.Call) or not isinstance(expression.func, ast.Name) or expression.keywords:
        raise ValueError('Expected a skill call')
    name = ALIASES.get(expression.func.id, expression.func.id)
    if name not in ARITIES or len(expression.args) != ARITIES[name]:
        raise ValueError('Unknown skill or wrong argument count')
    values = []
    for argument in expression.args:
        if isinstance(argument, ast.Name):
            value = argument.id
        elif isinstance(argument, ast.Constant) and type(argument.value) in (str, int):
            value = str(argument.value)
        else:
            raise ValueError('Skill arguments must be names or scalar values')
        if re.fullmatch(r'counter\d+', value):
            value = 'counter'
        if not re.fullmatch(r'[a-zA-Z_][a-zA-Z_0-9]*|[0-9]+', value):
            raise ValueError('Invalid argument')
        values.append(value)
    if name == 'wait' and not (values[0].isdigit() and 1 <= int(values[0]) <= 5):
        raise ValueError('wait must be between 1 and 5')
    return name + '(' + ','.join(values) + ')'


def install(source, target):
    from collab.collab import LLMAgents

    original_parse = LLMAgents.parse_ml_action
    original_validate = LLMAgents.validate_current_ml_action
    original_state = LLMAgents.generate_state_prompt
    audit = target / 'interface-events.jsonl'

    def record(row):
        with audit.open('a', encoding='utf-8') as output:
            output.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')

    def parse(self, action):
        try:
            canonical = canonical_action(action)
        except (ValueError, SyntaxError) as error:
            record(dict(kind='interface_reject', agent=self.name, original=action, reason=str(error)))
            return False, str(error) + '. Use canonical skills and actual observed prerequisites.'
        record(dict(kind='interface_parse', agent=self.name, original=action, canonical=canonical))
        return original_parse(self, canonical)

    def state_prompt(self, state):
        text = original_state(self, state)
        player = state.players[self.agent_index]
        snapshot = dict(time=state.timestep, role=self.name, order=self.order,
                        self_state=player.to_dict(),
                        environment=state.to_dict(),
                        current_action=self.current_ml_action,
                        queued_actions=list(self.action_wait_parse.queue))
        record(dict(kind='observation', **snapshot))
        return CONTRACT + '\nauthoritative_observation=' + json.dumps(snapshot, default=str) + '\n' + text

    def validate(self, state):
        if self.current_ml_action is not None:
            original = self.current_ml_action
            try:
                self.current_ml_action = canonical_action(original)
            except (ValueError, SyntaxError) as error:
                record(dict(kind='interface_reject', agent=self.name, original=original, reason=str(error)))
                return str(error) + '. Use canonical skills and actual observed prerequisites.'
            if original != self.current_ml_action:
                record(dict(kind='interface_normalize_current', agent=self.name,
                            original=original, canonical=self.current_ml_action))
        return original_validate(self, state)

    LLMAgents.parse_ml_action = parse
    LLMAgents.validate_current_ml_action = validate
    LLMAgents.generate_state_prompt = state_prompt
