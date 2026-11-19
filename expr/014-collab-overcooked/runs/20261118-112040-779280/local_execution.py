import copy
import re


EXECUTION_RULES = '''Execution ownership rules (override conflicting planning advice):
Decide using current role space, held objects, observations, successful action
history and teammate instructions. Assistant must plan and execute assigned work;
lack of the full recipe does not prevent following a clear Chef instruction.
If an action is accessible to YOU and prerequisites are satisfied, write it
directly in YOUR plan, NOT inside request(...).
Request only teammate-only work, missing recipe information or dependencies you
cannot satisfy yourself. Explain the actual dependency in say. Never directly
access teammate-only appliances or dispensers. Continue independent local work.
A request is NOT execution. Only observation and successful history establish
completion. Shared counters require real placement and pickup. Never assume a
handoff happened. With empty hands do not place objects; with an empty pot do not
cook. Ask for the missing prerequisite and wait instead of inventing progress.
Use ONLY original skills and arguments. Do not invent recipe steps.
Example: Assistant with empty hands and dispenser access, instructed to fetch egg:
Assistant plan: pickup(egg,ingredient_dispenser);place_obj_on_counter()
Assistant say: I will fetch the egg and put it on the shared counter.
This announces a plan, not a completed handoff. Preserve role analysis/plan/say.
'''


def execution_messages(messages):
    result = copy.deepcopy(messages)
    for message in result:
        if message.get('role') == 'system' and isinstance(message.get('content'), str):
            message['content'] += '\n\n' + EXECUTION_RULES
            return result
    result.insert(0, {'role': 'system', 'content': EXECUTION_RULES})
    return result


def normalize_plan(text):
    pattern = r'((?:Chef|Assistant)\s+plan\s*:)\s*(.*?)(?=\s*(?:Chef|Assistant)\s+say\s*:|$)'

    def replace(match):
        actions = [action.strip() for action in match.group(2).split(';') if action.strip()]
        return match.group(1) + ';'.join(actions) + '\n'

    return re.sub(pattern, replace, text, flags=re.DOTALL | re.IGNORECASE)
