# 外部 baseline 适配核查与补实验建议

核查日期：2026-11-17。本次只做文献、作者实现、接口及运行条件核查，不修改报告结论，不新增性能对照批次。除官方DLA的一局冒烟测试外，其他作者实现均未在本机跑通；公开代码存在不等于本机可运行，更不等于已复现论文。

## 1. 任务约束与判断标准

当前整体效果实验使用 Flatland 4.2.6、Python 3.11.15、持久化场景及七列车配置。轨道移动受位置、方向、合法转移、速度与格内运动状态约束；列车存在场外等待及到达后退出等语义。不能把轨道非零格子直接转成普通四邻接网格，再声称同任务公平比较。

第二组包含局部计划修复、单容量资源预约、动态窗口失效及连锁扩组；第三组包含固定路线许可和真实模型资源预约。空间MAPF算法不自动解决版本化协议或语义响应问题。外部方法是否适合，必须分别核对任务模型、输入信息、执行器、目标与预算，不能只看名称中有“多智能体”“修复”或“滚动”。

## 2. 核查结论一览

| 候选 | 论文或出处 | 实现和适配证据 | 当前决策 |
| --- | --- | --- | --- |
| 官方 DeadLockAvoidancePolicy（DLA） | Flatland Association 官方工程基线，不是某篇已核实论文算法 | 已安装、已接入且有历史配对结果；本次单局再验证成功 | 直接保留为外部工程参照，不称论文SOTA |
| Flatland 2020 冠军铁路规划与重规划方案 | Li等，Scalable Rail Planning and Replanning: Winning the 2020 Flatland Challenge，SoCS 2021 | 作者仓库提供铁路专用求解与执行代码，但依赖Flatland 2.x、Python 3.6及Boost.Python | 首选论文型外部baseline；先做移植可行性验证，不直接批跑 |
| SADG滚动重排序 | Berndt等，Receding Horizon Re-ordering of Multi-Agent Execution Schedules，IEEE TRO 2024 | 作者提供ROS2、MAPF编译与MILP反馈实现；当前许可实验不具备其输入图与换序执行器 | 理论机制接近，但不是当前实验可直接接入的低成本对照 |
| RHCR | Li等，Lifelong Multi-Agent Path Finding in Large-Scale Warehouses，AAAI 2021 | 作者C++实现提供WHCA、ECBS、PBS窗口求解；任务是不断接收新目标的仓储MAPF | 不作为当前有限铁路任务的首个接入项 |
| MAPF-LNS2 | Li等，MAPF-LNS2: Fast Repairing for Multi-Agent Path Finding via Large Neighborhood Search，AAAI 2022 | 作者代码完整，支持MAPF标准地图/场景；需CMake、Boost、Eigen | 标准MAPF路径修复不等于我们的在线承诺修复；优先铁路专用实现 |
| 分布式计划修复论文中的MA-Plan方法 | Komenda等，arXiv:1202.2773 | 现有笔记明确缺少固定原代码、完整实例及种子；任务是符号规划域 | 本轮不能确认为可运行对照，不把“自行仿写”称作者复现 |

这些方法是有出处的候选，不据此认定它们是2026年的最新SOTA。本轮也不是对全部最新论文的穷尽检索。

## 3. 已可运行：官方DLA

- 官方仓库：https://github.com/flatland-association/flatland-baselines
- README明确将其称为 shortest path deadlock avoidance，提供RailEnvPolicy接口。
- 本地安装元数据的实际来源为 `https://github.com/flatland-association/flatland-baselines/archive/2c7436b47be92dc80634c4ded8f4fc16fa8b60b1.zip`，不是本次上游HEAD `c1733cbae8f9abc6c1e73fa16ec9119872abd292`。不能把最新代码描述套在旧实验上。
- 本次使用现有003隔离环境，加载 `flatland-core/v1/Test_00_Level_0.pkl`，逐步调用原策略 `act_many` 及原生 `env.step`；191步，7/7到达，环境正常终止。仅证明旧接口在本机仍可执行，不新增性能优越性结论。
- 现有完整记录：`../expr/004-distributed-agent-core/官方强基线十场景对照.md`。十个开发实例DLA为69/70、惩罚步数8993；menus为63/70、9182。目前我们没有在这项外部对照上获胜。
- DLA读取全环境状态，不能用其零显式协议消息主张我们的分布式通信效率更优。完成效果可并列，信息与架构差异必须明示。

## 4. 首选论文baseline：铁路专用规划与重规划

论文：https://doi.org/10.1609/socs.v12i1.18576 。出版方页面确认标题、作者及2021年发表信息：https://ojs.aaai.org/index.php/SOCS/article/view/18576 。

作者仓库：https://github.com/Jiaoyang-Li/Flatland 。本次HEAD：`6667f181d6f39f8c1d63f38799d7fce21ab4e87b`。

