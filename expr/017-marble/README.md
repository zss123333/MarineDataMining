# MARBLE 原生协作任务验收

运行器使用上游 coding task 1、三个原始角色、graph 协调与原始工具；不包含我们的前瞻协调改进。默认只跑一轮用于检查链路，不是完整任务效果实验。原任务三人均为高级 Python 开发者，不擅自改成架构师/开发/测试分工，也不把该任务默认策略称为 ReAct 实验。

许可证核对：pyproject.toml 声明 Apache 2.0，但实际 LICENSE 文件为 MIT，存在上游元数据不一致。当前不分发上游源码，后续分发须保留原文件并进一步确认。

源码下载：https://codeload.github.com/ulab-uiuc/MARBLE/zip/refs/heads/main

本次下载 ZIP 的 SHA256：56401033F92028CFBE2BD658E86A20CF69FCA3B755F88B568163BE7BBA1BE3FA。通过 GitHub ZIP 归档注释解析 commit：eae9f15e5b9f1e808f8ff61800b129d5538c1b47。须保留该归档，不能把未来下载的 main 当作同一版本。

适配仅在本目录启动器进行：跳过未使用任务的重量级环境导入（使用时直接报错）、通过 LiteLLM 连接本地 Ollama、记录全部实际模型请求/返回、每请求 180 秒超时及每进程 200 次模型调用保护。上游源码未编辑。模型与上下文参数写入日志。工具内部调用和评估调用同样计入日志。

默认模型 qwen2.5:7b，本机 CPU 推理可能较慢。验收模型和裁判使用同一个本地模型，因此评分不是独立可靠的质量证明。结果 JSONL 中的完成状态表示引擎运行结束，不等于软件任务满足全部需求；需要另查交付物。

PowerShell 启动命令（源码解压在当前机器临时目录）：

```powershell
$env:PYTHONUTF8='1'; $env:LITELLM_LOCAL_MODEL_COST_MAP='True'; & 'C:\zss\repo\github\zss-car-pla\课程\海洋数据挖掘\最终作业\expr\017-marble\.venv\Scripts\python.exe' -u 'C:\zss\repo\github\zss-car-pla\课程\海洋数据挖掘\最终作业\expr\017-marble\run.py' --source 'C:\Users\15085\AppData\Local\Temp\marine-marble\MARBLE-main'
```

日志与产物位于 runs/时间戳，包含 metadata.json、model_calls.jsonl、原生运行结果和独立任务 workspace。不要将可能包含敏感内容的模型日志公开上传。

启动记录：110415 批次因依赖尚未安装完而退出；110828 批次因上游 Config.load 使用 Windows 默认 GBK 读取 UTF-8 配置而失败，未发出模型请求。110941 批次使用 PYTHONUTF8=1 重启，已进入原生 Agent.act 并发出首个模型请求。开启本地模型价格表避免启动时联网超时；这不影响决策策略。实际结束状态以结果日志为准。
