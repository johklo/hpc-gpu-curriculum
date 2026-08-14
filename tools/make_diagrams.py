"""Draw the handbook's SVG figures from code so the palette stays consistent.

Every figure is composed here rather than exported from a drawing tool, which keeps the
colours tied to tokens.css and makes the alt text a required argument instead of an
afterthought.
"""

from __future__ import annotations

import pathlib
from xml.sax.saxutils import escape

OUT = pathlib.Path(__file__).resolve().parents[1] / "assets" / "img"

C = {
    "bg": "#EDF1ED",
    "ink": "#0D1C14",
    "ink2": "#38463E",
    "muted": "#5F6D65",
    "rule": "#D3D9D2",
    "accent": "#006763",
    "accentBg": "#D6F2EF",
    "warn": "#8A5600",
    "warnBg": "#F7EEE0",
    "danger": "#A5292B",
    "dangerBg": "#FBE9E6",
    "white": "#FFFFFF",
}

SANS = "IBM Plex Sans, Segoe UI, Helvetica, sans-serif"
MONO = "JetBrains Mono, Consolas, monospace"


def head(width: int, height: int, title: str, desc: str) -> list:
    markers = "".join(
        f'<marker id="{key}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
        f'markerHeight="6" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{colour}"/></marker>'
        for key, colour in (("a", C["accent"]), ("b", C["muted"]), ("w", C["warn"]), ("r", C["danger"]))
    )
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" '
        f'aria-labelledby="t d"><title id="t">{escape(title)}</title>'
        f'<desc id="d">{escape(desc)}</desc>'
        f'<rect width="{width}" height="{height}" fill="{C["bg"]}"/><defs>{markers}</defs>',
    ]


def txt(x, y, s, size=11, colour=None, font=MONO, weight=400, anchor="start", mid=False) -> str:
    baseline = ' dominant-baseline="middle"' if mid else ""
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}"{baseline} font-family=\'{font}\' '
        f'font-size="{size}" font-weight="{weight}" fill="{colour or C["ink2"]}">{escape(s)}</text>'
    )


def title_line(s: str) -> str:
    return txt(24, 28, s, size=13, colour=C["ink"], font=SANS, weight=600)


def box(x, y, w, h, lines, fill=None, stroke=None, dash=None) -> str:
    out = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill or C["white"]}" '
        f'stroke="{stroke or C["rule"]}" stroke-width="1.5" rx="2"'
        + (f' stroke-dasharray="{dash}"' if dash else "")
        + "/>"
    ]
    total = len(lines)
    start = y + h / 2 - (total - 1) * 9
    for index, (label, size, font, weight, colour) in enumerate(lines):
        if label:
            out.append(
                txt(x + w / 2, start + index * 18, label, size=size, colour=colour,
                    font=font, weight=weight, anchor="middle", mid=True)
            )
    return "".join(out)


def strong(s, size=13, colour=None):
    return (s, size, SANS, 600, colour or C["ink"])


def small(s, size=10, colour=None):
    return (s, size, MONO, 400, colour or C["muted"])


def line(x1, y1, x2, y2, colour=None, marker="a", dash=None, width=1.8) -> str:
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{colour or C["accent"]}" '
        f'stroke-width="{width}" marker-end="url(#{marker})"'
        + (f' stroke-dasharray="{dash}"' if dash else "")
        + "/>"
    )


def rule(x1, y, x2) -> str:
    return f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{C["rule"]}" stroke-width="1"/>'


def write(name: str, parts: list) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text("".join(parts) + "</svg>", encoding="utf-8")
    print(f"  {name}")


# ---------------------------------------------------------------- 05 parallel fs

