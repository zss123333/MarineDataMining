from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock
import traceback


class EventLog:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()

    def emit(self, kind, agent=None, peer=None, time=None, **data):
        row = dict(kind=kind, agent=agent, peer=peer, time=time,
                   wall_time=datetime.now(timezone.utc).isoformat(), **data)
        with self.lock, self.path.open('a', encoding='utf-8') as output:
            output.write(json.dumps(row, ensure_ascii=False, default=lambda value:
                                    asdict(value) if is_dataclass(value) else str(value)) + '\n')


class LoggedTransport:
    def __init__(self, transport, log):
        self.transport, self.log = transport, log

    def send(self, message):
        self.log.emit('message_send', agent=message.sender, peer=message.receiver,
                      message=vars(message) if hasattr(message, '__dict__') else message)
        return self.transport.send(message)

    def receive(self, receiver):
        messages = self.transport.receive(receiver)
        for message in messages:
            self.log.emit('message_receive', agent=receiver, peer=message.sender, message=message)
        return messages


class LoggedClock:
    def __init__(self, clock, log):
        self.clock, self.log = clock, log

    def __getattr__(self, name):
        return getattr(self.clock, name)

    def execute(self, identity, action):
        self.log.emit('action_submit', agent=identity, time=self.clock.round(), action=action)
        try:
            result = self.clock.execute(identity, action)
            self.log.emit('action_return', agent=identity, time=self.clock.round(), result=result)
            return result
        except Exception:
            self.log.emit('error', agent=identity, time=self.clock.round(), traceback=traceback.format_exc())
            raise
