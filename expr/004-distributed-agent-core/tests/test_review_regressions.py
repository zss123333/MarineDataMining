import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agent import Message
from demo import build


class ReviewRegressions(unittest.TestCase):
    def test_duplicate_response_does_not_prepare_twice(self):
        agents, mailbox = build()
        owner = agents[0]
        owner.step(0)
        proposals = list(mailbox.messages)
        for member in agents:
            member.think(next(message for message in proposals if message.receiver == member.identity))
        replies = [message for message in mailbox.messages if message.kind == "respond"]
        for message in replies:
            owner.think(message)
        count = sum(message.kind == "prepare" for message in mailbox.messages)
        owner.think(replies[-1])
        self.assertEqual(sum(message.kind == "prepare" for message in mailbox.messages), count)

    def test_duplicate_ready_does_not_commit_twice(self):
        agents, mailbox = build()
        owner = agents[0]
        owner.step(0)
        key = next(iter(owner.proposals))
        owner.ready[key] = {}
        for member in agents:
            owner.think(Message(member.identity, "A", "ready", key, True))
        count = sum(message.kind == "commit" for message in mailbox.messages)
        owner.think(Message("C", "A", "ready", key, True))
        self.assertEqual(sum(message.kind == "commit" for message in mailbox.messages), count)
