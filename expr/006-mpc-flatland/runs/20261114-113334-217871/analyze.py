import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", type=Path)
    args = parser.parse_args()
    rows = json.loads((args.batch / "results.json").read_text(encoding="utf-8"))
    lines = ["# 在线协商对照与过程验收", "", f"原始批次：`{args.batch.name}`；已完成{len(rows)}/45局。", "",
             "固定三个开发场景、无/低/高扰动及五方法。所有方法1000步，同路线、初始安排和事件表；规则Agent，无LLM。以下是描述性开发结果，不是独立保留或显著性结论。", "",
             "| 场景 | 扰动 | 方法 | 到达 | 惩罚完成步数 | 消息字节 | 检查 | 替代提交 | 反馈提案 | 秒 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in rows:
        lines.append(f"| {row['case']['scenario']} | {row['case']['tier']} | {row['method']} | {row['arrived']}/7 | {row['completion_penalty']} | {row['message_bytes']} | {row['checks']} | {row['committed_alternatives']} | {row['feedback_proposals']} | {row['seconds']:.2f} |")
    lines += ["", "## 完整反馈法的配对比较", "", "差值为feedback减对照；负的惩罚步数差仅在到达数不降低时才能解释为更好。"]
    comparisons = []
    for full in [row for row in rows if row['method'] == 'feedback']:
        for other in rows:
            if other['case'] == full['case'] and other['method'] != 'feedback':
                comparisons.append({"scenario": full['case']['scenario'], "tier": full['case']['tier'],
                                    "baseline": other['method'], "arrival_delta": full['arrived']-other['arrived'],
                                    "penalty_delta": full['completion_penalty']-other['completion_penalty'],
                                    "byte_delta": full['message_bytes']-other['message_bytes']})
    for row in comparisons:
        lines.append(f"- {row['scenario']} / {row['tier']} 对{row['baseline']}：到达差{row['arrival_delta']:+}，惩罚步数差{row['penalty_delta']:+}，字节差{row['byte_delta']:+}。")
    lines += ["", "## 过程审计", ""]
    for method in ['fixed', 'periodic', 'single', 'menus', 'feedback']:
        group = [row for row in rows if row['method'] == method]
        if group:
            lines.append(f"- {method}：{len(group)}局，替代提交{sum(row['committed_alternatives'] for row in group)}，反馈提案{sum(row['feedback_proposals'] for row in group)}，菜单穷尽{sum(row['menu_exhausted'] for row in group)}，预算耗尽{sum(row['budget_exhausted'] for row in group)}，修复安装{sum(row['repair_installs'] for row in group)}，到期执行拦截{sum(row['execution_blocks'] for row in group)}。")
    lines += [f"- 全部已完成运行：占用审计违规{sum(row['observed_occupancy_violations'] for row in rows)}，原生故障计数样本{sum(row['native_fault_samples'] for row in rows)}。", "", "## 解释边界", "", "替代提交非零说明队友替代方案实际采用；反馈提案非零只说明重协商发生，不代表它成功或有收益。大量菜单/预算耗尽、执行拦截可能是失败而非复杂协作成功。", "", "现有事件法仍按8步到期触发，不能把与周期法的差异归因于精确无影响不通信。反馈法扩大菜单且总预算更多，不是同预算消融；反馈内容目前主要是重试与覆盖扩展，不是完整冲突约束求解。初始串行基线保守，优于它不等于优于成熟调度器。", "", "未来扰动表被适配器用于边界选择，属于已知外部事件设置，不能声称预测未知故障。暂无严格任务恢复正常时间、单次求解分位数及无影响通信诊断，不能用安装次数替代恢复成功。"]
    (args.batch / 'comparison.json').write_text(json.dumps(comparisons, indent=2), encoding='utf-8')
    (args.batch.parent.parent / '在线对照验收.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(len(rows), 'runs analyzed')


if __name__ == '__main__':
    main()
