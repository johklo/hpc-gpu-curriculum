"""Report每 module's size, section depth, figures, code blocks and voice violations."""

import pathlib
import re
import sys

BAD = re.compile(
    r"습니다|하겠다|살펴보|다음과 같|이 문서에서는|요약하면|정리하면|결론적으로|한마디로|"
    r"주목할 점|라 할 수 있다|명확하다|강력한|혁신적|손쉽게|간편하게|원활하게|완벽한|"
    r"를 통해|에 대하여|라는 점에서"
)

def split_sections(text: str):
    """Same fence-aware split the builder uses, so counts match the rendered page."""
    sections, current, fenced = [], None, False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced:
            match = re.match(r"## +(.+)$", line)
            if match:
                current = [match.group(1).strip(), []]
                sections.append(current)
                continue
        if current:
            current[1].append(line)
    return [(title, "\n".join(body).strip()) for title, body in sections]


root = pathlib.Path(__file__).resolve().parents[1] / "content"
show_thin = "--thin" in sys.argv
total = thin_total = bad_total = 0

for path in sorted(root.glob("*.md")):
    text = path.read_text(encoding="utf-8")
    total += len(text)
    heads = split_sections(text)
    thin = [(len(body), title) for title, body in heads if len(body) < 600]
    hits = BAD.findall(text)
    thin_total += len(thin)
    bad_total += len(hits)
    print(f"{path.name:26s} {len(text):6d}자 섹션{len(heads):3d} "
          f"그림{text.count('!['):2d} 코드{text.count('```') // 2:3d} "
          f"표{text.count('| ---'):3d} 위반{len(hits)} 얇음{len(thin)}")
    if show_thin:
        for size, head in thin:
            print(f"      {size:5d}  {head}")
        for hit in hits:
            print(f"      위반: {hit}")

print(f"\n합계 {total:,}자 · 얇은 섹션 {thin_total}개 · 어투 위반 {bad_total}건")
