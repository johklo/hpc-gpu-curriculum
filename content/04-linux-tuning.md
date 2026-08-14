---
id: m3-linux
no: "04"
title: Linux 성능 튜닝
subtitle: NUMA, 메모리, I/O, 네트워크
level: 심화
---

같은 하드웨어인데 성능이 다르게 나오는 일이 있다. 커널 기본값은 범용 서버를 전제로 잡혀 있어
HPC 워크로드와 어긋나는 지점이 몇 군데 있고, 그 지점을 하나씩 짚는다.

## NUMA와 프로세스 배치

소켓이 둘 이상인 서버는 메모리가 소켓마다 붙어 있다. 다른 소켓에 붙은 메모리를 읽으면 지연이
늘고 대역폭이 준다. GPU와 NIC도 특정 소켓에 연결되어 있어, 프로세스를 어디에 두느냐가 성능을
바꾼다.

```bash
lscpu | grep -i numa         # 노드 수와 코어 배치
numactl --hardware           # 노드별 메모리 용량과 노드 간 거리
nvidia-smi topo -m           # GPU와 NIC이 어느 노드에 붙었는지
```

`numactl --hardware`의 거리 행렬에서 로컬은 보통 10, 원격은 20 이상이다. 이 값이 실제 지연
비율의 근사치다.

![CPU와 메모리, GPU, NIC이 소켓마다 붙어 있고 소켓을 넘는 접근은 지연이 커진다](img/numa-topology.svg)

배치를 고정하는 방법은 둘이다.

```bash
# 프로세스를 NUMA 노드 0에 묶고 메모리도 거기서만 할당한다
numactl --cpunodebind=0 --membind=0 ./app

# Slurm에서 GPU와 가까운 코어에 자동으로 묶는다
srun --gpus-per-task=1 --cpu-bind=verbose,cores ./app
```

GPU 8장 노드에서 프로세스 8개를 띄울 때, 각 프로세스를 담당 GPU와 같은 소켓에 묶으면 데이터
전송 구간에서 차이가 난다. `--cpu-bind=verbose`를 붙이면 실제 어디에 묶였는지 로그로 확인할 수
있다.

## 메모리 설정

투명 대용량 페이지는 기본으로 켜져 있고, 대개 도움이 되지만 지연에 민감한 워크로드에서는
페이지 병합 과정이 튀는 원인이 된다.

```bash
cat /sys/kernel/mm/transparent_hugepage/enabled   # [always] madvise never
echo madvise > /sys/kernel/mm/transparent_hugepage/enabled
```

`always`는 커널이 알아서 병합하고, `madvise`는 프로그램이 요청한 영역에만 적용한다. 지연이
중요한 곳은 `madvise`가 무난하다.

스왑은 계산 노드에서 사실상 재앙이다. 학습 프로세스가 스왑에 걸리면 성능이 수십 배 떨어지므로,
차라리 OOM으로 죽는 편이 낫다.

```bash
sysctl vm.swappiness         # 계산 노드는 1 또는 0으로 둔다
sysctl vm.overcommit_memory  # 0이 기본. 2로 두면 과할당을 막지만 부작용이 있다
```

페이지 캐시는 비워야 할 대상이 아니다. 벤치마크 재현성을 위해 비우는 경우에만
`echo 3 > /proc/sys/vm/drop_caches`를 쓰고, 운영 중에는 손대지 않는다.

## I/O 스케줄러와 파일시스템

NVMe는 큐가 깊고 자체적으로 재배치를 하므로 커널 스케줄러가 개입할 여지가 적다. 대부분
`none`이 가장 좋다.

```bash
cat /sys/block/nvme0n1/queue/scheduler    # [none] mq-deadline kyber
echo none > /sys/block/nvme0n1/queue/scheduler
```

| 장치 | 권장 | 이유 |
| --- | --- | --- |
| NVMe SSD | `none` | 장치가 이미 병렬 처리한다. 커널 개입이 오히려 지연을 만든다 |
| SATA SSD | `mq-deadline` | 가벼운 정렬로 충분하다 |
| HDD | `mq-deadline` 또는 `bfq` | 탐색 시간이 커서 정렬 효과가 크다 |

