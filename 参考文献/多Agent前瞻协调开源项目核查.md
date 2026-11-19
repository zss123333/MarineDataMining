# 多 Agent 前瞻协调：开源项目核查

核查日期：2026-11-19。以下是联网读取 README 和部分关键源码后的筛选，不是本机运行结果。研究对象是固定角色之后，各 Agent 的未来计划、跨角色依赖和反馈后的关联修正；单 Agent PDDL 不作为主实验替代品。

## 优先试跑：MultiAgentBench / MARBLE

- 仓库：https://github.com/ulab-uiuc/MARBLE
- 论文：https://arxiv.org/abs/2503.01935
- 已读取 README、pyproject.toml、scripts/run_benchmark.py、marble/agent/base_agent.py、marble/engine/engine.py、research_env.py、coding_env.py、world_env.py，以及 coding_main.jsonl 第一项。
- Python 要求 >=3.9 且 <3.12。项目声明 Apache 2.0，正式引入时仍须保存原许可证并核对数据条款。

适配点：已有角色配置、Agent 关系图、发送与接收消息、双边通信会话、协调模式及任务数据。coding 首项明确包含多个模块及先后依赖，且关系图配置了三个 Agent，能承接我们固定角色之后的协调研究。运行入口已有任务筛选、迭代上限与中断恢复，不必从零再做协调运行器。

必须注意：

1. base_agent.py 的 react 策略是向通用工具调用代理添加 Observation/Thought/Action/Result 提示，不是原始 ReAct 作者代码的复现。应称“MARBLE 的 ReAct 提示策略多智能体基线”。正式论文比较还应复用其原生协调配置，不能只自定义一个弱提示。
2. coding 第一题是大型软件开发需求，不是带完备确定性单元测试的小型编程题。环境还会调用 LLM 工具；不能把外层调用数视为全部成本，也不能直接把评分当可执行正确率。
3. research 有 arXiv/Semantic Scholar 等外部检索依赖，README 所谓无需外部服务不能理解为无需网络。bargaining 更轻，但偏竞争协商，不足以证明协作依赖规划。
4. communication/planning/milestone 指标涉及 LLM 裁判，应与最终任务结果、实际交付物和成本分开，不能只凭主观协调分宣称效果更好。
5. 当前主分支 README 记录了多项近期修复，包括任务解析、评估和数据重复。必须在成功获取源码后锁定 commit，同时区分该版本与论文发布版本。本次未能通过 API 确认其 commit，不能将 main 视为可复现版本。

结论：作为低仿真部署成本的首个工程验收候选，而不是已经确定足够强的主实验。先验收原生 coding 协作路径、交付物和评估机制；若缺少可靠结果判定，不为了得分而另造裁判或大幅改题。

## 最贴近显式合作规划：CoELA

- https://github.com/UMass-Embodied-AGI/CoELA
- 核查 commit：3e12dea925d735eefce33da71806ae9da6fcaf3f。
- Building Cooperative Embodied Agents Modularly with Large Language Models，ICLR 2024；https://arxiv.org/abs/2307.02485 。
- C-WAH 与 TDW-MAT 提供具身协作任务和通信。README 明确 C-WAH 发送消息占一步且有长度上限；TDW-MAT 有搬运目标和容器容量约束，并提供 HP 与 CoELA 实验脚本。
- 风险：C-WAH 要额外下载 Linux x86-64 模拟器；TDW 涉及独立仿真运行环境，远程 Linux 还需 X server。不能直接称为当前 Windows 的即装即用方案。

结论：任务依赖、通信成本与可观测执行结果更贴近主研究，应优先评估有无可用 Linux/WSL 和仿真资源。保留原生高层动作接口，不重新编写抓取等底层操作。

## 直接相关方法：RoCo

- https://github.com/MandiZhao/robot-collab
- 核查 commit：9943870298e650de7ff1f9231ed279b35f196ddc。
- RoCo: Dialectic Multi-Robot Collaboration with Large Language Models；https://arxiv.org/abs/2307.04738 。
- README 原生入口：python run_dialog.py --task pack -llm gpt-4。
- 已读取 prompting/dialog_prompter.py：已有对话历史、失败计划、环境反馈和多次重规划配置。这说明“通过对话考虑未来并根据反馈重规划”已有直接相关工作，不能泛称首创。
- 风险：MuJoCo 2.3.0、dm_control 1.0.8 和机器人路径/碰撞反馈；仍有底层轨迹规划开销，不适合为了快速完成实验立即全量迁移。

结论：重要方法参照，后续同任务比较必须明确适配；不把抽出提示词运行于新任务称为原论文复现。

## PARTNR：已有明确多 Agent ReAct，但部署重

- https://github.com/facebookresearch/partnr-planner
- 核查 commit：ddfff19f4b6c098a31edea4d19e7b75db72433c2。
- https://arxiv.org/abs/2411.00081 ，仓库声明 MIT。
- README 明确给出 decentralized_zero_shot_react_summary、centralized_zero_shot_react_summary 和 single_agent_zero_shot_react_summary 原生配置。
- 关键限制：README 明确去中心化规划器之间没有显式通信；不能直接拿该配置证明消息协调机制优越。依赖 Habitat、场景资源与模型推理环境，安装需单独核查。

结论：多 Agent ReAct 基线来源很明确，但不作为当前最快落地选择。增加显式通信会改变原配置，必须标注。

## ProAgent：主动合作相关，但不重返厨房调试

- https://github.com/PKU-Alignment/ProAgent
- 核查 commit：8aa0e6563b368d2220e0ac3fff44d0d971b5715b。
- AAAI 2024，主动协作方法；README 有 analysis/intention 层级与 Greedy 等现成对照。
- README 推荐 Linux/WSL、Python 3.7；部分训练基线加载需要 TensorFlow 1。已有大量传统策略对照，但不意味着它们都适用于我们的消息与多步依赖研究。

结论：列入相关方法，不优先部署，避免回到此前厨房操作与旧依赖问题。

## 推进顺序

1. 先获取并锁定 MARBLE 源码，在隔离环境检查三角色 coding 原生任务的工具链、交付物、通信日志和结果评估；只做小规模验收，不先宣称其为最终主基准。
2. 同时在部署决策层确认 CoELA 的仿真资源条件。若具备 Linux 和足够资源，优先用其已有环境评估真实任务成功与通信成本；否则明确暂缓，不自行重写简化模拟器冒充原基准。
3. 原生基线能稳定产生有意义结果后，再接入我们的跨 Agent 未来依赖维护。对照包括原生协作方法、各自独立多步规划、跨 Agent 计划关联与反馈修正；所有方法统一角色、观测、工具、任务与预算。
4. 保存所有模型调用（包括工具内部和裁判）、真实收发消息、计划版本、工具回执与终止原因。任务成功优先于主观协调得分，试跑集不用于最终收益结论。

本次结论：存在可以复用的多 Agent 项目，但没有一个已在本机完成验收。GitHub API 随后触发未认证限流；关键文件改由 raw.githubusercontent.com 读取。没有启动新付费实验，也没有修改报告中的实验结果。
