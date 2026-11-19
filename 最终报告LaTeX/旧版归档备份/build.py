from pathlib import Path
import re
import shutil
import subprocess
from datetime import datetime
import hashlib
import json

root = Path(__file__).resolve().parent
archive = root / "报告迭代版本"
archive.mkdir(exist_ok=True)
versions = [int(match.group(1)) for path in archive.iterdir()
            if path.is_dir() and (match := re.match(r"v(\d+)(?:_|$)", path.name))]
version = f"v{max(versions, default=0)+1:03d}"
stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
destination = archive / f"{version}_{stamp}"
destination.mkdir(exist_ok=False)
(root / "report-version.tex").write_text(f"\\newcommand{{\\ReportVersion}}{{{version}}}\n", encoding="utf-8")
source = root.parent / "expr/课程最终实验报告.md"
text = source.read_text(encoding="utf-8")
text = text.replace("≈", "约")
text = re.sub(r"^# .*\n", "", text, count=1)
text = re.sub(r"^>.*\n", "", text, flags=re.MULTILINE)
text = re.sub(r"(?m)^(#{2,4}) (?:\d+(?:\.\d+)*\.? )", r"\1 ", text)
text = re.sub(r"\]\((?!https?://|#)([^)]+)\)", lambda match: "](" + "../expr/" + match.group(1) + ")", text)
subprocess.run(["pandoc", "-f", "markdown", "-t", "latex", "--listings", "--shift-heading-level-by=-1", "--top-level-division=chapter", "--columns=85", "-o", str(root / "report-content.tex")], input=text, text=True, encoding="utf-8", check=True)
for iteration in range(2):
    completed = subprocess.run(["xelatex", "-interaction=nonstopmode", "-halt-on-error", "report.tex"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (destination / f"compile-{iteration+1}.log").write_bytes(completed.stdout)
    completed.check_returncode()
pdf_name = f"课程最终实验报告_{version}.pdf"
shutil.copyfile(root / "report.pdf", destination / pdf_name)
for name in ["report.tex", "report-content.tex", "report-version.tex", "build.py", "zjuthesis.cls", "LICENSE"]:
    shutil.copyfile(root / name, destination / name)
shutil.copytree(root / "config", destination / "config")
shutil.copyfile(source, destination / "课程最终实验报告.md")
metadata = {"version": version, "created_at": datetime.now().astimezone().isoformat(),
            "status": "compiled; personal details and public conversation links pending",
            "pdf": pdf_name, "pdf_sha256": hashlib.sha256((destination / pdf_name).read_bytes()).hexdigest(),
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
(destination / "version.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
shutil.copyfile(root / "report.pdf", root.parent / "课程最终实验报告.pdf")
print(destination / pdf_name)
