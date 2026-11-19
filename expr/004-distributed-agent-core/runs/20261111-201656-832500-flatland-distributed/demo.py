from collections import defaultdict
import json

from agent import Agent, Candidate, Response


class Mailbox:
    def __init__(self):
        self.queues = defaultdict(list)
        self.messages = []

    def send(self, message):
        self.queues[message.receiver].append(message)
        self.messages.append(message)

    def receive(self, receiver):
        messages = self.queues.pop(receiver, [])
        return messages


class ExampleTask:
    def __init__(self, identity):
        self.identity = identity
        self.version = 0
        self.installed = "keep"
        self.broken = False
        self.changed = []
        self.costs = {"A": {"keep": 0, "solo": -8, "joint": -6, "repair": -4},
                      "B": {"keep": 0, "solo": 12, "joint": 2, "repair": 1},
                      "C": {"keep": 0, "solo": 4, "joint": 1, "repair": 1}}[identity]

    def observe(self):
        return {"version": self.version, "broken": self.broken}

    def needs_revision(self, observation):
        return True

    def candidates(self, observation):
        return tuple(Candidate(key, {"arrangement": key}) for key in ["keep", "solo", "joint", "repair"])

    def respond(self, proposal, candidate, observation):
        return Response(True, self.costs[candidate.key], {"conditions": "example feasible arrangement"},
                        {"version": observation["version"], "action": candidate.key})

    def compatible(self, candidate, responses):
        return True

    def valid(self, response, observation):
        return not observation["broken"] and response.private_plan["version"] == observation["version"]

    def install(self, response):
        self.installed = response.private_plan["action"]
        self.version += 1

    def infeasible(self, observation):
        return observation["broken"]

    def revoke(self, observation):
        self.installed = "stop"

    def dependency_changed(self, peer, observation):
        self.changed.append(peer)

    def act(self, observation):
        return self.installed


def run_round(agents, mailbox, round, after_responses=None):
    for agent in agents:
        agent.step(round)
    for phase in range(100):
        batches = {agent.identity: mailbox.receive(agent.identity) for agent in agents}
        for agent in agents:
            for message in batches[agent.identity]:
                agent.think(message)
        if phase == 1 and after_responses:
            after_responses()
        if not any(mailbox.queues.values()):
            break
    if any(mailbox.queues.values()):
        raise RuntimeError("Synchronous negotiation did not finish")
    return {agent.identity: agent.act() for agent in agents}


def build():
    members = ("A", "B", "C")
    mailbox = Mailbox()
    agents = [Agent(identity, members, ExampleTask(identity), mailbox) for identity in members]
    return agents, mailbox


if __name__ == "__main__":
    agents, mailbox = build()
    result = run_round(agents, mailbox, 0)
    print(json.dumps({"actions": result, "messages": len(mailbox.messages),
                      "interpretation": "three-agent protocol demonstration, not benchmark evidence"}, indent=2))
