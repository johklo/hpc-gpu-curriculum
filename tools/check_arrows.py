"""Flag arrows used as prose connectors. Diagrams, code blocks and tables may keep them."""

import pathlib

FENCE = "```"
found = 0
for path in sorted(pathlib.Path("content").glob("*.md")):
    inside = False
    for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        if line.startswith(FENCE):
            inside = not inside
            continue
        if inside or "\u2192" not in line:
            continue
        if line.strip().startswith("|") or line.strip().startswith("!["):
            continue
        print(f"{path.name}:{number}  {line.strip()[:90]}")
        found += 1
print(f"문장 안 화살표 {found}건")
