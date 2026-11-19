import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'dynamic_runs/20261118-172010'
OUT = ROOT / 'figures'
OUT.mkdir(exist_ok=True)
plt.rcParams.update({'font.sans-serif': ['Microsoft YaHei'], 'axes.unicode_minus': False,
                     'font.size': 11, 'savefig.dpi': 200})
COLORS = ['#246991', '#2b947f', '#cf8a32', '#8b69aa']
NAMES = dict(collect='采集资料', analyse='分析资料', verify='补充核验', publish='发布结果', reference='整理参考资料')
OWNERS = dict(collect=0, analyse=1, verify=1, publish=2, reference=3)
results = json.loads((DATA / 'results.json').read_text(encoding='utf-8'))
local = next(row for row in results if row['method'] == 'local' and row['configuration'] == 0)


def save(fig, name):
    fig.savefig(OUT / (name + '.png'), bbox_inches='tight', facecolor='white')
    plt.close(fig)


fig, ax = plt.subplots(figsize=(10, 7))
for owner in range(4):
    ax.axvline(owner, color='#a4b6c4', linestyle='--', linewidth=1)
    ax.text(owner, -1.1, 'Agent ' + str(owner), ha='center', weight='bold', color=COLORS[owner])
starts, ends = {}, {}
for step in local['trajectory']:
    for receipt in step['submitted']:
        if receipt['status'] == 'running':
            starts[receipt['task_id']] = step['time']
    for job in step['completed']:
        ends[job] = step['time'] + 1
for job, start in starts.items():
    owner = OWNERS[job]
    ax.add_patch(FancyBboxPatch((owner-.05, start), .1, ends[job]-start,
                              boxstyle='round,pad=0.01', color=COLORS[owner], zorder=3))
    ax.text(owner+.09, (start+ends[job])/2, NAMES[job], va='center', fontsize=10)
for source, target, when, text in [(0, 1, ends['collect'], '采集结果已就绪'), (1, 2, max(ends['analyse'], ends['verify']), '分析与核验均完成')]:
    ax.annotate('', xy=(target, when), xytext=(source, when),
                arrowprops=dict(arrowstyle='->', color='#344a5e', lw=1.8))
    ax.text((source+target)/2, when-.25, text, ha='center', fontsize=10)
ax.axhline(2, color='#c77924', linestyle=':')
ax.text(1.55, 2.5, 't=2：发布新增核验依赖', color='#a55e15', fontsize=10)
ax.set(xlim=(-.4, 3.65), ylim=(14.7, -1.7), ylabel='逻辑时间（完成记于步末边界）', xticks=[], title='真实工具执行时序与交付依赖｜局部协调·配置0')
ax.spines[['top', 'right', 'bottom']].set_visible(False)
ax.text(.02, -.1, '实线箭头表示依据产物完成记录确认的交付条件，不是历史消息发送时间。', transform=ax.transAxes, fontsize=10)
save(fig, 'execution-sequence')

fig, ax = plt.subplots(figsize=(10, 4))
positions = dict(collect=(.1,.6), analyse=(.4,.6), verify=(.4,.15), publish=(.77,.6), reference=(.77,.15))
for job, (x, y) in positions.items():
    ax.text(x, y, NAMES[job]+'\nAgent '+str(OWNERS[job]), ha='center', va='center',
            bbox=dict(boxstyle='round,pad=.6', fc='#edf4f8', ec=COLORS[OWNERS[job]]))
for source, target, changed in [('collect','analyse',False), ('analyse','publish',False), ('collect','verify',True), ('verify','publish',True)]:
    start, end = positions[source], positions[target]
    ax.annotate('', xy=end, xytext=start, arrowprops=dict(arrowstyle='->', shrinkA=52, shrinkB=52,
                color='#c77924' if changed else '#426580', linestyle='--' if changed else '-'))
ax.set(xlim=(-.05,1), ylim=(-.15,1), title='动态依赖：橙色虚线为t=2新增，参考资料工作不受影响')
ax.axis('off')
save(fig, 'dependency-change')

fig, axes = plt.subplots(1, 2, figsize=(10, 4))
methods = ['local','global','autogen']; labels = ['局部协调','全员重议','AutoGen']
for ax, key, title in zip(axes, ['calls','input_tokens'], ['模型调用次数（两配置合计）','输入token（两配置合计）']):
    values = [sum(row[key] for row in results if row['method'] == method) for method in methods]
    bars = ax.bar(labels, values, color=COLORS[:3], width=.55)
    ax.bar_label(bars, padding=4)
    ax.set_ylim(0,max(values)*1.2); ax.set_title(title)
    ax.spines[['top','right']].set_visible(False)
fig.suptitle('同等合法执行结果下的协调成本｜每配置每方法一次')
fig.tight_layout()
save(fig, 'coordination-cost')

fig, ax = plt.subplots(figsize=(9, 4))
for method, label, color in zip(methods, labels, COLORS):
    row = next(row for row in results if row['method']==method and row['configuration']==0)
    ax.step([step['time'] for step in row['trajectory']], [step['versions']['3'] for step in row['trajectory']], where='post', label=label, color=color, linewidth=2)
ax.set(xlabel='逻辑轮次', ylabel='Agent 3方案版本', title='无关成员是否被反复要求安装方案｜配置0')
ax.legend(); ax.spines[['top','right']].set_visible(False)
save(fig, 'unrelated-plan')
(OUT / 'provenance.json').write_text(json.dumps(dict(source=str(DATA.relative_to(ROOT)),
    sequence='trajectory submission/completion; arrows are dependency availability, NOT message replay',
    agents=4, note='Historical experiment uses four agents; current UI three-agent mode is a different configuration'), indent=2), encoding='utf-8')
print(OUT)
