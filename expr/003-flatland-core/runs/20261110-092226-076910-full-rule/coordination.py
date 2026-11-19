from dataclasses import asdict, dataclass
import json
import urllib.request


@dataclass
class Commitment:
    owner: int
    version: int
    start: int
    expires: int
    path: list
    status: str = "active"


def conflicts(left, right):
    return left == right or (left[0] == right[1] and left[1] == right[0])


def dependencies(owner, candidate, commitments, now, horizon):
    evidence = []
    for peer, commitment in commitments.items():
        if peer == owner or commitment.status != "active":
            continue
        for offset, cell in enumerate(candidate[:horizon]):
            stamp = now + offset
            index = stamp - commitment.start
            if index < 0 or stamp >= commitment.expires:
                continue
            if index < len(commitment.path):
                other = commitment.path[index]
                edge = (candidate[max(0, offset - 1)], cell)
                other_edge = (commitment.path[max(0, index - 1)], other)
                if cell == other or conflicts(edge, other_edge):
                    evidence.append({"peer": peer, "version": commitment.version,
                                     "use_at": stamp, "kind": "current" if offset == 0 else "predicted",
                                     "evidence": "published route; constant-speed forecast, not guarantee"})
                    break
    return evidence


class Coordinator:
    def __init__(self, horizon=16):
        self.horizon = horizon
        self.commitments = {}
        self.messages = []
        self.pending = {}
        self.repairs = set()
        self.registered = []
        self.versions = {}

    def register(self, consumer, provider, resource, use_at, now):
        commitment = self.commitments[provider]
        item = {"consumer": consumer, "provider": provider, "version": commitment.version,
                "resource": resource, "use_at": use_at, "registered_at": now,
                "kind": "current" if use_at <= now else "future"}
        if item not in self.registered:
            self.registered.append(item)
            self.messages.append({"type": "dependency_register", **item})

    def invalidate_chain(self, owner, now):
        affected = set()
        frontier = [owner]
        while frontier:
            provider = frontier.pop()
            for item in self.registered:
                consumer = item["consumer"]
                if item["provider"] == provider and item["use_at"] >= now and consumer != owner and consumer not in affected:
                    affected.add(consumer)
                    frontier.append(consumer)
        self.repairs.update(affected)
        return affected

    def propose(self, owner, path, now, duration):
        old = self.commitments.get(owner)
        version = self.versions.get(owner, 0) + 1
        self.versions[owner] = version
        proposal = Commitment(owner, version, now, now + duration, path)
        affected = dependencies(owner, path, self.commitments, now, self.horizon)
        if old:
            affected += dependencies(owner, old.path[max(0, now-old.start):],
                                     self.commitments, now, self.horizon)
        peers = {item["peer"] for item in affected}
        peers.update(item["consumer"] for item in self.registered
                     if item["provider"] == owner and item["use_at"] >= now
                     and old is not None and item["version"] == old.version)
        self.pending[owner] = (proposal, peers, set(), now + 3)
        self.messages.append({"type": "propose", "at": now, **asdict(proposal), "peers": sorted(peers)})
        if not peers:
            self.commit(owner, now)
        return peers

    def acknowledge(self, owner, version, peer, now, accept):
        pending = self.pending.get(owner)
        if not pending or pending[0].version != version or peer not in pending[1]:
            return False
        proposal, required, accepted, deadline = pending
        self.messages.append({"type": "ack" if accept else "reject", "owner": owner,
                              "version": version, "peer": peer, "at": now})
        if now > deadline or not accept:
            self.pending.pop(owner)
            return False
        accepted.add(peer)
        if required <= accepted:
            self.commit(owner, now)
        return True

    def commit(self, owner, now):
        proposal, peers, _, _ = self.pending.pop(owner)
        self.invalidate_chain(owner, now)
        self.commitments[owner] = proposal
        self.repairs.update(peers)
        self.messages.append({"type": "replace", "owner": owner, "version": proposal.version, "at": now})

    def revoke(self, owner, now, reason):
        commitment = self.commitments.get(owner)
        if not commitment or commitment.status != "active":
            return
        self.repairs.update(item["peer"] for item in dependencies(
            owner, commitment.path[max(0, now-commitment.start):], self.commitments, now, self.horizon))
        commitment.status = "revoked"
        self.invalidate_chain(owner, now)
        self.pending.pop(owner, None)
        self.messages.append({"type": "emergency_revoke", "owner": owner,
                              "version": commitment.version, "at": now, "reason": reason})

    def expire(self, now):
        for owner, (_, _, _, deadline) in list(self.pending.items()):
            if now > deadline:
                self.pending.pop(owner)
                self.messages.append({"type": "timeout", "owner": owner, "at": now})
        for commitment in self.commitments.values():
            if commitment.status == "active" and now >= commitment.expires:
                commitment.status = "expired"


class Ollama:
    def __init__(self, model="qwen2.5:1.5b"):
        self.model = model
        self.calls = []

    def choose(self, owner, candidates, context):
        schema = {"type": "object", "properties": {"candidate": {"type": "integer",
                  "enum": list(range(len(candidates)))}}, "required": ["candidate"]}
        payload = {"model": self.model, "stream": False, "keep_alive": "15m", "format": schema,
                   "messages": [{"role": "system", "content": "You control one train. Select a candidate minimizing delay and disruptions to teammates. Return JSON only."},
                                {"role": "user", "content": json.dumps({"agent": owner, "candidates": candidates, "context": context})}],
                   "options": {"temperature": 0, "num_ctx": 2048, "num_predict": 24}}
        request = urllib.request.Request("http://localhost:11434/api/chat",
                                         json.dumps(payload).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.load(response)
        selected = json.loads(result["message"]["content"])["candidate"]
        if not isinstance(selected, int) or selected not in range(len(candidates)):
            raise ValueError("Model selected an invalid candidate")
        self.calls.append({"agent": owner, "request": payload, "response": result})
        return selected
