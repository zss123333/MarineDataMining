# 实验001：Overcooked环境与执行链路冒烟测试

## 1. 研究问题与边界

验证真实开源Overcooked底层MDP能否在无图形界面、无LLM和无训练的条件下运行，并让最小宏动作执行器完成取洋葱、投料、开火、取盘、装汤和交付，同时保存可逐步精确重放的轨迹。

**这不是DACM有效性实验，不是双LLM协作比较。** 脚本只控制厨师0，厨师1静止；只验证环境与I/O，不声称规则方法能解决协作，也不提供统计显著性结论。下一实验才接入承诺与队友未来依赖。

## 2. 实验设计

- 环境：上游Overcooked源码提交 `739950a079cdaed5a44fcc662efc40244c205d06`，直接使用 `OvercookedGridworld`，不替换成自建仿真。
- 输入：[统一数据版本](../datasets/overcooked-smoke/v1/README.md)，一张 `cramped_room`，固定初态。
- 条件：`idle` 两厨师都等待；`scripted_delivery` 厨师0规则做汤、厨师1等待。
- 长度：每episode 200个环境步，两方法各运行种子0、1、2，共6个episode。无扰动、无随机初态，因此不同种子是重复性检查，不是独立样本。
- 执行：在位置与朝向联合状态上BFS，找能面向目标设备的位置；将队友位置当障碍，无法到达时报错，不默默无限等待。交互使用真实MDP，投料后显式启动烹饪。
- 指标：交付次数、环境原生稀疏奖励、执行步数、双人位置均未改变的步数、实际经过的宏动作。静止不等于死锁，尤其烹饪等待不能误判失败。
- 成本：零LLM调用、零token。墙钟为本地执行耗时，不与未来API推理混比。

## 3. 验收与失败条件

1. 所有位置始终是合法地面且两厨师不重叠。
2. idle稀疏奖励为0。
3. scripted_delivery在200步内至少交付一碗汤。
4. 保存完整前状态、联合动作、后状态、奖励和事件，每条轨迹从初态精确重放一致。
5. 数据SHA-256和上游安装来源通过核查；不符即失败。

测试未通过时保存 `logs/error.txt` 和失败运行状态，不修改或删除失败记录。没有通过这些验收，就不开始LLM层。

## 4. 安装与执行

以下命令以PowerShell、当前目录为本实验目录；脚本内部用文件位置定位数据，因此也可从其他工作目录传绝对脚本路径执行。

```powershell
python -m venv --system-site-packages .venv
.\.venv\Scripts\python.exe -m pip install --no-deps --ignore-requires-python -r requirements.txt
.\.venv\Scripts\python.exe scripts/prepare_dataset.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe src/smoke.py --config configs/smoke.json
```

本机基于Python3.13.5、已有NumPy2.1.3运行。上游实际构建元数据pyproject.toml声明Python >=3.10且<3.11、NumPy<2，包版本为2.0.0（旧setup.py版本不同）；全量安装还包含图形/Web依赖。因此本实验使用 `--no-deps --ignore-requires-python` 在隔离环境验证底层MDP，**不声称满足上游完整应用依赖约束**。本机测试通过不代表完整训练、渲染、Gym包装器或Web demo兼容。`--system-site-packages`会继承本机包，核心版本见requirements及运行清单。正式后续实验宜另建Python3.10、NumPy1.x环境再验收，不能直接推广本次兼容性结论。

依赖安装属于环境准备，非实验输入；不把完整第三方仓库复制进数据集。API密钥不需要配置。

## 5. 文件与复现

- `configs/smoke.json`：固定实验协议。
- `scripts/prepare_dataset.py`：下载固定提交原始地图与许可，生成输入清单，已有版本只做验证。
- `src/smoke.py`：输入验证、朝向感知BFS、脚本宏动作、运行记录及重放。
- `tests/test_smoke.py`：空动作、完整交付、不可达目标、数据路径边界测试。
- `runs/<run_id>/`：生效配置、来源/环境清单、JSONL轨迹、指标、报告和错误日志。

运行清单记录本实验目录未提交修改，运行目录的 `source_snapshot/` 保留执行时核心源码和依赖清单，不能只凭仓库HEAD复现。底层全局Recipe配置意味着暂不支持同进程并行初始化不同配方环境。

## 6. 结果状态

2026-11-09本机验收完成：4项unittest通过；两条件各3次、每次200步，累计1200步重放全部一致。脚本条件每局交付4碗、原生稀疏奖励80；idle每局交付0、奖励0。三个种子产生相同结果，符合确定性协议，不是统计上的三次独立证据。

主要结果：[运行报告](runs/20261109-170142-smoke-d72b83/report.md)、[机器验收项](runs/20261109-170142-smoke-d72b83/metrics/checks.json)、[逐episode指标](runs/20261109-170142-smoke-d72b83/metrics/episodes.json)、[环境及来源记录](runs/20261109-170142-smoke-d72b83/run_manifest.json)。早期运行也保留在runs下，主报告使用包含源码快照的这一轮。

下一步可以进入最小双Agent承诺预实验，但本次结果不支持“元认知提高协作效率”或“节省token”的结论；正式实验前还应在上游支持的Python3.10环境复核。