마운트 옵션에서는 `noatime`이 효과가 확실하다. 읽기만 해도 접근 시각을 쓰느라 메타데이터 갱신이
발생하는데, 파일을 대량으로 읽는 워크로드에서 이 비용이 무시할 수 없다.

```
/dev/nvme0n1 /scratch xfs defaults,noatime,nodiratime 0 0
```

병렬 파일시스템은 성격이 다르다. Lustre는 파일을 여러 OST에 나눠 저장하는데, 큰 파일을 쓸 때는
스트라이프를 늘려야 대역폭이 나온다.

```bash
lfs getstripe /scratch/dataset
lfs setstripe -c 8 /scratch/bigfiles     # 스트라이프 8개로 분산한다
```

작은 파일에 스트라이프를 늘리면 오히려 손해다. 큰 파일이 놓일 디렉터리에만 적용한다.

## 네트워크

분산 학습에서 노드 간 통신은 대개 InfiniBand나 RoCE를 쓴다. 상태 확인이 먼저다.

```bash
ibstat                      # 포트 상태와 링크 속도
ibv_devinfo                 # 장치별 상세
ib_write_bw -d mlx5_0       # 대역폭 측정. 상대 노드에서 서버 모드로 함께 띄운다
```

`ibstat`의 `Rate`가 규격보다 낮으면 케이블이나 트랜시버를 의심한다. 링크가 절반 속도로 붙는
경우가 드물지 않고, 성능 저하 신고의 원인이 되곤 한다.

이더넷 구간에서는 MTU를 맞춘다. 경로 위 모든 장비가 같은 값이어야 하고, 한 곳이라도 작으면
단편화가 일어나 오히려 느려진다.

```bash
ip link show eth0 | grep mtu
ping -M do -s 8972 <상대노드>    # 9000 MTU 확인. 헤더 28바이트를 뺀 값이다
```

NCCL은 환경 변수로 경로를 통제한다. 디버깅에는 이 둘이 쓸모 있다.

```bash
export NCCL_DEBUG=INFO          # 어떤 경로를 골랐는지 로그로 남긴다
export NCCL_IB_HCA=mlx5_0,mlx5_1  # 쓸 HCA를 지정한다
```

`NCCL_DEBUG=INFO` 로그에서 통신 경로가 `NET/Socket`으로 잡혔다면 InfiniBand를 못 쓰고 TCP로
돌고 있다는 뜻이다. 성능이 기대의 몇 분의 일로 떨어진다.

## CPU 주파수와 절전

기본 배포판은 전력을 아끼는 쪽으로 설정되어 있다. 계산 노드에서는 이 설정이 지연을 만든다.
부하가 걸릴 때까지 클럭이 낮게 유지되고, 깊은 절전 상태에서 깨어나는 데 시간이 걸린다.

```bash
cpupower frequency-info                       # 현재 거버너와 클럭 범위
cpupower frequency-set -g performance         # 모든 코어를 성능 모드로
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
turbostat --interval 5                        # 실제 클럭과 C-state 체류 시간
```

`turbostat`의 `Busy%`가 낮은데 성능이 안 나오면 클럭이 안 올라간 것이고, `CPU%c6`가 크면 깊은
절전에 자주 들어간다는 뜻이다. 지연에 민감한 워크로드는 절전 깊이를 제한한다.

```bash
# 부팅 파라미터로 깊은 절전을 막는다
intel_idle.max_cstate=1 processor.max_cstate=1
```

전력 비용과 맞바꾸는 결정이라 노드 성격에 따라 다르게 둔다. 상시 학습이 도는 GPU 노드는 성능
모드가 맞고, 유휴 시간이 긴 노드는 굳이 그럴 필요가 없다.

## 인터럽트 배치

네트워크 카드는 패킷을 받을 때마다 인터럽트를 건다. 이 처리가 특정 코어에 몰리면 그 코어가
포화되어 전체 처리량이 떨어진다. 계산 스레드가 도는 코어와 겹치면 계산도 함께 방해받는다.

```bash
cat /proc/interrupts | grep mlx               # 인터럽트가 어느 코어로 가는지
systemctl status irqbalance                   # 자동 분배 데몬
cat /sys/class/net/eth0/device/numa_node      # NIC 이 붙은 NUMA 노드
```

