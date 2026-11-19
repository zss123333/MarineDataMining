from collections import deque
from dataclasses import dataclass
import math


DELTAS = [(-1, 0), (0, 1), (1, 0), (0, -1)]


def routes(env, agent, limit=3):
    position = agent.position if agent.position is not None else agent.initial_position
    direction = agent.direction if agent.position is not None else agent.initial_direction
    start = (tuple(position), int(direction))

    def search(forbidden):
        queue = deque([start])
        parents = {start: None}
        while queue:
            state = queue.popleft()
            if state[0] == tuple(agent.target):
                result = []
                while state is not None:
                    result.append(state)
                    state = parents[state]
                return result[::-1]
            for heading, allowed in enumerate(env.rail.get_transitions(state)):
                if allowed:
                    delta = DELTAS[heading]
                    neighbor = ((state[0][0] + delta[0], state[0][1] + delta[1]), heading)
                    if neighbor not in parents and (state, neighbor) not in forbidden:
                        parents[neighbor] = state
                        queue.append(neighbor)
        return []

    first = search(set())
    if not first:
        return []
    found = [first]
    for index in range(len(first) - 1):
        alternative = search({(first[index], first[index + 1])})
        if alternative and alternative not in found:
            found.append(alternative)
        if len(found) >= limit:
            break
    return found


@dataclass
class Plan:
    route: list
    wait_until: int
    published: int
    cells: list
    label: str


def predict(agent, route, now, wait_until, horizon):
    speed = float(agent.speed_counter.max_speed)
    dwell = max(1, math.ceil(1 / speed))
    offmap = agent.position is None
    departure = max(now, wait_until, int(agent.earliest_departure) if offmap else now)
    cells = [None if offmap else route[0][0]] * (departure - now)
    if offmap:
        cells.append(None)
    remaining = max(1, math.ceil((1-float(agent.speed_counter.distance)) / speed))
    for index, (position, _) in enumerate(route):
        cells.extend([position] * (remaining if index == 0 and not offmap else dwell))
    cells.extend([None] * horizon)
    return cells[:horizon]


def collisions(left, right):
    found = []
    for offset, (first, second) in enumerate(zip(left, right)):
        if first is not None and first == second:
            found.append(offset)
        elif offset and first is not None and second is not None:
            if first == right[offset-1] and second == left[offset-1]:
                found.append(offset)
    return found


def candidates(env, agent, now, horizon, old=None):
    result = []
    available = routes(env, agent)
    if old:
        position = agent.position if agent.position is not None else agent.initial_position
        direction = agent.direction if agent.position is not None else agent.initial_direction
        state = (tuple(position), int(direction))
        if state in old.route:
            retained = old.route[old.route.index(state):]
            result.append(Plan(retained, max(now, old.wait_until), now,
                               predict(agent, retained, now, max(now, old.wait_until), horizon), "keep"))
    for path in available:
        for delay in [0, 3, 8, 16]:
            result.append(Plan(path, now + delay, now,
                               predict(agent, path, now, now+delay, horizon),
                               "route_wait"))
    return result


def action(agent, plan, now):
    if now < plan.wait_until:
        return 4
    if agent.position is None:
        return 2
    state = (tuple(agent.position), int(agent.direction))
    if state not in plan.route:
        return 4
    index = plan.route.index(state)
    if index + 1 == len(plan.route):
        return 2
    relative = (plan.route[index+1][1] - int(agent.direction)) % 4
    return {0: 2, 1: 3, 2: 2, 3: 1}[relative]