def llm_io_traffic() -> None:
    """What actually crosses the wire between GPU nodes and Lustre during an LLM run."""
    w, h = 900, 540
    p = head(w, h, "LLM 학습 중 GPU 노드와 Lustre 사이를 오가는 트래픽",
             "노드에서 스토리지로 가는 트래픽과 스토리지에서 노드로 오는 트래픽을 종류별로 방향과 "
             "양과 빈도로 나눠 표시했다. 매 스텝의 all-reduce는 컴퓨트 패브릭에서만 오가고 "
             "스토리지를 지나지 않는다.")
    p.append(title_line("LLM 학습에서 노드와 Lustre 사이를 오가는 것"))

    p.append(box(24, 66, 176, 310, [
        strong("GPU 노드 64대"),
        small("GPU 512장"),
        small(""),
        small("한 대가 곧"),
        small("Lustre 클라이언트"),
        small("한 개다"),
    ], fill=C["accentBg"], stroke=C["accent"]))

    p.append(box(700, 66, 176, 310, [
        strong("Lustre"),
        small(""),
        small("MDT · 파일 위치"),
        small("OST 32대 · 내용"),
        small(""),
        small("한계 20 GB/s"),
    ]))

    rows = [
        ("① 학습을 시작할 때 한 번", "체크포인트와 토크나이저를 읽는다", "980 GB", "read"),
        ("② 매 스텝", "토큰 샤드를 읽는다", "1.6 MB/s", "read"),
        ("③ 30분마다", "체크포인트를 쓴다", "980 GB · 49초", "write"),
        ("④ 노드가 빠진 뒤", "체크포인트를 되읽는다", "980 GB", "read"),
        ("⑤ 학습 내내", "로그와 지표를 쓴다", "양은 작고 open이 많다", "write"),
    ]
    y = 110
    for label, what, volume, kind in rows:
        read = kind == "read"
        colour = C["accent"] if read else C["warn"]
        marker = "a" if read else "w"
        x1, x2 = (692, 210) if read else (210, 692)
        p.append(txt(216, y - 12, label, size=10, colour=C["muted"]))
        p.append(txt(686, y - 12, volume, size=11, colour=colour, anchor="end", weight=600))
        p.append(line(x1, y, x2, y, colour=colour, marker=marker))
        p.append(txt(216, y + 22, what, size=12, colour=C["ink2"], font=SANS))
        y += 56

    p.append(rule(24, 404, 876))
    p.append(f'<path d="M 62 380 C 40 444, 166 444, 144 380" fill="none" stroke="{C["ink2"]}" '
             f'stroke-width="2" marker-end="url(#b)"/>')
    p.append(txt(216, 428, "매 스텝 노드 사이에서 기울기를 합친다", size=12, colour=C["ink2"], font=SANS))
    p.append(txt(216, 448, "all-reduce · 스텝당 280 GB · 컴퓨트 패브릭", size=10, colour=C["muted"]))
    p.append(txt(686, 434, "스토리지로 가지 않는다", size=11, colour=C["ink2"], anchor="end", weight=600))

    p.append(rule(24, 470, 876))
    p.append(txt(24, 494, "읽기는 왼쪽 방향, 쓰기는 오른쪽 방향이다. 스토리지로 가는 양은 거의 전부가 ①③④의 체크포인트다.", size=11))
    p.append(txt(24, 514, "②의 토큰 읽기는 클러스터 전체를 합쳐도 초당 수 MB라 같은 축에 그리면 보이지 않는다.", size=11))
    write("llm-io-traffic.svg", p)


