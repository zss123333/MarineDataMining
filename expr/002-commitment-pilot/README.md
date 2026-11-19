# 实验002：双Agent承诺与未来依赖核心预实验

状态：2026-11-09已实现首版框架，4项单元测试通过，离线工程验证完成；**尚未运行真实LLM比较，不是正式有效性结论**。实验001环境验收已通过，但其单脚本结果不能替代本实验。

## 1. 核心问题

在相同Overcooked执行器、观察与决策频率下，将队友尚未开始的未来依赖纳入修订判断，是否优于独立改计划、固定承诺期限，以及仅保护当前依赖？第一轮是控制变量预实验，不是已完成整个DACM方案。尤其要检验收益是否只是固定冻结所致。

## 2. 协议与数据

- 输入复用[统一冒烟数据v1](../datasets/overcooked-smoke/v1/README.md)。这里只复用开发地图和种子，不将它冒充新建正式测试集。
- 双厨师均有独立决策，读取同一决策前快照；共享状态、承诺、后续计划及依赖记录。调用顺序不会让第二个厨师看到第一个本拍新输出。
- 每10环境步决策一次，200步每局，承诺有效期20步；同一低层执行器将任务转成基础动作。
- 任务为投洋葱（含取料）、启动烹饪、取盘、装汤、交付、等待。物品不匹配时不偷偷丢弃，而是记录前提失败；暂不支持物品交接与清空手持物，是首版局限。
- 方法为independent、fixed_commitment、current_only、future_aware；各有三个种子，每种子随机化方法运行顺序，合计12局。
- 相同API配置与调用机会，每局40次调用，默认最多480次。单次输出上限700 token；这不是总费用上限，输入token和供应商隐藏费用仍需预算确认。

## 3. LLM输出与前瞻

LLM选择当前任务、最多四步未来宏任务，以及引用队友承诺的依赖：current/planned/predicted、预计使用步和可观察证据。字段与承诺ID程序校验，非法输出终止并留痕，不回退脚本假装模型成功。

future_aware将有效未来依赖也纳入保护，current_only只保护current。**当前保护器仍是规则门控，不是完成版“保持/等价调整/协商替代/紧急撤销”的候选决策器。** predicted在首版与planned同样保护，仅用于暴露过度保守风险，不能作为最终不确定性处理方案。期限到期释放保护，因此也不是长期依赖安全保证。

目前没有物理扰动、任务变化、修订协商和真实依赖失效判定器；不能以dependency_protections计数当作“避免失败数”。本轮先观察LLM能否稳定产生有效计划、发生多少前提失败，以及是否有实际交付。若宏动作受阻/持物卡死占主导，先修执行器，不据此否定研究假设。

## 4. 运行

使用实验001已验证的最小MDP环境，兼容性偏离见其README；正式确认实验前仍需Python3.10/NumPy1.x复核。以下在expr目录执行：

```powershell
.\001-environment-smoke-test\.venv\Scripts\python.exe -m unittest discover -s 002-commitment-pilot/tests -v
.\001-environment-smoke-test\.venv\Scripts\python.exe 002-commitment-pilot/src/pilot.py --backend offline
```

offline是固定规则双厨师，仅验收工程链路，不调用模型、不产生LLM研究证据。它不生成语义依赖，不能用于衡量未来依赖方案收益。

真实运行要求显式设置用户确认的OpenAI兼容Chat Completions接口，不猜测任何已存在密钥对应的服务：

```powershell
$env:EXPR_API_BASE = "https://实际服务地址/v1"
$env:EXPR_MODEL = "实际模型ID"
$env:EXPR_API_KEY_ENV = "已配置的密钥环境变量名"
.\001-environment-smoke-test\.venv\Scripts\python.exe 002-commitment-pilot/src/pilot.py --backend api --allow-paid
```

以上地址和模型是需替换的占位，不是验证可用的接口。也可设置EXPR_API_KEY而不设置EXPR_API_KEY_ENV。密钥不写配置，不打印。仅支持HTTPS且无URL凭证/query/fragment。模型必须支持文本JSON输出；本版不自动重试、不提供JSON修复，失败终止并记录类型，以免隐性增加费用。第一次联调应另设小配置，只保留一个方法、一个种子并降低horizon，确认输出再开480次整批运行。

## 5. 结果和限制

日志包含模型输入、文本输出、usage和耗时，不记录Authorization或错误响应体。usage缺失标注不完整，不把缺失token算成免费；不要求保存隐式思维链。运行快照保存核心代码、所复用执行器与配置，原始地图仍仅保留在统一datasets。

当前离线结果：[报告](runs/20261109-185848-offline-08e9b8/report.md)。仅说明程序能完成12局与写出轨迹/指标；不同种子在确定性脚本下不代表独立随机样本。不要从这份报告挑选方法胜负，也不进行显著性检验。

下一步：确认实际模型与端点及调用预算 → 小规模真实接口联调 → 检查双厨师交付与LLM依赖输出 → 补齐自检/规则依赖强基线、协商修订、真实失败指标和未来需求反例 → 冻结独立任务与扰动协议 → 才进入正式确认性比较。不能直接拿当前单图开发集作为投稿主结果。
