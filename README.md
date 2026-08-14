# HPC & GPU Engineering 학습 가이드

Slurm, Kubernetes, NVIDIA GPU, Linux 성능 튜닝 등 HPC/GPU 인프라 운영에 필요한 글을
**학습 순서대로 배열한 색인**입니다.

**사이트:** https://johklo.github.io/hpc-gpu-curriculum/

## 무엇인가

기존에 흩어져 있던 114편의 글을 7개 모듈로 묶고, 각 모듈에 학습 목표를 붙였습니다.
왼쪽 목차에서 모듈을 고르고, 오른쪽에서 그 모듈의 설명과 읽을 글 목록을 봅니다.

| 모듈 | 주제 | 글 |
| --- | --- | ---: |
| 01 | HPC 기초 — 클러스터 구조, Slurm 설치, MPI | 5 |
| 02 | 클러스터 운영 Zero to Hero — 일상 운영 전반 | 35 |
| 03 | Linux 성능 튜닝 Deep Dive — 커널·NUMA·I/O | 15 |
| 04 | 스케줄링 Deep Dive — 토폴로지·공정성·하이브리드 | 11 |
| 05 | ML 인프라 오케스트레이션 — Slurm vs Kubernetes | 8 |
| 06 | 인프라 용어 사전 — 34개 항목 | 35 |
| 07 | 하드웨어 점검과 장애 분석 — PCIe·Xid·DCGM | 5 |

## 저작권

이 저장소는 **색인과 학습 안내만** 담습니다. 원문 본문은 복제하지 않았고, 모든 항목은
원문으로 연결됩니다. 모듈 설명과 학습 목표는 직접 작성했습니다.
글의 저작권은 원저자에게 있습니다 — 출처: [ygtoken.tistory.com](https://ygtoken.tistory.com/)

## 빌드

```bash
python build.py      # curriculum.json + _modules.json -> site/
```

의존성은 없습니다. 파이썬 표준 라이브러리만 사용합니다.

| 파일 | 역할 |
| --- | --- |
| `curriculum.json` | 모듈 정의: 제목, 설명, 학습 목표 |
| `_modules.json` | 모듈별 글 목록 (제목·URL·날짜) |
| `build.py` | 정적 사이트 생성기 |
| `assets/` | 스타일시트, 디자인 토큰, 스크립트 |