def training_io_timeline() -> None:
    """The same traffic on a time axis, because the shape is what surprises people."""
    w, h = 900, 360
    p = head(w, h, "학습 시간축에서 본 스토리지 부하",
             "토큰 읽기는 축척으로 보이지 않을 만큼 작고 일정하다. 체크포인트 쓰기만 주기적으로 "
             "상한까지 치솟으며 그동안 계산이 멈춘다. 노드가 빠지면 되읽기가 한 번 더 일어난다.")
    p.append(title_line("시간축에서 본 스토리지 부하"))

    base, top, left, right = 268, 96, 96, 856
    p.append(f'<line x1="{left}" y1="{base}" x2="{right}" y2="{base}" stroke="{C["ink2"]}" stroke-width="1.5"/>')
    p.append(f'<line x1="{left}" y1="{base}" x2="{left}" y2="{top - 12}" stroke="{C["ink2"]}" stroke-width="1.5"/>')
    p.append(txt(left - 10, top - 4, "20 GB/s", size=10, colour=C["muted"], anchor="end"))
    p.append(txt(left - 10, top + 12, "스토리지 상한", size=9, colour=C["muted"], anchor="end"))
    p.append(txt(left - 10, base + 4, "0", size=10, colour=C["muted"], anchor="end"))
    p.append(f'<line x1="{left}" y1="{top}" x2="{right}" y2="{top}" stroke="{C["rule"]}" '
             f'stroke-width="1" stroke-dasharray="4 4"/>')

    p.append(txt(412, top - 34, "체크포인트 쓰기 · 980 GB · 49초 · 그동안 GPU 512장이 논다",
                 size=11, colour=C["warn"], anchor="middle", weight=600))
    for x, label in ((124, "시작 시 읽기"), (268, None), (412, None), (556, None), (700, None)):
        p.append(f'<rect x="{x}" y="{top}" width="20" height="{base - top}" fill="{C["warnBg"]}" '
                 f'stroke="{C["warn"]}" stroke-width="1.5"/>')
        if label:
            p.append(txt(x + 10, top - 14, label, size=10, colour=C["accent"], anchor="middle"))
    p.append(f'<rect x="800" y="{top}" width="20" height="{base - top}" fill="{C["dangerBg"]}" '
             f'stroke="{C["danger"]}" stroke-width="1.5"/>')
    p.append(txt(812, top - 14, "노드 교체 후 되읽기", size=10, colour=C["danger"], anchor="middle"))

    p.append(f'<line x1="{left}" y1="{base - 2}" x2="{right}" y2="{base - 2}" '
             f'stroke="{C["accent"]}" stroke-width="2.5"/>')
    p.append(txt(left + 8, base + 22, "토큰 읽기 1.6 MB/s · 이 축척에서는 바닥에 붙는다",
                 size=10, colour=C["accent"]))

    for x, label in ((124, "0분"), (268, "30분"), (412, "60분"), (556, "90분"), (700, "120분"), (810, "장애")):
        p.append(txt(x + 10, base + 42, label, size=10, colour=C["muted"], anchor="middle"))

    p.append(rule(24, 310, 876))
    p.append(txt(24, 334, "학습 내내 읽기는 바닥에 깔리고, 스토리지가 바빠지는 순간은 저장할 때뿐이다. 용량이 아니라 이 봉우리에 맞춰 대역폭을 잡는다.", size=11))
    write("training-io-timeline.svg", p)


