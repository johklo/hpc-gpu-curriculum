"""content/ 의 Markdown 문서를 정적 사이트로 만든다.

문서 한 편이 모듈 하나다. 머리말에서 제목과 난이도를 읽고, 본문의 `## ` 제목을 갈라
왼쪽 목차의 항목으로 쓴다. 절마다 GitHub 편집 화면으로 가는 고치기 링크를 붙인다.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
SITE = ROOT / "site"
CONF = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))

MD = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists"])


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def slug(text: str) -> str:
    text = re.sub(r"[^0-9A-Za-z가-힣\s-]", "", text).strip().lower()
    return re.sub(r"\s+", "-", text) or "section"


def parse(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    if raw.startswith("---"):
        head, _, raw = raw.partition("\n---\n")
        for line in head.lstrip("-\n").splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                meta[key.strip()] = value.strip().strip('"')

    parts = re.split(r"^## +(.+)$", raw, flags=re.MULTILINE)
    sections = []
    for index in range(1, len(parts), 2):
        title = parts[index].strip()
        sections.append({"title": title, "id": slug(title), "body": parts[index + 1].strip()})

    return {
        "file": path.name,
        "id": meta.get("id") or path.stem,
        "no": meta.get("no", ""),
        "title": meta.get("title", path.stem),
        "subtitle": meta.get("subtitle", ""),
        "level": meta.get("level", ""),
        "intro": parts[0].strip(),
        "sections": sections,
    }


def render(text: str) -> str:
    MD.reset()
    return MD.convert(text)


def build() -> None:
    modules = [parse(p) for p in sorted(CONTENT.glob("*.md"))]
    SITE.mkdir(parents=True, exist_ok=True)
    for name in ("style.css", "tokens.css", "app.js"):
        (SITE / name).write_text((ROOT / "assets" / name).read_text(encoding="utf-8"), encoding="utf-8")

    images = SITE / "img"
    images.mkdir(exist_ok=True)
    for source in sorted((ROOT / "assets" / "img").glob("*.svg")):
        (images / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (SITE / ".nojekyll").write_text("", encoding="utf-8")

    edit_base = CONF["edit_base"].rstrip("/")
    rail, body = [], []

    for module in modules:
        subs = "".join(
            f'<li><a href="#{esc(module["id"])}--{esc(section["id"])}">{esc(section["title"])}</a></li>'
            for section in module["sections"]
        )
        rail.append(
            f'<li class="rail-mod"><a class="rail-top" href="#{esc(module["id"])}" aria-current="false">'
            f'<span class="n">{esc(module["no"])}</span>'
            f'<span class="t">{esc(module["title"])}</span></a>'
            f'<ul class="rail-sub">{subs}</ul></li>'
        )

        edit_url = f"{edit_base}/{module['file']}"
        sections_html = "".join(
            f'<section class="sec" id="{esc(module["id"])}--{esc(section["id"])}" '
            f'data-search="{esc((section["title"] + " " + section["body"]).lower())}">'
            f'<h3>{esc(section["title"])}'
            f'<a class="edit" href="{esc(edit_url)}" target="_blank" rel="noopener">고치기</a></h3>'
            f'{render(section["body"])}</section>'
            for section in module["sections"]
        )
        body.append(
            f'<article class="module" id="{esc(module["id"])}">'
            f'<header class="module-head">'
            f'<span class="module-no">{esc(module["no"])}</span>'
            f'<h2>{esc(module["title"])}'
            f'<span class="badge" data-level="{esc(module["level"])}">{esc(module["level"])}</span></h2>'
            f'<p class="sub">{esc(module["subtitle"])}</p></header>'
            f'<div class="intro">{render(module["intro"])}</div>'
            f'{sections_html}</article>'
        )

    total = sum(len(m["sections"]) for m in modules)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    page = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(CONF["title"])}</title>
<meta name="description" content="{esc(CONF["description"])}">
<meta property="og:title" content="{esc(CONF["title"])}">
<meta property="og:description" content="{esc(CONF["description"])}">
<link rel="stylesheet" href="style.css">
</head><body>
<div class="shell">
<aside class="rail">
  <a class="rail-brand" href="#top">
    <span class="mark">Handbook</span>
    <span class="name">{esc(CONF["title"])}</span>
  </a>
  <button class="rail-toggle" type="button" aria-expanded="true" aria-controls="rail-nav">목차 닫기</button>
  <input class="rail-search" id="q" type="search" placeholder="문서 검색" aria-label="문서 검색">
  <ul class="rail-nav" id="rail-nav">{"".join(rail)}</ul>
  <p class="rail-foot">
    모듈 {len(modules)}개 · 문서 {total}편<br>
    <a href="{esc(CONF["repo"])}" target="_blank" rel="noopener">저장소에서 고치기</a>
  </p>
</aside>

<main class="main" id="top">
  <header class="masthead">
    <h1>{esc(CONF["title"])}</h1>
    <p class="tagline">{esc(CONF["tagline"])}</p>
    <ul class="stats">
      <li><b>{len(modules)}</b>모듈</li>
      <li><b>{total}</b>문서</li>
      <li><b>{esc(generated)}</b>갱신</li>
    </ul>
  </header>

  <p class="note">문서 제목 옆의 <b>고치기</b>를 누르면 GitHub 편집 화면이 열린다.
  고쳐서 저장하면 변경 이력이 남고 잠시 뒤 사이트에 반영된다. 틀린 내용이나 빠진 설명은
  직접 고치면 된다.</p>

  {"".join(body)}

  <footer class="foot">
    <span>갱신 {esc(generated)}</span>
    <span><a href="{esc(CONF["repo"])}" target="_blank" rel="noopener">GitHub</a></span>
  </footer>
</main>
</div>
<script src="app.js"></script>
</body></html>
"""
    (SITE / "index.html").write_text(page, encoding="utf-8")
    print(f"모듈 {len(modules)}개, 문서 {total}편을 만들었다.")


if __name__ == "__main__":
    build()
