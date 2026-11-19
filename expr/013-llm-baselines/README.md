# LLM协调框架对照预实验

这是开发预实验，不是高复杂任务benchmark，也不是论文SOTA复现。目标先验证：同一本机模型面对两工序、跨成员前置依赖、两个共享资源及资源关闭变化时，不同协调组织方式能否生成可执行安排。

## 对照来源

- 外部实现：Microsoft AutoGen AgentChat 0.7.5 的原生 `AssistantAgent` 与 `RoundRobinGroupChat`，并非我们自行仿写轮询。源码：https://github.com/microsoft/autogen/tree/python-v0.7.5/python/packages/autogen-agentchat 。
- 相关论文：AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation，https://arxiv.org/abs/2308.08155 。现代0.7.5实现与论文当时版本不同，本实验是框架级任务适配，不称完整论文复现或2026 SOTA。
- 无通信LLM、集中式LLM是本实验实现的基础对照，不冒称有独立论文算法出处。
- protocol调用现有核心Agent、版本化补丁、公开组合检查及prepare/commit流程，不重新实现另一份协议。

## 预先固定条件

3名成员，各有准备与完成两道工序，两个容量1资源，两条跨成员前置依赖。初次安排后，在执行前公布finish资源区间[3,9)关闭，各方法重新生成安排。这是执行前窗口变化，不是执行中抢占。

统一Qwen2.5-1.5B、温度0、相同每阶段调用上限（见各批manifest，首轮18次，结构化输出调试轮9次）、每次至多256输出token，失败不以规则求解器补答案。所有方法获得同一完整任务描述，因此本实验不检验私有信息保护；中央方法有权直接输出全体安排，其他方法只输出本人安排。协议额外的发起模型调用计入预算。后续调试轮用JSON Schema限定字段形状，不提供合法时间候选或答案。

统一校验器检查类型、释放时刻、时域、本人顺序、跨成员依赖、资源互斥与关闭窗口。校验器仅报告错误，不生成候选、不修正模型时间。无通信方法仅接收自身约束错误，不接收队友计划；其他方法获得公开冲突反馈。AutoGen保留原生群聊历史，其他方法使用显式公开板，输入token差异如实记录。

每阶段合法安排才允许整体执行，非法计划完成数记0；完成数由合法时间表推导，不是外部具身模拟器实测。只有一个固定开发实例及其动态变体，不能支持统计优势、复杂任务泛化或领先现有研究的结论。尚未启用精细影响范围、跨阶段复用账本等全部机制。

## 运行与证据

现有003 Python3.11隔离环境已安装autogen-agentchat和autogen-ext[openai] 0.7.5，不安装到全局Python。模型服务为本机Ollama。

```powershell
& 最终作业/expr/003-flatland-core/.venv/Scripts/python.exe -m unittest discover -s 最终作业/expr/013-llm-baselines -p 'test_*.py' -v
& 最终作业/expr/003-flatland-core/.venv/Scripts/python.exe 最终作业/expr/013-llm-baselines/run.py
```

每批开始保存manifest、任务、参数与核心源码快照；每次真实响应后保存原始请求、回答及服务token统计。保留失败批次，不按结果挑选实例，不自动写入最终报告。