def rank_shard_map() -> None:
    """Which rank talks to which OST, and why one layout melts a single server."""
    w, h = 900, 400
    p = head(w, h, "랭크와 파일과 OST의 대응",
             "랭크마다 자기 샤드 파일을 하나씩 읽으면 파일이 OST 전체에 흩어져 부하가 고르다. "
             "모든 랭크가 조각 수 1인 큰 파일 하나를 읽으면 서버 한 대로 몰린다.")
    p.append(title_line("512개 랭크가 어느 OST에 붙는가"))

    p.append(txt(24, 62, "좋은 배치 · 랭크마다 자기 파일", size=12, colour=C["ink"], font=SANS, weight=600))
    for index, x in enumerate((24, 122, 220, 318)):
        p.append(box(x, 78, 84, 38, [small(f"랭크 {index}", 10, C["ink"])], fill=C["accentBg"], stroke=C["accent"]))
    p.append(txt(430, 100, "…", size=13, colour=C["muted"], mid=True))
    for index, x in enumerate((24, 122, 220, 318)):
        p.append(box(x, 152, 84, 38, [small(f"shard-{index}", 10, C["ink"])]))
        p.append(line(x + 42, 118, x + 42, 150, width=1.5))
    p.append(txt(430, 174, "…", size=13, colour=C["muted"], mid=True))
    for x in (66, 164, 262, 360):
        p.append(line(x, 192, x, 214, width=1.5))
    p.append(f'<rect x="24" y="216" width="424" height="40" fill="{C["white"]}" '
             f'stroke="{C["accent"]}" stroke-width="1.5" rx="2"/>')
    p.append(txt(236, 236, "OST 32대에 고르게 흩어진다", size=11, colour=C["accent"], anchor="middle", mid=True, weight=600))
    p.append(txt(24, 288, "조각 수는 1로 둔다. 파일이 이미 많아서", size=10))
    p.append(txt(24, 306, "파일 단위로 흩어진다.", size=10))

    p.append(f'<line x1="472" y1="52" x2="472" y2="330" stroke="{C["rule"]}" stroke-width="1"/>')

    p.append(txt(500, 62, "위험한 배치 · 모두가 큰 파일 하나", size=12, colour=C["ink"], font=SANS, weight=600))
    for index, x in enumerate((500, 598, 696, 794)):
        p.append(box(x, 78, 84, 38, [small(f"랭크 {index}", 10, C["ink"])], fill=C["accentBg"], stroke=C["accent"]))
    for x in (542, 640, 738, 836):
        p.append(line(x, 118, x, 150, width=1.5))
    p.append(box(500, 152, 378, 38, [small("tokens.bin · 조각 수 1", 10, C["ink"])], stroke=C["danger"]))
    p.append(line(689, 192, 689, 214, colour=C["danger"], marker="r", width=1.5))
    p.append(f'<rect x="640" y="216" width="98" height="40" fill="{C["dangerBg"]}" '
             f'stroke="{C["danger"]}" stroke-width="1.5" rx="2"/>')
    p.append(txt(689, 236, "OST 1대", size=11, colour=C["danger"], anchor="middle", mid=True, weight=600))
    p.append(txt(500, 288, "512개 랭크가 서버 한 대로 몰린다. 조각 수를", size=10))
    p.append(txt(500, 306, "넉넉히 주거나 파일을 나눈다.", size=10))

    p.append(rule(24, 344, 876))
    p.append(txt(24, 368, "읽는 총량이 같아도 어느 서버에 떨어지느냐로 속도가 갈린다. lfs getstripe 로 실제 배치를 확인한다.", size=11))
    write("rank-shard-map.svg", p)


# ---------------------------------------------------------------- 06/07 slurm + k8s

