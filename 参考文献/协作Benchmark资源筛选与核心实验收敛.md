# 协作 Benchmark 资源筛选与核心实验收敛

核查日期：2026-11-09。目标：尽量复用现成任务、环境、动作接口与评测，不先自建危险品模拟器。证据来自官方仓库README、任务文件和部分源码；本轮没有安装或跑通这些新候选，因此“开源存在”不等于“本机已经可运行”。不把资料筛选冒充逐篇论文精读。

## 1. 方法还需要收敛，但不必继续扩大理论

[方案设计](../方案设计.md)足以作为方向和架构说明，但还不是冻结的核心实验协议。当前同时涉及承诺期限、未来依赖预测、前瞻候选、消息版本、确认、修复及紧急撤销；若全部作为独立创新实现，会拖慢开发并使结果无法归因。

建议只保留一个核心决策问题：**当Agent考虑撤销或改变一个仍有效的承诺时，是否检查队友有限未来计划的依赖，并据此决定保持还是提出可行替代？**

固定：规划窗口、宏动作执行器、检查时机、通信预算、基础模型。被测差别：不检查依赖、只检查当前依赖、检查当前与未来依赖。加入固定期限和规则依赖保护强基线。确认、版本与安全校验是公共基础设施，不各自包装创新。第一版不学习最优承诺深度、不研究无限递归相互建模。

任务选定后才确定承诺对应何种交付、可验证前提、期限单位和失败条件。这不是随意“具体情况具体分析”，而是对同一个决策规则做任务实例化。

## 2. 筛选标准

必须分别检查：单Agent是否原生无法完成；是否存在先后/交接依赖；是否有原生异步或扰动；是否有明确程序判定失败；是否已有LLM动作与观测；本机Windows、CPU、Qwen2.5-1.5B的适配成本。不要把合作奖励自动等同于必须协作，也不要把碰撞被程序阻止描述为撞车灾难。

## 3. 优先候选

### A. Collab-Overcooked：最省Agent适配工作的首选

