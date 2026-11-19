import math

from agent import Response
from planning import Plan, predict


def initialize(agents):
    departure = 0
    records = []
    for member in agents:
        task = member.task
        departure = max(departure, int(task.train.earliest_departure))
        travel = math.ceil(len(task.fixed_route)/float(task.train.speed_counter.max_speed))+4
        plan = Plan(task.fixed_route, departure, 0,
                    predict(task.train, task.fixed_route, 0, departure, task.horizon), "initial_serial")
        task.install(Response(True, 0, {}, {"version": task.version, "plan": plan}))
        records.append({"agent": member.identity, "departure": departure, "travel_budget": travel})
        departure += travel
    return records, departure
