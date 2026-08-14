"""Build the static learning-guide site.

The site is an index: it organises links to the source articles into a learning order and
adds original module notes. It does not reproduce the articles themselves.
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def build() -> None:
    cfg = json.loads((ROOT / "curriculum.json").read_text(encoding="utf-8"))
    modules_data = json.loads((ROOT / "_modules.json").read_text(encoding="utf-8"))

    SITE.mkdir(parents=True, exist_ok=True)
    for name in ("style.css", "tokens.css", "app.js"):
        (SITE / name).write_text((ROOT / "assets" / name).read_text(encoding="utf-8"), encoding="utf-8")
    (SITE / ".nojekyll").write_text("", encoding="utf-8")

    total = sum(len(modules_data.get(m["id"], [])) for m in cfg["modules"])
    dates = sorted(p["date"] for m in cfg["modules"] for p in modules_data.get(m["id"], []) if p.get("date"))

    rail = []
    for module in cfg["modules"]:
        count = len(modules_data.get(module["id"], []))
        rail.append(
            f'<li><a href="#{esc(module["id"])}" aria-current="false">'
            f'<span class="n">{esc(module["no"])}</span>'
            f'<span class="t">{esc(module["title"])}</span>'
            f'<span class="c" data-total="{count}">{count}</span></a></li>'
        )

    body = []
    for module in cfg["modules"]:
        entries = modules_data.get(module["id"], [])
        rows = []
        for index, post in enumerate(entries, start=1):
            haystack = f'{post["short"]} {post["title"]}'.lower()
            rows.append(
                f'<li data-search="{esc(haystack)}">'
                f'<a href="{esc(post["url"])}" target="_blank" rel="noopener">'
                f'<span class="i">{index:02d}</span>'
                f'<span class="t">{esc(post["short"])}'
                f'{f"<span class=\"d\">{esc(post['date'])}</span>" if post.get("date") else ""}</span></a></li>'
            )
        outcomes = "".join(f"<li>{esc(item)}</li>" for item in module["outcomes"])
        body.append(
            f'<section class="module" id="{esc(module["id"])}">'
            f'<div class="module-head">'
            f'<span class="module-no">MODULE {esc(module["no"])}</span>'
            f'<h2>{esc(module["title"])}'
            f'<span class="badge" data-level="{esc(module["level"])}">{esc(module["level"])}</span></h2>'
            f'<p class="sub">{esc(module["subtitle"])}</p></div>'
            f'<p class="lead">{esc(module["lead"])}</p>'
            f'<div class="outcomes"><span class="lbl">이 모듈을 마치면</span><ul>{outcomes}</ul></div>'
            f'<p class="list-lbl">읽을 글 {len(entries)}편</p>'
            f'<ol class="entries">{"".join(rows)}</ol>'
            f'<p class="empty hidden">검색어와 일치하는 글이 없습니다.</p>'
            f"</section>"
        )

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    page = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(cfg["site_title"])}</title>
<meta name="description" content="{esc(cfg["site_description"])}">
<meta property="og:title" content="{esc(cfg["site_title"])}">
<meta property="og:description" content="{esc(cfg["site_description"])}">
<link rel="stylesheet" href="style.css">
</head><body>
<div class="shell">
<aside class="rail">
  <a class="rail-brand" href="#top">
    <span class="mark">Learning Index</span>
    <span class="name">{esc(cfg["site_title"])}</span>
  </a>
  <button class="rail-toggle" type="button" aria-expanded="true" aria-controls="rail-nav">목차 닫기</button>
  <input class="rail-search" id="q" type="search" placeholder="주제·키워드 검색" aria-label="글 검색">
  <ul class="rail-nav" id="rail-nav">{"".join(rail)}</ul>
  <p class="rail-foot">
    글 {total}편 · 모듈 {len(cfg["modules"])}개<br>
    원문 출처 <a href="{esc(cfg["source_url"])}" target="_blank" rel="noopener">{esc(cfg["source_name"])}</a>
  </p>
</aside>

<main class="main" id="top">
  <header class="masthead">
    <h1>{esc(cfg["site_title"])}</h1>
    <p class="tagline">{esc(cfg["site_tagline"])}</p>
    <ul class="stats">
      <li><b>{total}</b>정리된 글</li>
      <li><b>{len(cfg["modules"])}</b>학습 모듈</li>
      <li><b>{esc(dates[0][:7] if dates else "")}</b>수록 시작</li>
    </ul>
  </header>

  <p class="note">이 사이트는 <strong>학습 순서를 붙인 색인</strong>입니다. 각 모듈의 설명과 학습 목표는
  직접 작성했고, 글 본문은 옮기지 않았습니다. 제목을 누르면 원문
  <a href="{esc(cfg["source_url"])}" target="_blank" rel="noopener">{esc(cfg["source_name"])}</a>으로 이동합니다.
  모든 저작권은 원저자에게 있습니다.</p>

  {"".join(body)}

  <footer class="foot">
    <span>마지막 갱신 {esc(generated)}</span>
    <span>원문 <a href="{esc(cfg["source_url"])}" target="_blank" rel="noopener">{esc(cfg["source_name"])}</a></span>
  </footer>
</main>
</div>
<script src="app.js"></script>
</body></html>
"""
    (SITE / "index.html").write_text(page, encoding="utf-8")
    print(f"Built {SITE/'index.html'}: {total} entries across {len(cfg['modules'])} modules.")


if __name__ == "__main__":
    build()
