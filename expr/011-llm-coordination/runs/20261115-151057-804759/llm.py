"""显式模型决策客户端；每次调用保留请求、原始输出和token计数。"""

import json
import time
import urllib.request


class OllamaDecisionModel:
    def __init__(self, model="qwen2.5:1.5b", endpoint="http://localhost:11434/api/chat"):
        self.model = model
        self.endpoint = endpoint
        self.calls = []

    def decide(self, identity, stage, context):
        messages = [
            {"role": "system", "content": "You are one distributed agent, not a central planner. Decide only your own local change or response. Respect the supplied hard constraints. Return JSON only, using the required schema."},
            {"role": "user", "content": json.dumps({"identity": identity, "stage": stage, **context}, ensure_ascii=False)},
        ]
        schema = context.get("output_schema", "json")
        payload = {"model": self.model, "messages": messages, "stream": False,
                   "format": schema, "options": {"temperature": 0, "num_predict": 96, "num_ctx": 2048}}
        started = time.perf_counter()
        request = urllib.request.Request(self.endpoint, data=json.dumps(payload).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=180) as connection:
            result = json.load(connection)
        self.calls.append({"identity": identity, "stage": stage, "request": payload,
                           "response": result, "seconds": time.perf_counter()-started})
        return json.loads(result["message"]["content"])
