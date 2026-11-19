# 局部变更与连锁协调验证

日期2026-11-14。直接调用通用核心，不复制新协议，不使用Flatland或LLM。此目录是小型确定性能力测试，不是协作效果benchmark。无需下载数据，任务在demo.py中明确构造，因此没有另建数据集副本。

A最初只联系B。B生成自己的局部响应后发现影响C，C再发现影响D；扩展后A/B/C/D重新核验并提交。E不相关、不收到消息、不计算响应。每个成员有shared和independent两个片段；本轮只修改shared。private_plan中保存补丁，消息中没有完整私有任务。

三项测试通过：连锁协调后无关片段内容和版本不变、E不参与；无关片段变化不使补丁失效；相关读取版本变化必须拒绝补丁。旧004的31项及006的10项测试也通过。输出runs/local-chain.json保存各片段版本、安装次数、收件人和协议轨迹。本验证说明能力发生，不证明比全量重规划更快或减少真实模型token。

```powershell
$py = "最终作业/expr/003-flatland-core/.venv/Scripts/python.exe"
& $py -m unittest discover -s 最终作业/expr/007-local-chain -v
& $py 最终作业/expr/007-local-chain/demo.py
```

后续真实任务适配必须正确声明补丁读集合及潜在依赖，遗漏读取或依赖会破坏保证。本轮没有实现自动语义依赖识别，也没有把007结果计入006完成率或声称铁路换序已完成。
