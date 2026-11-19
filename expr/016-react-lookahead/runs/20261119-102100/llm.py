"""显式模型决策客户端；每次调用保留请求、原始输出和token计数。"""

# json是Python标准库，负责Python字典与JSON文本之间的转换，不负责发送网络请求。
# 例如dumps({"slot": 2})得到文本；loads读取这段文本后重新得到可访问字段的字典。
import json
# time.perf_counter用于记录耗时；它不是日期时间，也不是仿真里的任务时刻。
import time
# urllib.request是标准库HTTP客户端；Ollama在本机运行，但Python仍通过HTTP与它通信。
# HTTP可理解为客户端按约定发送请求、服务端返回结果的通信格式；无需另装requests库。
import urllib.request


class OllamaDecisionModel:
    """只封装模型服务，不生成规则替代答案；任务硬约束由适配器提供。"""
    # 初始化本实例的状态；self字段属于当前对象，不是所有Agent共享的全局变量。
    def __init__(self, model="qwen2.5:1.5b", endpoint="http://localhost:11434/api/chat"):
        # model是服务里注册的模型名称，不是权重文件内容；客户端不会在这里加载或下载权重。
        self.model = model
        # endpoint是完整接口地址：http表示协议，localhost表示本机，11434是端口，/api/chat是聊天接口路径。
        # 因此请求发往本机Ollama服务，不是默认发送到外部云服务；服务没启动会连接失败。
        self.endpoint = endpoint
        # 方括号创建列表，保存该客户端对象生命周期内每一次收到完整外层JSON的调用记录。
        # 多个Agent复用同一客户端时日志放在一起，用identity区分；不会自动把日志当聊天历史发回模型。
        self.calls = []

    # 一次请求对应一个成员在一个阶段的决定；不隐式拼接其他成员或上次调用的对话历史。
    # 先序列化本人上下文，调用本机Ollama，再保存服务端原始响应并解析生成的JSON。
    # 客户端无自动重试和规则回退；HTTP失败不会伪装成某个合法动作。
    def decide(self, identity, stage, context):
        """发送本人上下文，约束输出结构，保留原始证据后返回决策字段。"""
        # Ollama输入由system规则与本次user上下文构成；客户端没有自动历史会话。
        # 这是一个列表，列表元素是字典；role标记消息角色，content是实际交给模型的文字。
        # system给出通用角色约束，user提供当前任务；这些提示不替代后面的硬约束校验。
        # 字典里的**context表示把上下文键值展开进新字典；同名键会覆盖前面的identity或stage，插件应避免冲突。
        # ensure_ascii=False让中文在JSON字符串中保持可读，并不改变传输编码；真正的UTF-8编码在Request前执行。
        messages = [
            {"role": "system", "content": "You are one distributed agent, not a central planner. Decide only your own local change or response. Respect the supplied hard constraints. Return JSON only, using the required schema."},
            {"role": "user", "content": json.dumps({"identity": identity, "stage": stage, **context}, ensure_ascii=False)},
        ]
        # 任务可提供JSON Schema限定合法输出域；缺省仅要求JSON格式。
        # dict.get(键, 默认值)在键缺失时返回默认值，不会抛KeyError。
        # JSON是数据表示格式；JSON Schema则是描述字段类型和取值范围的规则，例如slot必须为整数。
        # format="json"只约束格式；传入Schema可进一步限制字段，但语义和跨Agent冲突仍需程序检查。
        schema = context.get("output_schema", "json")
        # 温度0降低采样随机性；输出token上限和上下文窗口均设为32768。
        # 输出上限不是预留额度：输入也占用上下文，实际可生成长度仍受剩余容量与结束符约束。
        # payload是本次请求的Python字典，稍后会变成HTTP请求体；不是已发出去的数据。
        # stream=False表示服务生成完再一次返回，不逐token推送；因此客户端等待期间不会收到可执行的半截方案。
        # temperature=0减少随机采样，不保证不同服务版本或硬件下完全可复现。
        # num_predict是输出token上限；token是模型分词单位，不等于汉字数或字节数。
        # num_ctx是模型一次处理的上下文窗口，输入和生成内容都占用它；两者都为32768不意味着能容纳32768输入再输出32768。
        payload = {"model": self.model, "messages": messages, "stream": False,
                   "format": schema, "options": {"temperature": 0, "num_predict": 32768, "num_ctx": 32768}}
        # 单调时钟只用于测量本次请求耗时，不与环境轮次混用。
        # 先记开始值，结束时再相减才得到秒数；perf_counter的绝对值本身没有业务含义。
        started = time.perf_counter()
        # 先把字典转JSON字符串再编码UTF-8字节；有data时Request默认POST。
        # 分三层理解：payload是内存字典；json.dumps把它变成JSON字符串；encode把字符串变成网络需要的字节。
        # HTTP请求分为请求方法、地址、请求头和可选请求体。data参数正是请求体，用于携带模型名、消息和选项。
        # GET通常用于获取资源，POST通常用于提交数据让服务处理；Ollama聊天接口要求POST提交生成请求。
        # Request在未传method时按data推断方法：data不是None时选择POST；data为None时选择GET。
        # 这里data是序列化后的字节，因此实际发出POST。不是data这个单词有特殊HTTP含义，也不是所有Python函数都遵循此规则。
        # Request只构造请求对象，尚未联网；下方urlopen才真正发送。
        # headers设置Content-Type为application/json，是告诉接收方请求体按JSON解释，不是要求模型输出JSON；输出由format约束。
        request = urllib.request.Request(self.endpoint, data=json.dumps(payload).encode("utf-8"),
                                         headers={"Content-Type": "application/json"})
        # with确保响应连接关闭；timeout限制底层阻塞操作，不是整个实验总时限。
        # urlopen发送上面的请求，等待HTTP响应；连接失败、超时或HTTP错误会抛异常，本函数没有吞掉它们。
        # timeout=180的单位是秒，约束底层阻塞操作，不保证整个调用总耗时精确小于180秒。
        # with...as把响应对象命名为connection，正常结束或代码异常退出时都会关闭响应资源。
        with urllib.request.urlopen(request, timeout=180) as connection:
            # json.load从可读取的响应对象直接读数据，得到服务端外层字典；它与读取字符串的json.loads不同。
            # 例如外层是{"message":{"content":"{\"slot\":2}"},"eval_count":8}，其中content本身仍是一段文本。
            result = json.load(connection)
        # 外层JSON读取成功后先存原始证据，内层生成JSON解析失败时仍能检查原文。
        # 这里只存内存；写文件由实验驱动负责，HTTP读取失败则尚未执行这一步。
        # append是在列表尾部追加一条记录，不覆盖前次记录；request与response保留复核模型输入输出所需内容。
        # seconds是当前时钟减开始值，包含等待服务与读取外层JSON的耗时，不是模型纯GPU计算耗时。
        # 此处未深拷贝payload/result，调用方应避免再修改日志对象；永久保存由实验运行器写文件完成。
        self.calls.append({"identity": identity, "stage": stage, "request": payload,
                           "response": result, "seconds": time.perf_counter()-started})
        # Ollama外层响应与模型生成内容是两层JSON；此处解析的是模型文本，不是HTTP信封。
        # 方括号按键逐层取值：先取message字典，再取content字符串，最后loads将模型文本转换为Python对象。
        # 如果字段缺失会KeyError，content不是合法JSON会JSONDecodeError；不会自动选一个规则答案顶替。
        # 单独执行loads可以得到字典、列表或数字；所以下面还必须要求顶层类型为dict。
        # 类型变化示例：模型原始content是字符串 '{"slot": 2}'，解析后的decision是字典{"slot": 2}。
        # 因此最终返回的decision不是一段自然语言，而是可按字段读取的Python字典。
        # 如果模型回答“我建议第2时刻执行”，这不是合法JSON，会在此解析失败；当前没有自然语言转计划模块。
        decision = json.loads(result["message"]["content"])
        if not isinstance(decision, dict):
            raise ValueError("Model decision must be a JSON object")
        # 本客户端只完成格式解析与顶层类型检查，不解释slot等任务字段，也不直接执行动作。
        # 返回链路：本方法 → Agent.model_decision → start或generate_response中的decision变量。
        # revise阶段：Agent.start把字典交给task.candidates_from_decision，生成Candidate候选。
        # respond阶段：Agent.generate_response把字典交给task.response_from_decision，生成本人的Response。
        # 具体例子见expr/011-llm-coordination/run.py：读取decision["slot"]，检查整数与合法时间范围，
        # 再构造PlanPatch；通过组合检查及prepare/ready/commit后，task.install才把补丁安装到本地计划。
        # 字典中即使另有reason等自然语言字段，也只是字段值；是否使用由任务插件定义，核心不会把它当指令执行。
        return decision
