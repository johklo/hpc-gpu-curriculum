---
id: m2-operations
no: "02"
title: 클러스터 운영
subtitle: 노드 점검, 자원 관리, 모니터링
level: 핵심
---

운영자가 매일 만지는 것들을 다룬다. 노드 상태 점검에서 시작해 사용자 환경과 GPU 자원 관리,
모니터링까지 이어진다. 장애 상황에서 어디부터 보는지에 대한 순서를 만드는 것이 목표다.

## 노드 상태 점검

문제 신고가 들어오면 순서를 정해두고 본다. 부하, 프로세스, 메모리, 디스크, 네트워크 순이다.

```bash
uptime                      # 1·5·15분 부하 평균. 코어 수보다 크면 과부하다
top -b -n1 | head -20       # CPU를 먹는 프로세스 확인
ps aux --sort=-%mem | head  # 메모리를 먹는 프로세스 확인
systemctl --failed          # 실패한 서비스 목록
```

부하 평균은 코어 수와 비교해서 읽는다. 128코어 노드에서 부하 20은 한가한 상태고, 부하 300은
대기열이 쌓였다는 뜻이다. 부하가 높은데 CPU 사용률이 낮으면 I/O 대기를 의심한다. `top`의
`wa` 값이 그 단서다.

Slurm이 보는 상태와 실제 상태가 다를 수 있다. 노드가 `DRAIN`이면 이유부터 확인한다.

```bash
sinfo -R                              # 드레인된 노드와 사유를 한 번에 본다
scontrol show node gpu07 | grep -i reason
scontrol update NodeName=gpu07 State=RESUME   # 원인을 고친 뒤 복귀시킨다
```

## 메모리와 스토리지

메모리는 `free`의 `available` 열만 보면 된다. `free` 열은 캐시를 제외한 값이라 낮게 보이는
것이 정상이다.

```bash
free -g                     # available 열을 본다
vmstat 1 5                  # si/so가 0이 아니면 스왑이 일어나는 중이다
df -h /home /scratch        # 사용률과 남은 용량
df -i /home                 # inode 고갈. 작은 파일이 많으면 용량보다 먼저 찬다
du -sh /scratch/* | sort -h # 누가 얼마나 쓰는지
```

공유 스토리지에서 자주 겪는 문제는 용량이 아니라 inode 고갈과 메타데이터 부하다. 학습 데이터를
작은 파일 수백만 개로 두면 용량은 남아도 파일시스템이 느려진다. 이런 데이터는 묶음 포맷으로
바꾸는 편이 낫다.

I/O가 의심되면 장치별로 확인한다.

```bash
iostat -x 1 5               # %util이 100에 가까우면 포화 상태다
iotop -oPa                  # 실제로 I/O를 일으키는 프로세스
```

## 사용자와 실행 환경

계정은 보통 LDAP이나 AD로 중앙에서 관리한다. 노드마다 로컬 계정을 만들면 UID가 어긋나 공유
스토리지의 파일 소유권이 깨진다.

소프트웨어는 환경 모듈로 제공한다. 같은 라이브러리의 여러 버전을 충돌 없이 두기 위해서다.

```bash
module avail                # 설치된 모듈 목록
module load cuda/12.4 nccl/2.21
module list                 # 현재 적재된 모듈
module purge                # 전부 내린다. 작업 스크립트 첫 줄에 두면 재현성이 올라간다
```

작업 스크립트에서 `module purge`로 시작해 필요한 것만 적재하면 사용자의 셸 설정에 영향받지
않는다. 재현이 안 되는 작업을 조사할 때 이 부분을 먼저 본다.

## 로그와 1차 분류

로그는 세 군데를 본다. 커널, 시스템 데몬, 애플리케이션이다.

```bash
dmesg -T | tail -50                    # 커널. OOM, 하드웨어 오류, Xid가 여기 남는다
journalctl -u slurmd -n 100 --no-pager # 특정 서비스
journalctl -p err -S "1 hour ago"      # 최근 한 시간의 오류만
```

`dmesg`에서 `Out of memory: Killed process`가 보이면 커널이 프로세스를 죽인 것이다. 작업이
아무 메시지 없이 사라졌다는 신고의 상당수가 여기에 해당한다. `Xid`로 시작하는 줄이 보이면 GPU
문제이고, 모듈 07에서 다룬다.

작업 단위로는 Slurm의 기록을 본다.

```bash
sacct -j 12345 --format=JobID,State,ExitCode,MaxRSS,Elapsed
```

`ExitCode`가 `0:9`면 SIGKILL, `0:15`면 SIGTERM이다. 시간 초과로 스케줄러가 죽인 경우
`State`가 `TIMEOUT`으로 남는다. `MaxRSS`가 요청한 메모리에 근접했다면 메모리 부족을 의심한다.

## GPU 자원 관리

GPU 상태는 `nvidia-smi`로 본다. 사람이 읽는 화면보다 질의 형식이 자동화에 편하다.

```bash
nvidia-smi
nvidia-smi --query-gpu=index,name,memory.used,memory.total,utilization.gpu,temperature.gpu \
           --format=csv,noheader
nvidia-smi topo -m          # GPU 사이 연결 형태. NVLink 여부를 확인한다
```

사용률이 낮은데 학습이 느리면 GPU가 아니라 데이터 로더나 통신이 병목이다. 사용률과 메모리를
같이 보고 판단한다.

한 장을 여러 작업이 나눠 쓰게 하려면 분할 방식을 고른다.

| 방식 | 격리 수준 | 쓰임 |
| --- | --- | --- |
| MIG | 하드웨어 분할. 메모리와 연산이 완전히 격리된다 | 추론 서비스, 다중 사용자 공유 |
| MPS | 프로세스 공유. 격리는 약하다 | 작은 커널을 많이 띄우는 워크로드 |
| 시분할 | 스케줄러가 번갈아 배정한다 | 개발과 실험 환경 |

Slurm에서는 GPU를 GRES로 다룬다. `--gres=gpu:2`처럼 요청하면 `CUDA_VISIBLE_DEVICES`가 자동으로
설정되어 다른 GPU가 보이지 않는다. 사용자가 이 변수를 직접 덮어쓰면 격리가 깨지므로 작업
스크립트에서 손대지 않게 안내한다.

## 모니터링

노드에 들어가서 보는 방식은 노드가 늘면 유지되지 않는다. 지표를 모아두고 대시보드로 본다.

구성은 세 층이다. 수집기가 노드에서 지표를 뽑고, 시계열 DB가 저장하고, 대시보드가 보여준다.
GPU 지표는 DCGM Exporter가 담당한다.

| 지표 | 무엇을 알려주는가 |
| --- | --- |
| `DCGM_FI_DEV_GPU_UTIL` | GPU 사용률. 낮으면 병목이 GPU 밖에 있다 |
| `DCGM_FI_DEV_FB_USED` | GPU 메모리 사용량. OOM 예측에 쓴다 |
| `DCGM_FI_DEV_GPU_TEMP` | 온도. 스로틀링 판단의 근거다 |
| `DCGM_FI_DEV_POWER_USAGE` | 전력. 랙 단위 용량 계획에 쓴다 |
| `DCGM_FI_DEV_XID_ERRORS` | Xid 발생. 장애의 조기 신호다 |

경보는 적게 만든다. 사람이 즉시 행동해야 하는 것만 경보로 두고, 나머지는 대시보드에 둔다.
노드 다운, Xid 발생, 스토리지 사용률 90퍼센트 정도면 시작으로 충분하다.
