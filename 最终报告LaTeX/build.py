from pathlib import Path
import re
import shutil
import subprocess

root = Path(__file__).resolve().parent
archive = root / "报告迭代版本"
archive.mkdir(exist_ok=True)
versions = [int(match.group(1)) for path in archive.iterdir()
            if path.is_file() and (match := re.search(r"_v(\d+)\.pdf$", path.name))]
version = f"v{max(versions, default=0)+1:03d}"
source = root.parent / "expr/课程最终实验报告.md"
text = source.read_text(encoding="utf-8")
table_ids = re.findall(r"(?m)^: .*?\{#(tbl-[\w-]+)\}$", text)
text = re.sub(r"(?m)^(: .*?)\s*\{#tbl-[\w-]+\}$", r"\1", text)
chapter_tables = {}
current_chapter = None
for line in text.splitlines():
    chapter = re.match(r"## (\d+)\.", line)
    if chapter:
        current_chapter = int(chapter.group(1))
    if line.startswith(": "):
        chapter_tables[current_chapter] = chapter_tables.get(current_chapter, 0) + 1
        number = f"{current_chapter}-{chapter_tables[current_chapter]}"
        text = text.replace("表" + number + "给出", r"表\ref{" + table_ids[sum(chapter_tables.values())-1] + "}给出")
        text = text.replace("见表" + number + "。", r"见表\ref{" + table_ids[sum(chapter_tables.values())-1] + "}。")
citation_keys = ["course", "react", "repair", "schedules", "mpc", "dmpc", "syncplan", "strongermas", "flatland", "autogen"]
text = re.sub(r"\[(10|[1-9])\](?!\()", lambda match: r"\cite{" + citation_keys[int(match.group(1))-1] + "}", text)
text = text.replace("≈", "约")
text = re.sub(r"(?<!\()(https?://[^\s；。；）]+)", r"<\1>", text)
text = re.sub(r"^# .*\n", "", text, count=1)
text = re.sub(r"^>.*\n", "", text, flags=re.MULTILINE)
text = re.sub(r"(?m)^(#{2,4}) (?:\d+(?:\.\d+)*\.? )", r"\1 ", text)
text = re.sub(r"\]\((?!https?://|#)([^)]+)\)", lambda match: "](" + "../expr/" + match.group(1) + ")", text)
subprocess.run(["pandoc", "-f", "markdown", "-t", "latex", "--listings", "--shift-heading-level-by=-1", "--top-level-division=chapter", "--columns=85", "-o", str(root / "report-content.tex")], input=text, text=True, encoding="utf-8", check=True)
content = root / "report-content.tex"
latex = content.read_text(encoding="utf-8").replace(r"\chapter{摘要}", r"\chapter*{摘要}\markboth{摘要}{摘要}")
latex = re.sub(r"\\includegraphics\[([^\]]*)\]", lambda match:
               r"\includegraphics[" + match.group(1).replace(r"height=\textheight", r"height=0.68\textheight")
               + ",keepaspectratio]", latex)
table_weights = [
    [18, 24, 25, 33], [18, 45, 37], [30, 70],
    [20, 12, 12, 15, 14, 14, 13], [22, 19, 14, 14, 14, 17],
    [24, 12, 15, 20, 15, 14], [21, 9, 12, 10, 16, 11, 9, 12],
    [21, 8, 14, 10, 19, 15, 13], [24, 14, 18, 24, 20],
    [9, 28, 9, 12, 14, 14, 14], [25, 14, 23, 15, 23],
]
table_index = 0
def fit_table(match):
    global table_index
    columns = len(match.group(2))
    weights = table_weights[table_index]
    table_index += 1
    if len(weights) != columns:
        raise ValueError(f"Table {table_index}: column count changed; update layout")
    available = f"\\dimexpr\\linewidth-{12*(columns-1)}pt\\relax"
    specs = []
    for index, weight in enumerate(weights):
        alignment = r"\raggedright" if index == 0 or columns <= 4 else r"\centering"
        if table_index == 10 and index == 1:
            alignment = r"\raggedright"
        specs.append(r">{" + alignment + r"\arraybackslash}p{" +
                     f"\\dimexpr({available})*{weight}/{sum(weights)}\\relax" + "}")
    return match.group(1) + "@{}" + "".join(specs) + "@{}}"
latex = re.sub(r"(\\begin\{longtable\}\[[^\]]*\]\{)@\{\}([lrc]+)@\{\}\}", fit_table, latex)
caption_index = 0
def label_caption(match):
    global caption_index
    label = table_ids[caption_index]
    caption_index += 1
    return match.group(0) + r"\label{" + label + "}"
latex = re.sub(r"\\begin\{longtable\}.*?\\end\{longtable\}",
               lambda table: re.sub(r"\\caption\{[^\n]*\}", label_caption, table.group(0)),
               latex, flags=re.DOTALL)
if table_index != len(table_weights):
    if table_ids:
        raise ValueError("Table inventory changed; review captions and widths")
content.write_text(latex, encoding="utf-8")
for iteration in range(3):
    completed = subprocess.run(["xelatex", "-interaction=nonstopmode", "-halt-on-error", "report.tex"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (root / f"compile-{iteration+1}.log").write_bytes(completed.stdout)
    completed.check_returncode()
    if iteration == 0:
        bibliography = subprocess.run(["bibtex", "report"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (root / "compile-bibtex.log").write_bytes(bibliography.stdout)
        bibliography.check_returncode()
pdf_name = f"课程最终实验报告_{version}.pdf"
destination = archive / pdf_name
with destination.open("xb") as output:
    output.write((root / "report.pdf").read_bytes())
shutil.copyfile(root / "report.pdf", root.parent / "课程最终实验报告.pdf")
print(destination)
