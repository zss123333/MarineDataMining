import json
from pathlib import Path


def main():
    session_id = '01a1e25d-2934-76c1-ab27-2ec872941319'
    source = next((Path.home() / '.codex' / 'sessions').rglob(f'*{session_id}*'))
    messages = []
    for line in source.read_text(encoding='utf-8').splitlines():
        event = json.loads(line)
        payload = event.get('payload', {})
        if event.get('type') == 'event_msg' and payload.get('type') == 'turn_aborted':
            messages.append(('中断事件', event['timestamp'], '用户中断了当前轮次。'))
            continue
        if event.get('type') != 'response_item' or payload.get('type') != 'message':
            continue
        role = payload.get('role')
        if role not in ('user', 'assistant'):
            continue
        if payload.get('channel') not in (None, 'final', 'commentary'):
            continue
        text = '\n'.join(part.get('text', '') for part in payload.get('content', [])
                         if part.get('type') in ('input_text', 'output_text', 'text'))
        if not text.strip():
            continue
        if text.lstrip().startswith(('<environment_context>', '<turn_aborted>',
                                     'Another language model started to solve this problem',
                                     'You are performing a CONTEXT CHECKPOINT',
                                     '<context_summary>', '## Current request / task',
                                     '# Context Summary', '## Current task')):
            continue
        messages.append(('用户' if role == 'user' else '助手', event['timestamp'], text))
    header = (
        '# 03 完整会话记录\n\n'
        '本文件按本机会话原始事件日志导出，包含代码解释、实验调整、开源项目筛选、MARBLE试运行及最终报告修改等讨论，'
        '截至本次导出时已写入日志的用户消息与助手可见回复，保留中断事件。'
        f'原会话编号：{session_id}。时间戳为原日志UTC时间。\n\n'
        '不包含系统/开发者配置、环境配置、内部推理、上下文压缩摘要及工具命令/工具输出；'
        '这些不是用户与助手的对话正文。文件未用总结替换原消息，未对消息内容做改写；'
        '中断事件使用统一说明。本次导出完成后的消息不在截取范围内。\n\n'
    )
    sections = [f'## {index:03d} · {role} · {timestamp}\n\n{text}\n\n---\n\n'
                for index, (role, timestamp, text) in enumerate(messages, 1)]
    destination = Path(__file__).parent / '03-2026-11-19-协作实验推进与最终报告修改完整会话.md'
    destination.write_text(header + ''.join(sections), encoding='utf-8')
    print(f'Exported {len(messages)} entries; {destination.stat().st_size} bytes')
    print(destination)


if __name__ == '__main__':
    main()
