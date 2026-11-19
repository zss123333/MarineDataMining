# ReAct前瞻实验：开源项目核查与迁移建议

核查日期：2026-11-19。通过 GitHub API 核对以下仓库、源码入口及依赖；尚未完成候选项目的本机端到端运行，以下不是实验结果。

## 1. 首选：AgentBoard 的 PDDL 任务与原生 ReAct

- 仓库：https://github.com/hkust-nlp/AgentBoard
- 核查版本：`bb7255e2daf1989069a186dad9e53f70680961db`。
- 论文：AgentBoard，https://arxiv.org/abs/2401.13178 。
- 原生基线：`agentboard/agents/react_agent.py`；任务封装：`agentboard/environment/pddl_env/pddl_env.py`；仓库内带有 PDDLGym 环境与 PDDL 问题。
- 推荐先选 blockworld 或 gripper，再验证同一项目内的其他规划域；最终使用哪些域必须以实际运行验收为准。

适配原因：环境已有状态转移、合法性检查、任务目标和目标子句进度，不需要继续编写厨房动作适配器；多步动作对后续可执行性的影响更适合检验前瞻。这里先检验单智能体规划机制，不把它冒充多智能体协调实验。

源码核查发现：ReactAgent 已有 Think/Action 循环、记忆和最多连续思考次数配置；ReAct 并不禁止多步规划。我们不能把“允许多想几步”本身写成创新。改进应落实为可保留的未来计划、执行进度、反馈后有效后缀复用与必要重规划。

运行风险：全量 requirements 包含 vLLM、DeepSpeed、Torch 和多个不相关环境，不能直接在现有 Windows 环境里全装。PDDL 封装导入时下载 NLTK punkt，依赖相对工作目录；vendored PDDLGym 的初始化还会导入绘图模块。ReactAgent.run 中的循环没有硬调用上限：格式错误时会持续重试，max_think_iters 主要通过提示催促动作，不是程序级终止保证。运行器必须增加一致的总调用与超时保护，明确记录这项适配。

任务封装的 reward 为历史最高目标子句满足比例，而非单纯当前比例；不能直接把它当作最终任务成功率。应分别记录环境终止成功、最终目标满足比例、历史最高进度和无效动作率。

## 2. 对照规划方法：LLMCompiler

- 仓库：https://github.com/SqueezeAILab/LLMCompiler
- 核查版本：`a00c9d35507507da70e8c637eee64efc8c1857ae`。
- 论文：An LLM Compiler for Parallel Function Calling，ICML 2024。
- 原生 ReAct：`src/react/base.py`；README 提供 `--react`、movie/hotpotqa/parallelqa 任务与 vLLM 接口。
- 实际工具核查：`configs/parallelqa_react/tools.py` 使用 Wikipedia Search 与额外 LLM 数学调用；movie 同样依赖 Wikipedia。不能宣称原任务完全离线可跑。

适合验证工具依赖图、并行执行与调用成本，但动态环境反馈不是它最直接的强项。在同一新任务上接入它属于方法适配，不是原论文结果复现。暂列第二选择，避免当前阶段再引入网络检索波动。

## 3. 显式前瞻参照：LLM Reasoners / RAP

- 仓库：https://github.com/maitrix-org/llm-reasoners
- 核查版本：`f94e5ac2cb9788c3d7d7dbf2173884ed4088e4b2`。
- 入口：`examples/RAP/blocksworld/README.md`；RAP 论文 https://arxiv.org/abs/2305.14992 。
- 仓库有 Blocksworld 数据和规划示例；该示例依赖 LLMs-Planning 子模块、VAL 验证器及模型后端配置，不是 Windows 上直接执行一个脚本即可复现。

适合用作前瞻规划的重要已有方法与后续强对照，但当前不优先部署整套搜索。搜索会增加模型调用，比较时必须同时报告总 token、调用数和耗时，不能只比较外层动作步数。

## 4. 权威来源与其他对照

- 原始 ReAct：https://github.com/ysymyth/ReAct ，核查版本 `6bdb3a1fd38b8188fc7ba4102969fe483df8fdc9`；ICLR 2023，https://arxiv.org/abs/2210.03629 。主要入口为 notebook，示例使用旧 GPT-3 接口，不能直接当现代本地模型运行器。
- Reflexion：https://github.com/noahshinn/reflexion ，核查版本 `218cf0ef1df84b05ce379dd4a8e47f17766733a0`；NeurIPS 2023，https://arxiv.org/abs/2303.11366 。适合检验失败反馈记忆，不等于显式前瞻；多次尝试必须计入预算。
- LangGraph/AutoGen 是可用工程框架，但使用框架本身不构成任务上的强基线，也不自动构成 SOTA。

## 5. 具体执行顺序与验收门槛

1. 固定 AgentBoard 版本，在独立环境中先跑通一个现成 PDDL 问题的 reset、合法动作、step 和目标判定；不修改原始状态转移或降低成功标准。
2. 接入本地模型适配器，保留原生 ReactAgent 控制循环和基线提示，记录适配差异。验收若干公开任务，确认模型不因输出解析反复卡住。1.5B 与 7B 分开报告，不能混为一种方法效果。
3. 若强一些的模型与原生基线仍无法形成非零成功率，不急着加入我们的方法：先区分格式失败、观测理解失败、规划失败，必要时更换任务难度或模型并公开筛选规则。
4. 通过基线验收后，再加入持久滚动计划与反馈修正，双方使用同一任务、模型、观测、工具和预算。先做静态规划；动态扰动与多智能体作为后续扩展，不混入原始任务复现。
5. 正式比较成功率、动作数、无效动作率、LLM 调用数、输入输出 token 与耗时。增加“每步重写计划”和“保留计划但不触发修正”消融，区分长提示、计划记忆与反馈修正的贡献。试跑集与正式评估集分开，保存全部失败运行。

当前下载状态：GitHub API 可读取源码，git clone 连接 github.com:443 失败，codeload 整包下载尚未成功确认。因此当前只确认了源码级可行性与风险，不能报告“已安装”“已跑通”或任何新的成功率。也不据此替换现有报告的实验结论。