- [官方仓库](https://github.com/YusaeMeow/Collab-Overcooked)
- [环境规则](https://github.com/YusaeMeow/Collab-Overcooked/blob/main/src/prompts/gpt/environment_rule_multi_task.txt)
- [现成复杂任务示例](https://github.com/YusaeMeow/Collab-Overcooked/blob/main/src/prompts/recipe/6_potato_carrot_and_onion_patty.txt)
- 本轮main快照：`d7ae1aa5e63d8ec076e96ee437fcbbd095278ef4`。正式使用固定commit，不能一直跟随main。

已经提供：多LLM Agent框架、自然语言交互、厨师/助手角色、任务与配方、工具调用、日志和evaluation.py / organize_result.py / convert_result.py。配方目录可核实30个文本任务（6组各5个），不能把任务名数量说成评测episode数量。

规则明确写：仅助手能从食材点拿原料，物品通过公共台面交接，且要检查队友能力。这比原版cramped_room中一个厨师包办全部工作更贴近必要协作。**不过必须进一步验证能力限制由执行代码而非提示独自保证，并验证选定任务的交接确实不可绕过。**

适合承诺：助手在某未来阶段交付原料/半成品；厨师未来加工需要该交付。复杂配方包含切、煮、搅拌、烤及最终装盘，天然有未来前提。可先选已有不同深度配方，不再自己编故事。

原生后果应写为任务失败、错误加工、无效动作和交接延迟。未验证有燃烧、不可逆报废或爆炸；不能为了强调严重后果擅自添加这些结论。若要加入损坏与期限，就属于自定义扩展，不再是零构造复用。

成本风险：官方推荐Python3.8，旧依赖、mpi4py及嵌入模型可能麻烦；有 `requirements-human.txt` 和无需嵌入/API的浏览器模式，也有Chat Completions模型接口，但不能把人机浏览模式直接当原双LLM评测。需要优先复用实际benchmark的离散动作接口，避免把整个旧依赖栈搬进本机。它内置的overcooked_ai与我们安装的上游不是相同API，必须隔离，不覆盖实验001依赖。

**推荐地位：时间优先且以LLM语义承诺为主线时，首先验证此候选。**

### B. Flatland：强协调失败后果的首选

- [环境](https://github.com/flatland-association/flatland-rl)
- [现成场景与竞赛任务](https://github.com/flatland-association/flatland-scenarios)
- [官方基线](https://github.com/flatland-association/flatland-baselines)
- [评测平台代码](https://github.com/flatland-association/flatland-benchmarks)
- 环境本轮main快照：`d1417769b0014f351e42faa92c0c5b7795b8c08d`，MIT。

铁路多Agent路径与时序协调。现成轨道、列车、时刻表、速度差、故障/延迟模型以及竞赛场景。官方场景仓库含Olten铁路网络、受阻版本及任务元数据；不必手工造窄通道。基线仓库提供 shortest-path deadlock avoidance，可作为强规则对照。README明确当前测试覆盖Windows、Python3.11–3.14，但本机尚未安装验证；不同历史场景版本可能需要匹配环境版本。

适合承诺：等待某车通过、在某时段不进入共享区段、按约定路线释放冲突资源。一个Agent尚未进入冲突区，当前让行决定已依赖另一个Agent未来通行/清空。

**原生严重后果是死锁、列车未达终点和大范围延误，不是真实撞车。** 源码含冲突解决机制，不能说“决策不一致就必然碰撞”。它主要是资源竞争下的必要协调，不是两个互补角色共同完成一次物品交付。

额外工作：没有现成适配我们方法的LLM语义接口。应让LLM决定路口/区段层的等待与路线承诺，代码负责轨道合法动作；需提取冲突资源与未来路线依赖，不能直接让1.5B读整张大地图逐步开车。不要将一个中央调度器伪装成独立Agent元认知。

**推荐地位：若“协调失败有明确严重系统后果”是硬条件，优先它。** 不必自造报废规则，但需承担中等接口适配成本，且必须公平对比现成规则调度。

### C. Level-Based Foraging：部署轻、原生强制合作，后果较弱

- [官方仓库](https://github.com/semitable/lb-foraging)，MIT。
- [环境源码](https://github.com/semitable/lb-foraging/blob/master/lbforaging/foraging/environment.py)
- 本轮master快照：`79f383b7db0a3530f14252d5b6cc0d85aa9fb385`。

Agent等级总和达到食物等级才可收集；提供force_coop模式与共享奖励。具有同位置邻域、时机和伙伴选择协调，动作离散，CPU快速，已有Gym接口。选择高等级目标时，必须检查一个Agent不能单独收集，而非只给共享奖励。

适合承诺：将来在指定目标旁共同执行收集，途中是否改变集合目标。原生后果为收集失败、超时及收益损失，不是不可逆事故；未来依赖链通常较浅。适合轻量补充验证，不作为严重后果主场景。无需训练RL即可接LLM。

### D. VMAS transport / reverse_transport：物理协调强，低层控制负担较大

- [官方模拟器](https://github.com/proroklab/VectorizedMultiAgentSimulator)
- [transport源码](https://github.com/proroklab/VectorizedMultiAgentSimulator/blob/main/vmas/scenarios/transport.py)
- [reverse_transport源码](https://github.com/proroklab/VectorizedMultiAgentSimulator/blob/main/vmas/scenarios/reverse_transport.py)
- [现成测试](https://github.com/proroklab/VectorizedMultiAgentSimulator/blob/main/tests/test_scenarios/test_transport.py)

PyTorch二维物理，可CPU运行，transport已有可移动重物、多个Agent及启发式控制接口。比3D机器人轻，但包裹质量大不严格证明单Agent永远无法完成，需要验证时域与参数；原生也未确认有货物损坏。连续作用力不是1.5B最合适的直接输出，额外宏控制器可能成为最大工作量。暂列备选，不为它先训练策略。

## 4. 很相关但当前不建议作为首个核心实验

| 资源 | 已核实的可复用部分 | 不优先的原因 |
| --- | --- | --- |
| [PARTNR](https://github.com/facebookresearch/partnr-planner) | Habitat协作任务、LLM规划与技能接口、评测、轨迹、val_mini与oracle技能工具 | 3D模拟/资产部署重；部分技能沙盒只支持顺序控制，不直接等于并发协作评测；并非每任务都严格需要双Agent |
| [CoELA：TDW-MAT / C-WAH](https://github.com/UMass-Embodied-AGI/CoELA) | TDW-MAT 24个测试episode、运输与容器任务；C-WAH五类家务、消息与LLM agent | TDW/Unity/资产和感知栈；搬运很多任务可能可分解为独立运输，不能因多Agent就认定强互依 |
| [CHAIC](https://github.com/UMass-Embodied-AGI/CHAIC) | 身体能力限制、八类长程任务、紧急事件、LLM/行为建模与脚本 | 能力互补很适合，但官方安装涉及TDW、Py3.9、Torch CUDA、检测模型和资产，当前CPU机器风险高 |
| [HAZARD](https://github.com/UMass-Embodied-AGI/HAZARD) | 火灾/洪水等动态灾害、原生物品价值损失、规则/MCTS/LLM基线 | 危险后果匹配，但本轮未验证原生双Agent相互承诺任务；不可拿单Agent灾害规划充当多Agent强协调现成基准 |
| [RWARE](https://github.com/semitable/robotic-warehouse) | 仓储、多机器人、共享通道、Gymnasium、随机任务队列 | 单货架通常可由单机器人搬运；碰撞由程序解决，不是原生危险品报废；强互补协作不自动成立 |
| [PettingZoo](https://github.com/Farama-Foundation/PettingZoo) | 多Agent接口和许多任务，例如合作物理pistonball | 是环境集合，不是单个未来承诺基准；任务动力学与LLM接口仍需另选，不能只装接口就算完成适配 |
| [Melting Pot](https://github.com/google-deepmind/meltingpot) | 社会协作任务集合与评估资源 | 依赖栈和任务选择工作量较大；不优先于直接有LLM接口的Collab任务 |

代码仓库许可证与场景/资产/权重许可不是一回事。后续选定才逐项存档核查，不把某个仓库MIT推广到所有关联数据。

## 5. 最终建议：不要同时部署两个主平台

**按当前“快成文、少构造、LLM元认知”目标：优先核查Collab-Overcooked的一条原生角色交接配方；若必须有死锁级失败后果，则把Flatland升为主场景，Collab作为备选，而非同时开工。**

不建议继续自造危险品运输模拟器。现成资源没有同时满足全部愿望的零成本选项：强互补且有LLM接口的Collab缺少已核实灾难后果；Flatland有系统级失败但需LLM调度适配；3D灾害/合作平台则太重。选择时应明确取舍，而非虚构一个完美benchmark。

## 6. 选定后的核心实验边界

固定一个窗口内的计划与承诺，不学习所有时域。选择现成任务中具有真实后续依赖的配置，并保留低依赖/可替代配置作为反例。用环境原生成功、未完成任务、超时、死锁或错误动作指标，而非单纯“承诺保护次数”。

必须比较：独立重规划、固定期限/预约、规则依赖保护、仅当前依赖、当前+未来依赖。主要问题是后两者及最强简单基线的实际结果差异，不能只证明“带协议胜过完全不通信”。

至少覆盖：应该保持、应该修订、需求未发生或可替代三类情况；优先选现成任务/随机故障实现，不立即加自定义损坏。保留同信息、同模型、同执行器和成本统计。Qwen2.5-1.5B若无法稳定使用原生动作，先缩短观测与约束格式，不以规则替答再声称模型成功。

接下来具体动作是检查选定仓库的一条任务、原生能力限制和自动判定是否可运行，再冻结配置；不是下载全部资源、训练低层策略或继续改大框架。所有场景文件和任务配置仍统一归入expr/datasets并记录来源commit，第三方源码按依赖单独管理。