원칙은 두 가지다. NIC 인터럽트는 그 NIC이 붙은 NUMA 노드의 코어로 보내고, 계산에 쓰는 코어와
겹치지 않게 한다. 노드를 넘어가면 인터럽트 처리마다 원격 메모리 접근이 생긴다.

```bash
# 특정 인터럽트를 특정 코어에 고정한다
echo 2 > /proc/irq/128/smp_affinity_list

# 계산 코어를 커널 작업에서 떼어 놓는다 (부팅 파라미터)
isolcpus=8-63 nohz_full=8-63 rcu_nocbs=8-63
```

`isolcpus`는 강한 도구다. 격리한 코어에는 스케줄러가 아무것도 올리지 않으므로, 그 코어를 쓰는
프로세스를 명시적으로 배치해야 한다. 설정만 하고 배치를 안 하면 코어가 통째로 논다.

## 쓰기 버퍼와 I/O 폭발

체크포인트처럼 짧은 시간에 대량으로 쓰는 워크로드는 커널의 쓰기 버퍼 설정에 영향을 받는다.
버퍼가 가득 차면 쓰기가 동기로 바뀌면서 프로세스가 멈춘다.

```bash
sysctl vm.dirty_ratio               # 이 비율을 넘으면 쓰는 쪽이 직접 내려쓴다
sysctl vm.dirty_background_ratio    # 이 비율부터 백그라운드로 내려쓰기 시작
sysctl vm.dirty_expire_centisecs    # 얼마나 오래된 데이터부터 내려쓸지
```

기본값은 메모리의 20퍼센트와 10퍼센트다. 메모리가 1TB인 노드라면 200GB까지 버퍼에 쌓였다가
한꺼번에 내려간다. 이 순간 다른 I/O가 전부 밀린다. 값을 낮추면 조금씩 꾸준히 내려가 지연이
고르게 퍼진다.

```bash
sysctl -w vm.dirty_background_ratio=3
sysctl -w vm.dirty_ratio=10
```

## 튜닝 프로파일

항목을 하나씩 만지는 대신 묶음으로 적용하는 방법도 있다. 배포판이 제공하는 프로파일은 위에서
다룬 항목 상당수를 한 번에 설정한다.

```bash
tuned-adm list                       # 사용 가능한 프로파일
tuned-adm active                     # 현재 적용된 것
tuned-adm profile hpc-compute        # 계산 노드용
tuned-adm profile latency-performance
```

프로파일을 먼저 적용하고 필요한 항목만 덧붙이는 순서가 실수가 적다. 무엇이 바뀌는지는 프로파일
정의 파일에서 확인할 수 있다.

```bash
cat /usr/lib/tuned/hpc-compute/tuned.conf
```

## 바꾸기 전과 후를 비교

설정을 바꿨으면 효과를 재야 한다. 재현 가능한 부하로 같은 조건에서 비교한다.

```bash
# 메모리 대역폭
mpirun -np 64 stream_mpi

# 지연
perf bench sched pipe

# 종합
sar -u -r -d -n DEV 1 60 > baseline.txt
```

값이 좋아지지 않았다면 되돌린다. 설정을 쌓아 두기만 하면 나중에 문제가 생겼을 때 무엇이
원인인지 가릴 수 없다. 바꾼 항목과 이유, 측정값을 한곳에 기록해 두는 편이 낫다.

## 다수 노드에 명령 실행

노드가 수십 대면 한 대씩 SSH로 들어가는 방식은 유지되지 않는다. 병렬 실행 도구를 쓴다.

```bash
pdsh -w gpu[01-16] uptime
pdsh -w gpu[01-16] 'nvidia-smi --query-gpu=index,temperature.gpu --format=csv,noheader' | dshbak -c
```

`dshbak -c`는 출력이 같은 노드를 묶어서 보여준다. 16대 중 15대가 같고 1대만 다르면 그 1대가
바로 눈에 띈다. 점검 스크립트를 돌릴 때 이 조합이 편하다.

Slurm이 있으면 할당된 노드에만 실행하는 방법도 있다.

```bash
srun --nodes=16 --ntasks-per-node=1 hostname
```

명령을 배포하기 전에 대상 목록을 먼저 확인하는 습관이 필요하다. 범위를 잘못 적어 전체 노드에
파괴적인 명령을 보내는 사고가 실제로 일어난다.