def slurm_k8s_split() -> None:
    """The layout that actually works when both schedulers live on one cluster."""
    w, h = 900, 470
    p = head(w, h, "Slurm과 Kubernetes를 한 클러스터에서 함께 쓰는 구조",
             "노드는 스케줄러마다 나눠 갖고, 파일시스템과 이미지와 신원과 네트워크와 지표는 함께 쓴다. "
             "한 노드를 두 스케줄러가 동시에 관리하면 자원이 이중으로 할당된다.")
    p.append(title_line("Slurm과 Kubernetes를 한 클러스터에서 함께 쓰기"))

    p.append(f'<rect x="24" y="58" width="852" height="80" fill="{C["white"]}" '
             f'stroke="{C["rule"]}" stroke-width="1.5" rx="2"/>')
    p.append(txt(36, 78, "함께 쓰는 것 · 한 벌만 둔다", size=11, colour=C["muted"]))
    shared = [
        ("공유 파일시스템", "양쪽 같은 경로"),
        ("이미지 레지스트리", "형식만 다르다"),
        ("uid / gid 신원", "파일 권한의 기준"),
        ("InfiniBand", "양쪽에서 RDMA"),
        ("DCGM 지표", "한 벌로 다 본다"),
    ]
    for index, (name, note) in enumerate(shared):
        x = 36 + index * 166
        p.append(box(x, 90, 154, 36, [small(name, 10, C["ink"]), small(note, 9)], fill=C["bg"]))

    pools = [
        (24, "Slurm 풀", "학습 · 배치 작업", "노드 48대", C["accent"], C["accentBg"]),
        (326, "이동 가능 풀", "그때그때 넘긴다", "노드 8대", C["warn"], C["warnBg"]),
        (628, "Kubernetes 풀", "추론 · 개발 · CI", "노드 8대", C["accent"], C["accentBg"]),
    ]
    for x, name, role, size, stroke, fill in pools:
        p.append(box(x, 178, 248, 96, [strong(name), small(role), small(size)], fill=fill, stroke=stroke))

    p.append(line(320, 210, 278, 210, colour=C["warn"], marker="w"))
    p.append(txt(299, 200, "resume", size=9, colour=C["warn"], anchor="middle"))
    p.append(line(278, 246, 320, 246, colour=C["warn"], marker="w"))
    p.append(txt(299, 266, "drain", size=9, colour=C["warn"], anchor="middle"))
    p.append(line(580, 210, 622, 210, colour=C["warn"], marker="w"))
    p.append(txt(601, 200, "uncordon", size=9, colour=C["warn"], anchor="middle"))
    p.append(line(622, 246, 580, 246, colour=C["warn"], marker="w"))
    p.append(txt(601, 266, "cordon", size=9, colour=C["warn"], anchor="middle"))

    p.append(f'<rect x="24" y="300" width="852" height="56" fill="{C["dangerBg"]}" '
             f'stroke="{C["danger"]}" stroke-width="1.5" rx="2"/>')
    p.append(txt(40, 322, "하지 말 것", size=11, colour=C["danger"], weight=600))
    p.append(txt(40, 344, "한 노드를 Slurm과 Kubernetes가 동시에 관리하는 구성. 서로의 할당을 모르므로 같은 GPU를 겹쳐 내주고 메모리가 터진다.",
                 size=11, colour=C["ink2"]))

    p.append(rule(24, 382, 876))
    p.append(txt(24, 406, "노드는 반드시 한 스케줄러에만 속한다. 경계를 옮기는 일은 있어도 겹치는 구간은 없다.", size=11))
    p.append(txt(24, 426, "이동 가능 풀의 크기는 두 워크로드의 성수기가 얼마나 어긋나는지로 정한다. 겹친다면 정적으로 나누는 편이 낫다.", size=11))
    p.append(txt(24, 446, "파일 권한은 uid로 매겨지므로 Kubernetes 파드도 실제 사용자 uid로 실행해야 Slurm에서 만든 파일을 읽는다.", size=11))
    write("slurm-k8s-split.svg", p)


