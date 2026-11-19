# 扩展开发集四方法对照

本批全部为已接触的开发实例，不是保留测试。规则控制，不含LLM推理。

| 方法 | 到达/总数 | 惩罚完成时间 | 消息数 | 消息字节 | 组合检查 | 墙钟秒 | 实际修复 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| independent | 33/70 | 11198 | 0 | 0 | 0 | 2.984 | 0 |
| single | 49/70 | 9954 | 19143 | 116671092 | 4358 | 96.115 | 42 |
| menus_no_repair | 63/70 | 9200 | 13717 | 91650580 | 83389 | 102.645 | 98 |
| menus | 63/70 | 9182 | 13647 | 91410394 | 79431 | 108.017 | 96 |

## 逐实例配对

惩罚完成时间越低越好；差值为完整方法减对照。不能脱离到达数量单看时间。

| 场景 | 对照 | 完整方法到达差 | 完整方法时间差 | 同一数据文件 |
| --- | --- | --- | --- | --- |
| Test_00_Level_0.pkl | independent | +4 | -408 | True |
| Test_00_Level_1.pkl | independent | +0 | +72 | True |
| Test_00_Level_2.pkl | independent | +4 | -251 | True |
| Test_00_Level_3.pkl | independent | +5 | -341 | True |
| Test_00_Level_4.pkl | independent | +0 | +48 | True |
| Test_00_Level_5.pkl | independent | +5 | -508 | True |
| Test_00_Level_6.pkl | independent | +4 | -195 | True |
| Test_00_Level_7.pkl | independent | +5 | -364 | True |
| Test_00_Level_8.pkl | independent | +0 | +0 | True |
| Test_00_Level_9.pkl | independent | +3 | -69 | True |
| Test_00_Level_0.pkl | single | +1 | -103 | True |
| Test_00_Level_1.pkl | single | +0 | +2 | True |
| Test_00_Level_2.pkl | single | +0 | -35 | True |
| Test_00_Level_3.pkl | single | +6 | -485 | True |
| Test_00_Level_4.pkl | single | +1 | -65 | True |
| Test_00_Level_5.pkl | single | +0 | -2 | True |
| Test_00_Level_6.pkl | single | +3 | -157 | True |
| Test_00_Level_7.pkl | single | +0 | +104 | True |
| Test_00_Level_8.pkl | single | +0 | +0 | True |
| Test_00_Level_9.pkl | single | +3 | -31 | True |
| Test_00_Level_0.pkl | menus_no_repair | +0 | +0 | True |
| Test_00_Level_1.pkl | menus_no_repair | +0 | +0 | True |
| Test_00_Level_2.pkl | menus_no_repair | +0 | -18 | True |
| Test_00_Level_3.pkl | menus_no_repair | +0 | +0 | True |
| Test_00_Level_4.pkl | menus_no_repair | +0 | +0 | True |
| Test_00_Level_5.pkl | menus_no_repair | +0 | +0 | True |
| Test_00_Level_6.pkl | menus_no_repair | +0 | +0 | True |
| Test_00_Level_7.pkl | menus_no_repair | +0 | +0 | True |
| Test_00_Level_8.pkl | menus_no_repair | +0 | +0 | True |
| Test_00_Level_9.pkl | menus_no_repair | +0 | +0 | True |

## 解释限制

- 这十个实例已用于开发，不能支持未见场景上的稳定收益或显著性结论。
- 独立方法每步自己重规划；协调方法轮换发起，决策机会不完全相同。
- 同一场景文件不保证执行相关的原生故障在各方法中具有同样的触发时刻。
- 修复成本是计划预测片段改变的代理计数，不是精确的物理恢复时间。独立方法未按同一定义记录修复。
- 未来影响主要由轨迹占用及交换冲突检查体现，尚无独立任务依赖消融。
- 各方法模型token均为零；本批不能回答同Qwen预算下的增益。
- 墙钟是单次测量，受机器负载影响，不据此推断稳定速度比。

原始批次：`runs/20261111-213049-aligned-ablation.json`。全部失败均保留在该文件及对应运行目录。
