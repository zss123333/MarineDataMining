"""显式模型决策客户端；每次调用保留请求、原始输出和token计数。"""

import json
import time
import urllib.request


class OllamaDecisionModel:
    """只封装模型服务，不生成规则替代答案；任务硬约束由适配器提供。"""
    # 初始化本实例的状态；self字段属于当前对象，不是所有Agent共享的全局变量。
    def __init__(self, model="qwen2.5:1.5b", endpoint="http://localhost:11434/api/chat"):
        self.model = model
        self.endpoint = endpoint
        self.calls = []

    # 一次请求对应一个成员在一个阶段的决定；不隐式拼接其他成员或上次调用的对话历史。
    # 先序列化本人上下文，调用本机Ollama，再保存服务端原始响应并解析生成的JSON。
    # 客户端无自动重试和规则回退；HTTP失败不会伪装成某个合法动作。
    def decide(self, identity, stage, context):
        """发送本人上下文，约束输出结构，保留原始证据后返回决策字段。"""
        # Ollama输入由system规则与本次user上下文构成；客户端没有自动历史会话。
        messages = [
            {"role": "system", "content": "You are one distributed agent, not a central planner. Decide only your own local change or response. Respect the supplied hard constraints. Return JSON only, using the required schema."},
            {"role": "user", "content": json.dumps({"identity": identity, "stage": stage, **context}, ensure_ascii=False)},
        ]
        # 任务可提供JSON Schema限定合法输出域；缺省仅要求JSON格式。
        schema = context.get("output_schema", "json")
        # 温度0降低采样随机性，96限制输出token，2048是上下文窗口；均不保证语义正确。
        payload = {"model": self.model, "messages": messages, "stream": False,
                   "format": schema, "options": {"temperature": 0, "num_predict": 96, "num_ctx": 2048}}
        # 单调时钟只用于测量本次请求耗时，不与环境轮次混用。
        started = time.perf_counter()
        # 先把字典转JSON字符串再编码UTF-8字节；有data时Request默认POST。
        request = urllib.request.Request(self.endpoint, data=json.dumps(payload).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
        # with确保响应连接关闭；timeout限制底层阻塞操作，不是整个实验总时限。
        with urllib.request.urlopen(request, timeout=180) as connection:
            result = json.load(connection)
        # 外层JSON读取成功后先存原始证据，内层生成JSON解析失败时仍能检查原文。
        # 这里只存内存；写文件由实验驱动负责，HTTP读取失败则尚未执行这一步。
        self.calls.append({"identity": identity, "stage": stage, "request": payload,
                           "response": result, "seconds": time.perf_counter()-started})
        # Ollama外层响应与模型生成内容是两层JSON；此处解析的是模型文本，不是HTTP信封。
        return json.loads(result["message"]["content"])
