import argparse
import asyncio
import contextlib
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import sys


async def evaluate(source, destination):
    sys.path.insert(0, str(source / 'src'))
    sys.path.insert(0, str(source / 'lib/overcooked_ai'))
    from human_coop.policies import RecipePolicy
    from human_coop.session import Session
    from overcooked_ai_py.mdp.overcooked_env import OvercookedEnv
    from overcooked_ai_py.mdp.overcooked_mdp import OvercookedGridworld

    episodes = []
    for order in ('apple', 'boiled_egg', 'boiled_corn_slices', 'baked_carrot_soup'):
        for human_index in (0, 1):
            mdp = OvercookedGridworld.from_layout_name('new_env')
            mdp.start_order_list, mdp.order_probability = [order], {}
            session = Session(OvercookedEnv(mdp, horizon=200), RecipePolicy(), human_index,
                              log_dir=destination / 'traces')
            human = RecipePolicy()
            session.command({'type': 'start'})
            for step in range(180):
                observation = session.observation()
                human_observation = dict(observation, agent_index=human_index,
                                         human_index=1 - human_index)
                human_decision = await human.decide(human_observation)
                agent_decision = await session.policy.decide(observation)
                session.pending_decision = (agent_decision, session.episode_id, session.env.t)
                session.command({'type': 'input', 'keys': [human_decision.action]
                                 if human_decision.action in ('up', 'down', 'left', 'right') else [],
                                 'interaction': {'action': human_decision.action,
                                                 'parameter': human_decision.parameter}
                                 if human_decision.action == 'interact' else None})
                with contextlib.redirect_stdout(io.StringIO()):
                    session.advance()
                if session.done:
                    break
            handoff = any('place_obj_on_counter()' in row['completed_actions'] for row in session.history)
            episodes.append({'order': order, 'human_index': human_index, 'steps': step + 1,
                             'score': session.score, 'remaining_orders': session.env.state.order_list,
                             'done': session.done, 'handoff_in_recent_history': handoff,
                             'passed': session.done and session.score == 20
                                       and not session.env.state.order_list and handoff})
            if session.log:
                session.log.close()
    result = {'scope': 'official scripted RecipePolicy environment acceptance, NOT LLM coordination',
              'environment_gate_passed': all(row['passed'] for row in episodes),
              'llm_execution_gate_passed': False,
              'coordination_comparison_allowed': False,
              'reason': 'Scripted recipe completion does not validate an LLM executor or replace an LLM baseline.',
              'source_hashes': {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                                for name in ('src/human_coop/policies.py', 'src/human_coop/session.py')},
              'episodes': episodes}
    (destination / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    destination = Path(__file__).resolve().parent / 'gate_runs' / datetime.now().strftime('%Y%m%d-%H%M%S')
    destination.mkdir(parents=True)
    result = asyncio.run(evaluate(args.source.resolve(), destination))
    print(json.dumps(result, indent=2))
    print(destination)


if __name__ == '__main__':
    main()
