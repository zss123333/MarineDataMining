import ast
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from flatland.env_generation.env_generator import env_generator
from flatland.envs.persistence import RailEnvPersister


def main():
    root = Path(__file__).resolve().parents[1]
    original = root.parent / "datasets" / "flatland-core" / "v1"
    dataset = root.parent / "datasets" / "flatland-core" / "v2-audit"
    dataset.mkdir(parents=True, exist_ok=True)
    upstream = json.loads((original / "manifest.json").read_text(encoding="utf-8"))
    metadata = (original / "upstream_metadata.csv").read_bytes()
    (dataset / "upstream_metadata.csv").write_bytes(metadata)
    rows = list(csv.DictReader(metadata.decode("utf-8").splitlines()))
    selected = [row for row in rows if row["test_id"] == "Test_00"]
    hashes = {}
    results = []
    for row in selected:
        name = row["test_id"] + "_" + row["env_id"] + ".pkl"
        target = dataset / name
        if not target.exists():
            keys = ["n_agents", "x_dim", "y_dim", "n_cities", "max_rail_pairs_in_city",
                    "max_rails_between_cities", "malfunction_duration_min", "malfunction_duration_max",
                    "malfunction_interval", "seed"]
            params = {key: int(row[key]) for key in keys}
            params.update(grid_mode=row["grid_mode"] == "True", speed_ratios=ast.literal_eval(row["speed_ratios"]))
            env, _, _ = env_generator(**params)
            RailEnvPersister.save(env, str(target))
        hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
        for method in ["full", "current_only", "independent", "fixed"]:
            command = [sys.executable, str(root / "src" / "run.py"), "--method", method,
                       "--scenario", name, "--dataset-version", "v2-audit", "--steps", "1000"]
            completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
            if completed.returncode:
                raise RuntimeError(completed.stderr)
            output = Path(completed.stdout.strip().splitlines()[-1])
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            results.append({"run": str(output.relative_to(root)), **summary})
            print(name, method, summary["arrived"], summary["dependency_unique_blocks"], flush=True)
    (dataset / "manifest.json").write_text(json.dumps({"upstream_commit": upstream["upstream_commit"],
        "source": upstream["source"], "flatland_version": "4.2.6", "selected": selected,
        "kind": "all ten Test_00 official parameter configurations regenerated locally",
        "sha256": hashes}, indent=2), encoding="utf-8")
    output = root / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-dependency-audit.json")
    output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    methods = ["full", "current_only", "independent", "fixed"]
    lines = ["# 未来依赖审计：十个官方配置", "", "本报告由脚本直接汇总规则后端实际结果。十个配置各运行一次，不计算统计显著性。", "",
             "| 方法 | 到达/总列车 | 全部完成实例 | 未来依赖候选检查 | 无公开轨迹冲突的依赖检查 |", "| --- | --- | --- | --- | --- |"]
    for method in methods:
        group = [item for item in results if item["args"]["method"] == method]
        lines.append(f"| {method} | {sum(item['arrived'] for item in group)}/{sum(item['agents'] for item in group)} | {sum(item['arrived']==item['agents'] for item in group)}/{len(group)} | {sum(item['dependency_candidate_checks'] for item in group)} | {sum(item['dependency_unique_blocks'] for item in group)} |")
    lines += ["", "## 按场景配对", "", "| 场景 | full | current_only | independent | fixed |", "| --- | --- | --- | --- | --- |"]
    for row in selected:
        name = row["test_id"]+"_"+row["env_id"]+".pkl"
        group = {item["args"]["method"]: item for item in results if item["args"]["scenario"] == name}
        lines.append("| "+name+" | "+" | ".join(str(group[method]["arrived"])+"/7" for method in methods)+" |")
    lines += ["", "## 解释边界", "", "- current_only保留未来轨迹冲突前瞻和确认，仅去掉未来依赖登记与保护；更准确地说，这是无未来依赖登记消融，而非完全短视的Agent。",
              "- 无公开轨迹冲突的依赖检查仅为候选级诊断，不等于最终被拒绝次数、实际避免损失数或统计独立样本。",
              "- 即使候选级有独立检查，仍需检查其时间对齐、版本和执行语义，不能直接认定创新有效。",
              "- 十个实例均为开发审计，不能事后挑选有利实例冒充独立测试集；未改变地图或故障强度来保证胜出。",
              "- 同一pickle复用但原生故障可能随策略执行而不同；本轮规则后端不检验LLM独立增益。",
              "", f"原始汇总：`{output.relative_to(root).as_posix()}`。"]
    (root / "未来依赖十场景审计.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(output, flush=True)


if __name__ == "__main__":
    main()
