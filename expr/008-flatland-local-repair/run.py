import copy
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "004-distributed-agent-core/src"))
sys.path.insert(0, str(ROOT.parent / "003-flatland-core/src"))
from agent import PlanPatch, SegmentedPlan
from planning import routes
from flatland.envs.persistence import RailEnvPersister


def overlaps(first, second):
    return max(first[0], second[0]) < min(first[1], second[1])


def initial_plans(env):
    plans = []
    cursor = 0
    for train in env.agents:
        route = routes(env, train, limit=1)[0]
        dwell = round(1/float(train.speed_counter.max_speed))
        start = max(cursor, int(train.earliest_departure))
        segments = {str(index): {"resource": list(state[0]), "enter": start+index*dwell,
                                  "exit": start+(index+1)*dwell}
                    for index, state in enumerate(route)}
        plans.append(SegmentedPlan(segments))
        cursor = start+len(route)*dwell+4
    return plans


def local_response(plan, quotes, forced_delay=0):
    original = copy.deepcopy(plan.segments)
    values = copy.deepcopy(original)
    shift = forced_delay
    for key, segment in values.items():
        segment["enter"] += shift
        segment["exit"] += shift
        while True:
            blocking = [other for quote in quotes for other in quote.values()
                        if other["resource"] == segment["resource"]
                        and overlaps((segment["enter"], segment["exit"]), (other["enter"], other["exit"]))]
            if not blocking:
                break
            extra = max(other["exit"] for other in blocking)-segment["enter"]
            shift += extra
            segment["enter"] += extra
            segment["exit"] += extra
    changed = {key: value for key, value in values.items() if value != original[key]}
    if not changed:
        return None
    return PlanPatch(dict(plan.versions), changed)


def repair(plans, delay):
    original = [copy.deepcopy(plan.segments) for plan in plans]
    quotes = {}
    patches = {}
    messages = []
    for identity, plan in enumerate(plans):
        relevant = [peer for peer, quote in quotes.items()
                    if any(first["resource"] == second["resource"]
                           and overlaps((first["enter"], first["exit"]), (second["enter"], second["exit"]))
                           for first in quote.values() for second in plan.segments.values())]
        if identity and not relevant:
            continue
        for peer in relevant:
            messages.append({"sender": peer, "receiver": identity, "kind": "changed_windows",
                             "windows": quotes[peer]})
        patch = local_response(plan, [quotes[peer] for peer in relevant], delay if identity == 0 else 0)
        if patch:
            patches[identity] = patch
            quote = copy.deepcopy(plan.segments)
            quote.update(patch.updates)
            quotes[identity] = quote
    proposed = [copy.deepcopy(plan.segments) for plan in plans]
    for identity, patch in patches.items():
        proposed[identity].update(patch.updates)
    conflicts = []
    for identity, first in enumerate(proposed):
        for peer in range(identity+1, len(proposed)):
            for left in first.values():
                for right in proposed[peer].values():
                    if left["resource"] == right["resource"] and overlaps((left["enter"], left["exit"]), (right["enter"], right["exit"])):
                        conflicts.append([identity, peer, left["resource"]])
    confirmed = not conflicts and all(plans[identity].valid(patch) for identity, patch in patches.items())
    if confirmed:
        for identity, patch in patches.items():
            plans[identity].apply(patch)
    unchanged = sum(value == plans[identity].segments[key] for identity, segments in enumerate(original)
                    for key, value in segments.items())
    return {"delay": delay, "participants": sorted(patches), "messages": messages,
            "patches": {identity: asdict(patch) for identity, patch in patches.items()},
            "confirmed": confirmed, "conflicts": conflicts, "unchanged_segments": unchanged,
            "total_segments": sum(len(plan.segments) for plan in plans),
            "versions": [plan.versions for plan in plans], "original": original,
            "final": [plan.segments for plan in plans]}


def main():
    target = ROOT / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target.mkdir(parents=True)
    results = []
    for level in range(3):
        source = ROOT.parent / f"datasets/mpc-flatland-v1/Test_00_Level_{level}.pkl"
        for delay in [40, 120, 240]:
            env, _ = RailEnvPersister.load_new(str(source))
            result = repair(initial_plans(env), delay)
            result["scenario"] = source.name
            results.append(result)
            print(level, delay, result["participants"], result["confirmed"], result["unchanged_segments"], flush=True)
    (target / "results.json").write_text(json.dumps(results, indent=2, default=int), encoding="utf-8")
    (target / "runner.py").write_bytes(Path(__file__).read_bytes())
    print(target)


if __name__ == "__main__":
    main()
