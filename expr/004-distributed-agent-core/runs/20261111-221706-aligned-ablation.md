# 配对方法对照

本批为预先固定的新种子保留实例。规则控制，不含LLM推理。

| 方法 | 到达/总数 | 惩罚完成时间 | 消息数 | 消息字节 | 组合检查 | 墙钟秒 | 实际修复 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| independent | 10/28 | 4634 | 0 | 0 | 0 | 0.824 | 0 |
| single | 15/28 | 4333 | 12938 | 84728639 | 2119 | 44.000 | 28 |
| menus_no_repair | 15/28 | 4371 | 12681 | 107478013 | 97880 | 67.116 | 58 |
| menus | 15/28 | 4371 | 12681 | 107477763 | 97301 | 67.898 | 58 |
| official_dla | 28/28 | 3328 | 0 | 0 | 0 | 0.474 | 0 |

## 逐实例配对

惩罚完成时间越低越好；差值为完整方法减对照。不能脱离到达数量单看时间。

| 场景 | 对照 | 完整方法到达差 | 完整方法时间差 | 同一数据文件 |
| --- | --- | --- | --- | --- |
| Test_00_Level_0.pkl | independent | +4 | -158 | True |
| Test_00_Level_1.pkl | independent | +1 | -64 | True |
| Test_00_Level_2.pkl | independent | +0 | +0 | True |
| Test_00_Level_3.pkl | independent | +0 | -41 | True |
| Test_00_Level_0.pkl | single | +0 | +38 | True |
| Test_00_Level_1.pkl | single | +0 | +1 | True |
| Test_00_Level_2.pkl | single | +0 | +0 | True |
| Test_00_Level_3.pkl | single | +0 | -1 | True |
| Test_00_Level_0.pkl | menus_no_repair | +0 | +0 | True |
| Test_00_Level_1.pkl | menus_no_repair | +0 | +0 | True |
| Test_00_Level_2.pkl | menus_no_repair | +0 | +0 | True |
| Test_00_Level_3.pkl | menus_no_repair | +0 | +0 | True |
| Test_00_Level_0.pkl | official_dla | +0 | +13 | True |
| Test_00_Level_1.pkl | official_dla | -2 | +122 | True |
| Test_00_Level_2.pkl | official_dla | -6 | +468 | True |
| Test_00_Level_3.pkl | official_dla | -5 | +440 | True |

## 解释限制

- 样本少，且每场景仅一次运行，不能支持稳定收益或显著性结论。
- 独立方法每步自己重规划；协调方法轮换发起，决策机会不完全相同。
- 同一场景文件不保证执行相关的原生故障在各方法中具有同样的触发时刻。
- 修复成本是计划预测片段改变的代理计数，不是精确的物理恢复时间。独立方法未按同一定义记录修复。
- 未来影响主要由轨迹占用及交换冲突检查体现，尚无独立任务依赖消融。
- 各方法模型token均为零；本批不能回答同Qwen预算下的增益。
- 墙钟是单次测量，受机器负载影响，不据此推断稳定速度比。

原始批次：`runs/20261111-221706-aligned-ablation.json`。全部失败均保留在该文件及对应运行目录。
