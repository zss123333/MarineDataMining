# 最终报告LaTeX

当前入口report.tex已切换为用户指定USTC_研究生院官方LaTeX模板中的ustcthesis类（master、Windows字体、单面）。类文件、参考文献样式、示例入口、示例配置及figures已复制，许可见LICENSE-USTC。旧zjuthesis文件仅为历史残留，不再加载。课程封面仍明确标为课程实验报告，不生成学位原创声明，不冒用示例作者信息。

按用户指定路径复制研究生论文模板的config、page、body、figure、类文件、原始入口及LICENSE，未复制.git、编辑器配置、输出缓存或下载记录。原模板为TheNetAdmin/zjuthesis，保留其许可。report.tex使用其类和排版配置，但改为课程封面，不生成浙江大学学位声明或虚构学校身份。

最终入口是report.tex，不是模板示例zjuthesis.tex。report-content.tex由上级expr/课程最终实验报告.md生成，不单独维护两份正文。build.py调用Pandoc和XeLaTeX两遍，生成report.pdf并复制到上级课程最终实验报告.pdf。需本机安装中文字体及TeX Live；本机已具备。

编译：`python 最终作业/最终报告LaTeX/build.py`。

每次成功构建在报告迭代版本直接新增带版本号的PDF，不覆盖旧PDF。该目录只放PDF；源码、配置和日志统一留在当前目录，不作版本快照，封面不标版本号。两遍XeLaTeX算同一版。

封面姓名、学号由本人填写。完整会话与真实Public链接仍为硬性待办，PDF显著提示，不虚构完成状态。论文模板原始示例正文仅作模板保留，不进入report.pdf，也不应作为本作业原创内容提交。