def node_move() -> None:
    """Moving one node between the two pools without stranding a job or a pod."""
    w, h = 900, 300
    p = head(w, h, "노드를 두 스케줄러 사이에서 옮기는 절차",
             "Slurm에서 Kubernetes로 옮길 때는 새 작업을 막고 돌던 작업이 끝나기를 기다린 뒤 넘긴다. "
             "반대 방향도 파드를 비운 뒤 넘긴다. 기다리는 단계를 건너뛰면 실행 중인 작업이 죽는다.")
    p.append(title_line("노드 한 대를 옮기는 절차"))

    steps = [
        ("Slurm 보유", "작업이 돌고 있다", C["accentBg"], C["accent"]),
        ("새 작업 차단", "scontrol … DRAIN", C["warnBg"], C["warn"]),
        ("작업 종료 대기", "squeue -w 가 빌 때까지", C["warnBg"], C["warn"]),
        ("K8s 편입", "kubectl uncordon", C["accentBg"], C["accent"]),
        ("K8s 보유", "파드를 받는다", C["accentBg"], C["accent"]),
    ]
    x = 24
    for index, (name, cmd, fill, stroke) in enumerate(steps):
        p.append(box(x, 70, 152, 64, [strong(name, 12), small(cmd, 9)], fill=fill, stroke=stroke))
        if index < len(steps) - 1:
            p.append(line(x + 154, 102, x + 198, 102, colour=C["ink2"], marker="b"))
        x += 202

    p.append(txt(24, 172, "되돌릴 때", size=11, colour=C["muted"]))
    p.append(txt(24, 194, "kubectl cordon 으로 새 파드를 막고, kubectl drain 으로 돌던 파드를 다른 노드로 옮긴 뒤,", size=11))
    p.append(txt(24, 214, "scontrol update NodeName=… State=RESUME 으로 Slurm에 돌려준다.", size=11))

    p.append(rule(24, 238, 876))
    p.append(txt(24, 262, "세 번째 칸을 건너뛰면 돌던 학습이 통째로 죽는다. 24시간짜리 작업이 있을 수 있어 대기는 분이 아니라 시간 단위로 잡는다.", size=11))
    p.append(txt(24, 282, "자동화한다면 대기에 상한을 두고, 상한을 넘으면 사람에게 알리고 멈춘다. 강제로 끊는 자동화는 두지 않는다.", size=11))
    write("node-move.svg", p)


# ---------------------------------------------------------------- 09 glossary

def memory_hierarchy() -> None:
    """A first-day picture of where a number can live and what it costs to reach it."""
    w, h = 900, 380
    p = head(w, h, "GPU가 값을 꺼내오는 곳과 그 비용",
             "레지스터에서 멀어질수록 용량은 커지고 속도는 느려진다. 학습 성능 문제의 대부분은 "
             "값이 필요한 순간에 더 먼 칸에 있어서 생긴다.")
    p.append(title_line("값이 어디에 있느냐가 속도를 정한다"))

    tiers = [
        ("레지스터", "SM 안", "수십 KB", "가장 빠르다", C["accentBg"], C["accent"], 0),
        ("공유 메모리 · L1", "SM 안", "SM당 수백 KB", "수십 TB/s", C["accentBg"], C["accent"], 1),
        ("L2 캐시", "GPU 안", "수십 MB", "수 TB/s", C["white"], C["rule"], 2),
        ("HBM", "GPU 보드 위", "80~192 GB", "3 TB/s", C["white"], C["rule"], 3),
        ("옆 GPU의 HBM", "NVLink 건너", "같은 노드 안", "900 GB/s", C["white"], C["rule"], 4),
        ("호스트 메모리", "PCIe 건너", "1~2 TB", "50 GB/s", C["white"], C["rule"], 5),
        ("다른 노드", "InfiniBand 건너", "클러스터 전체", "25 GB/s", C["white"], C["rule"], 6),
        ("공유 스토리지", "네트워크 끝", "PB 단위", "노드당 수 GB/s", C["warnBg"], C["warn"], 7),
    ]
    y = 60
    for name, where, cap, speed, fill, stroke, index in tiers:
        width = 240 + index * 56
        p.append(f'<rect x="24" y="{y}" width="{width}" height="30" fill="{fill}" '
                 f'stroke="{stroke}" stroke-width="1.5" rx="2"/>')
        p.append(txt(36, y + 15, name, size=11, colour=C["ink"], font=SANS, weight=600, mid=True))
        p.append(txt(width + 12, y + 15, where, size=10, colour=C["muted"], anchor="end", mid=True))
        p.append(txt(676, y + 15, cap, size=10, colour=C["ink2"], mid=True))
        p.append(txt(876, y + 15, speed, size=10, colour=C["ink2"], anchor="end", mid=True))
        y += 36

    p.append(rule(24, 350, 876))
    p.append(txt(24, 372, "아래로 갈수록 넓고 느리다. 계산을 멈추게 하는 것은 대개 맨 아래 두 칸에서 값을 기다리는 시간이다.", size=11))
    write("memory-hierarchy.svg", p)