具体核对：

- 根README说明为Flatland 2020的 `An_old_driver` 团队方案，包含 `CBS-corridor` 和 `Flatland2020`。
- `CBS-corridor/README.md` 提供 `PythonCBS`、GPP、LNS等模式，显式考虑列车方向、不同速度、进入/离开地图、走廊冲突及截止时间，比通用网格求解器贴合当前任务。
- `Flatland2020/run.py` 使用 `MCP_Controller` 和 `PythonCBS`，但导入旧版 `RailAgentStatus`、`sparse_schedule_generator` 等接口；根README提到Flatland 2.1.10/2.2.x。
- 编译文档要求Python 3.6、Boost 1.61及Boost.Python；Windows需手工配置依赖。不能在当前3.11环境中直接导入旧编译扩展。
- README列出的GPP/LNS是可配置求解模式，不能未经核对就把任意默认配置称为完整冠军方案。需要进一步核对完整规划、MCP执行与重规划配置，并审阅许可后再复制或修改上游代码。

建议的接入验收顺序：

1. 固定作者commit，隔离工具链；不降级现有实验环境。
2. 先验证原仓库示例可编译运行，再设计4.2.6适配层。原示例失败与适配失败分别记录。
3. 对单车、对向走廊、异速跟驰、同起点场外等待、到达移除做微场景一致性检查。
4. 在同一持久化七车实例中验证合法动作、到达统计、截止及故障语义。不可读取未来故障真值。
5. 完成一局后再冻结方法、运行预算与种子，决定是否批量对比。只调用GPP子模式时，报告应写作者代码的GPP配置，而不是完整冠军复现。

这是一项“论文来源明确、任务贴近，但尚未完成本机适配”的候选，不是当前已跑通的新baseline。

## 5. 为什么其余作者代码暂不直接上实验

### SADG

- 作者仓库：https://github.com/alexberndt/sadg-controller ，HEAD `c2626d996121a9d6c128844a167b917db24418ac`。
- 论文：https://doi.org/10.1109/TRO.2023.3344051 。
- README要求ROS2 Galactic/Ubuntu20.04或Humble/Ubuntu22.04，推荐Docker；第三方依赖含libMultiRobotPlanning。requirements包含python-mip，不应在未核实前声称只能使用商业求解器。
- 本机没有可用docker命令或已安装WSL发行版，CMake也未在PATH发现；本轮未安装系统依赖。
- SADG需要初始无冲突计划、空间排他动作依赖图、事件进度和可切换次序。我们当前固定路线许可按整条路线保守放行，不具备相同粒度。改成同一执行器后才可对比固定ADG与滚动SADG；不能将我们当前按编号等待直接改名ADG。
- 仓库AGPL-3.0；后续整合需遵守许可。

### RHCR与MAPF-LNS2

- RHCR：https://github.com/Jiaoyang-Li/RHCR ，HEAD `d009a3bd716419b0d6c04aead9dbca1720c012da`。README提供周期h、窗口w及PBS/ECBS/WHCA求解器，针对lifelong仓储任务；依赖CMake、Boost，许可为USC Research License。
- MAPF-LNS2：https://github.com/Jiaoyang-Li/MAPF-LNS2 ，HEAD `1369823985a15944f9a339226d521f61605a6d17`。README提供标准.map/.scen输入和可执行命令，依赖CMake、Boost、Eigen，许可为USC Research License。
- 两者都有论文与作者实现，不是“找不到baseline”。但直接用于当前铁路必须核对方向、轨道转移、速度、格内进度与到达占用，且RHCR要适配有限目标任务。完成这些工作前，不能标为同环境已复现。
- MAPF-LNS2标题中的repairing主要指搜索中修复有冲突的路径集合，不自动等于执行时对承诺撤销、版本及第三方影响的修复。

## 6. 决定是否补实验

推荐先后顺序：

1. 第一组：保留并明确展示已有DLA外部结果；以SoCS 2021铁路冠军作者实现为首选移植验证对象。现阶段不需要再发明一个“优先级规划”来冒充外部实现。
2. 第二组：保留局部补丁及连锁过程验证；全组重新协调明确为内部控制变量对照。SADG只有在统一动作依赖执行器后才值得做外部性能对比，当前资源预约任务没有本轮已确认可直接替换的论文算法。
3. 第三组：周期与每步询问仍是合理触发消融，但不是论文强基线。若要用SADG/RHCR比较执行质量，先统一任务、信息与执行器；非LLM规划器的零token不能直接解释为LLM协调机制的优越或劣势。

下一阶段建议只做铁路论文baseline的适配小验证，不立刻启动新的大批次。不把作者示例成功、4.2.6移植成功、同任务公平对照和论文复现四个层次混为一谈。
