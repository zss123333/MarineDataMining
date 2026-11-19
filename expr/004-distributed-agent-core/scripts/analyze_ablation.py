import argparse
import json
from collections import defaultdict
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", type=Path)
    args = parser.parse_args()
    rows = json.loads(args.batch.read_text(encoding="utf-8"))
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["args"]["method"]].append(row)
    held_out = all(row["args"]["dataset_version"] == "v3-holdout" for row in rows)
    description = "本批为预先固定的新种子保留实例。" if held_out else "本批全部为已接触的开发实例，不是保留测试。"
    lines = ["# 配对方法对照", "", description + "规则控制，不含LLM推理。", "",
             "| 方法 | 到达/总数 | 惩罚完成时间 | 消息数 | 消息字节 | 组合检查 | 墙钟秒 | 实际修复 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for method, runs in grouped.items():
        totals = {key: sum(row[key] for row in runs) for key in
                  ["arrived", "agents", "capped_completion_steps", "messages", "message_bytes",
                   "combinations_checked", "wall_seconds", "repair_installs"]}
        lines.append(f"| {method} | {totals['arrived']}/{totals['agents']} | "
                     f"{totals['capped_completion_steps']} | {totals['messages']} | "
                     f"{totals['message_bytes']} | {totals['combinations_checked']} | "
                     f"{totals['wall_seconds']:.3f} | {totals['repair_installs']} |")
    lines += ["", "## 逐实例配对", "",
              "惩罚完成时间越低越好；差值为完整方法减对照。不能脱离到达数量单看时间。", "",
              "| 场景 | 对照 | 完整方法到达差 | 完整方法时间差 | 同一数据文件 |",
              "| --- | --- | --- | --- | --- |"]
    complete = {row["args"]["scenario"]: row for row in grouped["menus"]}
    for method, runs in grouped.items():
        if method == "menus":
            continue
        for row in runs:
            full = complete[row["args"]["scenario"]]
            lines.append(f"| {row['args']['scenario']} | {method} | "
                         f"{full['arrived']-row['arrived']:+d} | "
                         f"{full['capped_completion_steps']-row['capped_completion_steps']:+d} | "
                         f"{full['scenario_sha256'] == row['scenario_sha256']} |")
    lines += ["", "## 解释限制", "",
              "- 样本少，且每场景仅一次运行，不能支持稳定收益或显著性结论。",
              "- 独立方法每步自己重规划；协调方法轮换发起，决策机会不完全相同。",
              "- 同一场景文件不保证执行相关的原生故障在各方法中具有同样的触发时刻。",
              "- 修复成本是计划预测片段改变的代理计数，不是精确的物理恢复时间。独立方法未按同一定义记录修复。",
              "- 未来影响主要由轨迹占用及交换冲突检查体现，尚无独立任务依赖消融。",
              "- 各方法模型token均为零；本批不能回答同Qwen预算下的增益。",
              "- 墙钟是单次测量，受机器负载影响，不据此推断稳定速度比。", "",
              f"原始批次：`runs/{args.batch.name}`。全部失败均保留在该文件及对应运行目录。"]
    target = args.batch.with_suffix(".md")
    target.write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