def gpu_node_anatomy() -> None:
    """What is physically inside one GPU node, and which link each hop crosses."""
    w, h = 900, 500
    p = head(w, h, "GPU 노드 한 대의 물리 구성",
             "소켓 두 개에 각각 메모리와 PCIe 스위치가 붙고, 스위치 아래에 GPU 네 장과 네트워크 "
             "카드가 달린다. GPU끼리는 NVSwitch로 따로 이어진다. 소켓을 넘는 경로가 가장 느리다.")
    p.append(title_line("GPU 노드 한 대 안에서 무엇이 어디에 붙어 있는가"))

    p.append(box(24, 62, 58, 46, [small("DDR", 10, C["ink"]), small("메모리", 9)]))
    p.append(box(818, 62, 58, 46, [small("DDR", 10, C["ink"]), small("메모리", 9)]))
    p.append(box(96, 62, 292, 46, [strong("CPU 소켓 0", 12), small("NUMA 노드 0", 9)]))
    p.append(box(512, 62, 292, 46, [strong("CPU 소켓 1", 12), small("NUMA 노드 1", 9)]))
    p.append(line(84, 85, 94, 85, colour=C["ink2"], marker="b", width=1.5))
    p.append(line(816, 85, 806, 85, colour=C["ink2"], marker="b", width=1.5))
    p.append(line(390, 85, 510, 85, colour=C["danger"], marker="r", width=2))
    p.append(txt(450, 76, "UPI · 소켓을 넘는 가장 느린 구간", size=9, colour=C["danger"], anchor="middle"))

    p.append(box(96, 152, 292, 40, [small("PCIe 스위치", 11, C["ink"])]))
    p.append(box(512, 152, 292, 40, [small("PCIe 스위치", 11, C["ink"])]))
    for x in (242, 658):
        p.append(line(x, 110, x, 150, width=1.5))
        p.append(txt(x + 8, 132, "PCIe Gen5 x16 · 64 GB/s", size=9, colour=C["muted"]))
    p.append(box(24, 152, 58, 40, [small("HCA", 10, C["ink"])], fill=C["accentBg"], stroke=C["accent"]))
    p.append(box(818, 152, 58, 40, [small("HCA", 10, C["ink"])], fill=C["accentBg"], stroke=C["accent"]))
    p.append(line(84, 172, 94, 172, colour=C["accent"], width=1.5))
    p.append(line(816, 172, 806, 172, colour=C["accent"], width=1.5))

    for index, x in enumerate((96, 174, 252, 330, 512, 590, 668, 746)):
        p.append(box(x, 238, 66, 52, [small(f"GPU {index}", 11, C["ink"]), small("HBM", 9)],
                     fill=C["accentBg"], stroke=C["accent"]))
        p.append(line(x + 33, 194, x + 33, 236, width=1.5))
        p.append(line(x + 33, 292, x + 33, 330, colour=C["accent"], marker="a", width=1.5))

    p.append(box(96, 332, 708, 40, [small("NVSwitch · GPU 사이 900 GB/s · 어느 짝이든 같은 대역", 11, C["ink"])],
                 fill=C["accentBg"], stroke=C["accent"]))

    p.append(rule(24, 400, 876))
    p.append(txt(24, 424, "학습 프로세스는 자기 GPU와 같은 소켓에 붙은 메모리를 써야 한다. 소켓을 넘으면 붉은 구간을 지나 지연이 늘고 대역폭이 준다.", size=11))
    p.append(txt(24, 444, "GPUDirect RDMA는 HCA와 GPU가 같은 PCIe 스위치 아래 있을 때 효과가 크다. 짝이 어긋나면 데이터가 소켓을 건너 돌아간다.", size=11))
    p.append(txt(24, 464, "nvidia-smi topo -m 의 PIX 는 같은 스위치, NODE 는 같은 소켓, SYS 는 소켓을 넘는 경로를 뜻한다.", size=11))
    write("gpu-node-anatomy.svg", p)


