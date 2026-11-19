import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    rows = json.loads(args.batch.read_text(encoding="utf-8"))
    full = {row["args"]["scenario"]: row for row in rows if row["args"]["method"] == "menus"}
    lines = ["# 保留测试、成本与过程审计", "", "固定四个新种子，不因结果重新挑选。小样本只作探索性比较。", "",
             "## 配对差值与不确定性", "",
             "差值为完整方法减对照；到达数越高越好，惩罚完成时间越低越好。区间按场景配对重采样10000次，不把同场景7辆车当7个独立样本。", "",
             "| 对照 | 到达差均值 | 时间差均值 | 时间差探索性95%区间 |",
             "| --- | --- | --- | --- |"]
    rng = np.random.default_rng(20261111)
    for method in ["independent", "single", "menus_no_repair", "official_dla"]:
        controls = [row for row in rows if row["args"]["method"] == method]
        differences = np.array([full[row["args"]["scenario"]]["capped_completion_steps"] - row["capped_completion_steps"] for row in controls])
        arrivals = [full[row["args"]["scenario"]]["arrived"] - row["arrived"] for row in controls]
        samples = differences[rng.integers(0, len(differences), size=(10000, len(differences)))].mean(axis=1)
        lower, upper = np.quantile(samples, [.025, .975])
        lines.append(f"| {method} | {np.mean(arrivals):.2f} | {differences.mean():.2f} | [{lower:.2f}, {upper:.2f}] |")
    lines += ["", "## 可追踪过程", "",
              "恢复等待定义为撤销承诺到下一次本地计划安装的步数，不代表恢复正常行驶。未恢复单独计数。短期反复修复定义为8步内再次发生修复安装，不等于这些修改没有必要。", ""]
    for scenario, row in full.items():
        directory = root / row["run"]
        traces = json.loads((directory / "negotiation.json").read_text(encoding="utf-8"))
        messages = json.loads((directory / "messages.json").read_text(encoding="utf-8"))
        phases = Counter(event.get("decision", event.get("event", "other")) for events in traces.values() for event in events)
        proposals = {message["proposal"]: message["payload"] for message in messages if message["kind"] == "propose"}
        scopes = [len(proposal["participants"]) for proposal in proposals.values()]
        pending = {}
        recovery = []
        prepared = {}
        replies = {}
        last_repair = {}
        repeated = 0
        for message in messages:
            key = message["proposal"]
            member = message["receiver"]
            stamp = proposals[key]["round"] if key in proposals else None
            if message["kind"] == "revoke":
                pending.setdefault(message["sender"], int(key.split(":")[-1]))
            elif message["kind"] == "prepare":
                prepared[(key, member)] = message["payload"]
            elif message["kind"] == "respond":
                replies[(key, message["sender"])] = message["payload"]
            elif message["kind"] == "commit" and stamp is not None:
                if member in pending:
                    recovery.append(stamp-pending.pop(member))
                selection = prepared.get((key, member))
                if selection and (key, member) in replies:
                    options = replies[(key, member)][selection["candidate"]]["options"]
                    repair = options[selection["option"]]["public"].get("repair_cost", 0)
                    if repair:
                        repeated += member in last_repair and stamp-last_repair[member] <= 8
                        last_repair[member] = stamp
        lines += [f"### {scenario}", "",
                  f"- 到达{row['arrived']}/{row['agents']}，撤销{row['revocations']}，修复安装{row['repair_installs']}，采用替代搭配{row['committed_alternative_combinations']}。",
                  f"- 提案数量{len(proposals)}；参与人数最小/最大为{min(scopes, default=0)}/{max(scopes, default=0)}。",
                  f"- 撤销后再安装等待步数：{recovery}；未找到后续安装的成员数{len(pending)}。这是恢复代理，不证明重新正常行驶。",
                  f"- 8步内再次修复安装{repeated}次；不能仅凭频繁修改就认定没有必要。",
                  f"- 事件计数（同提案在成员间可能重复）：`{dict(phases)}`。",
                  f"- 原始轨迹、消息和协商：`{row['run']}`。", ""]
    source = root.parent.parent / "核心源码/agent.py"
    lines += ["## 解释边界", "",
              "未来路线的资源交集用于保守地选择参与者，即使当前预测片段没有重叠也可纳入；但它不提供任意任务的语义依赖证明。",
              "官方DLA读取完整环境，属于工程参考，不是同信息分布式SOTA。独立方法的决策机会和协调方法也不同。",
              "本批若无稳定收益，应接受该结论，不继续用同一保留集调参。", "",
              f"核心SHA256：`{hashlib.sha256(source.read_bytes()).hexdigest()}`。"]
    target = args.batch.with_name(args.batch.stem + "-audit.md")
    target.write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
