# Overcooked 冒烟输入 v1

- 来源：HumanCompatibleAI/overcooked_ai，提交 `739950a079cdaed5a44fcc662efc40244c205d06`。
- 原始输入：上游 `cramped_room.layout`，以及原始 MIT LICENSE；原样保存于 `raw/`，版权与许可见 `raw/UPSTREAM_LICENSE`。
- 用途：实验001的环境验收；不是训练集、正式测试集或人工采集的行为数据。
- `splits/smoke.json` 固定布局和种子 `[0,1,2]`。固定初态、脚本和动力学都是确定性的，三个种子不构成三个独立随机任务。
- 数量：一张地图、三个开发用种子配置；没有专家轨迹或LLM训练样本。
- 下载、SHA-256及大小：见 `manifest.json`。输入不修改，协议变更新建版本。
- 重建：在实验001执行 `python scripts/prepare_dataset.py`；已有版本只验证校验值，不覆盖。
- 环境源码在Python依赖中管理，不作为数据集重复保存；轨迹保留在实验001的 `runs/`。