def node_states() -> None:
    """How a node moves between scheduler states, and which command causes each move."""
    w, h = 900, 410
    p = head(w, h, "노드 상태와 그 사이를 오가는 명령",
             "작업이 들어오면 할당 상태가 되고 끝나면 유휴로 돌아온다. 점검하려면 드레인을 걸어 "
             "새 작업을 막고 돌던 작업이 끝나기를 기다린다. 응답이 없으면 다운으로 떨어진다.")
    p.append(title_line("노드 상태와 그 사이를 오가는 명령"))

    states = [
        (24, "IDLE", "자원이 비어 있다", C["accentBg"], C["accent"]),
        (250, "ALLOCATED / MIXED", "일부 또는 전부 사용 중", C["accentBg"], C["accent"]),
        (476, "DRAINING", "새 작업을 안 받고 기다린다", C["warnBg"], C["warn"]),
        (702, "DRAINED", "완전히 비었다", C["warnBg"], C["warn"]),
    ]
    for x, name, note, fill, stroke in states:
        size = 12 if len(name) < 12 else 11
        p.append(box(x, 92, 150, 58, [strong(name, size), small(note, 9)], fill=fill, stroke=stroke))

    p.append(line(176, 121, 246, 121, colour=C["ink2"], marker="b"))
    p.append(txt(211, 112, "작업 배정", size=9, colour=C["muted"], anchor="middle"))
    p.append(line(402, 121, 472, 121, colour=C["warn"], marker="w"))
    p.append(txt(437, 112, "State=DRAIN", size=9, colour=C["warn"], anchor="middle"))
    p.append(line(628, 121, 698, 121, colour=C["warn"], marker="w"))
    p.append(txt(663, 112, "작업 종료", size=9, colour=C["warn"], anchor="middle"))

    p.append(f'<path d="M 250 90 C 250 52, 176 52, 176 90" fill="none" stroke="{C["ink2"]}" '
             f'stroke-width="1.8" marker-end="url(#b)"/>')
    p.append(txt(213, 46, "작업이 끝난다", size=9, colour=C["muted"], anchor="middle"))

    p.append(f'<path d="M 777 152 C 777 228, 99 228, 99 152" fill="none" stroke="{C["accent"]}" '
             f'stroke-width="1.8" marker-end="url(#a)"/>')
    p.append(txt(438, 252, "State=RESUME · 점검이 끝나면 되돌린다", size=10, colour=C["accent"], anchor="middle"))

    p.append(box(250, 282, 150, 54, [strong("DOWN / FAIL", 12), small("응답이 없다", 9)],
                 fill=C["dangerBg"], stroke=C["danger"]))
    p.append(line(325, 152, 325, 280, colour=C["danger"], marker="r", width=1.5))
    p.append(txt(334, 178, "응답 없음 · 그 위의 작업은 죽는다", size=9, colour=C["danger"]))

    p.append(rule(24, 356, 876))
    p.append(txt(24, 378, "DRAIN 은 새 작업만 막고 돌던 작업은 끝까지 둔다. 즉시 비우는 명령이 아니라 기다림을 포함한다.", size=11))
    p.append(txt(24, 398, "sinfo -R 로 드레인 사유를 확인한다. 사유를 적어 두지 않으면 왜 뺐는지 아무도 모르게 된다.", size=11))
    write("node-states.svg", p)


if __name__ == "__main__":
    print("그림을 그린다")
    llm_io_traffic()
    training_io_timeline()
    rank_shard_map()
    slurm_k8s_split()
    node_move()
    memory_hierarchy()
    gpu_node_anatomy()
    node_states()
    print("끝")
