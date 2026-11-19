import json
from pathlib import Path

root = Path(__file__).resolve().parent
results = json.loads((root / "runs/results.json").read_text(encoding="utf-8"))
cases = json.loads((root.parent / "datasets/high-conflict-v1/manifest.json").read_text(encoding="utf-8"))
lines = ["# 高冲突实验结果", "", f"当前落盘{len(results)}/24局。仅24局全部落盘才视为完成批次。", "",
         "| Agent数 | 种子 | 方法 | 完成工序 | 冲突参与步 | 消息 | 字节 | 组合检查 | 反馈提案 | 秒 |",
         "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
for result in results:
    lines.append(f"| {result['agents']} | {result['seed']} | {result['method']} | {result['completed']}/{result['total']} | {result['conflict_steps']} | {result['messages']} | {result['bytes']} | {result['checks']} | {result['feedback_proposals']} | {result['seconds']:.3f} |")
lines += ["", "## 可行性检查", "", "依次串行执行所有工序可以构造无冲突安排，下面是该安排所需步数，不是本方法成绩。超过320步不保证本实验上限内可全部完成，但首项可以完成。"]
for case in cases:
    serial = sum(duration for jobs in case['jobs'] for resource, duration in jobs)
    lines.append(f"- {case['agents']}名Agent，种子{case['seed']}：{serial}步。")
lines += ["", "## 解释", "", "三项响应集中在相邻时刻，没有覆盖足够的错峰安排，也没有允许部分成员暂不预约的响应。找不到全体安排时无人推进。反馈使用已有占用作约束，各方可能一起选择同样的后移时间，未必打破对称性。", "", "增加反馈轮次只增加检查，未保证出现相容选项。结果不支持当前实现优越性，高冲突放大了候选覆盖问题。", "", "本任务是自建机制压力测试，不是外部benchmark，没有LLM调用。后续应增加所有方法共享的等待/暂不预约选项、扩展时间覆盖并加入公平破对称机制，再冻结新版对照，不能覆盖本轮失败。"]
(root / "结果分析.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
print(len(results), "runs analyzed")
