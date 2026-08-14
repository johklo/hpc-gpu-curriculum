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

NUMA(Non-Uniform Memory Access, 비균일 메모리 접근)는 CPU가 어느 메모리에 접근하느냐에 따라
속도가 달라지는 구조다. 소켓(socket)은 물리 CPU 하나를 꽂는 자리이고, 큰 서버는 소켓을 둘
이상 둔다.

소켓이 둘 이상인 서버는 메모리가 소켓마다 붙어 있다. 다른 소켓에 붙은 메모리를 읽으면 지연이
늘고 대역폭이 준다. GPU와 NIC도 특정 소켓에 연결되어 있어, 프로세스를 어디에 두느냐가 성능을
바꾼다.

```bash
lscpu | grep -i numa         # 노드 수와 코어 배치
numactl --hardware           # 노드별 메모리 용량과 노드 간 거리
nvidia-smi topo -m           # GPU와 NIC이 어느 노드에 붙었는지
```

`numactl --hardware`의 출력은 이렇게 읽는다.

```
available: 2 nodes (0-1)
node 0 cpus: 0 1 2 ... 63
node 0 size: 515000 MB
node 1 cpus: 64 65 ... 127
node 1 size: 515000 MB
node distances:
node   0   1
  0:  10  21
  1:  21  10
```

`node 0`에 코어 0–63과 약 515GB 메모리가 붙어 있고, `node 1`에 나머지가 붙어 있다는 뜻이다.
거리 행렬에서 대각선(자기 자신)은 10이고 노드 0에서 노드 1로 가는 값은 21이다. 노드 0의 코어가
노드 1의 메모리를 읽으면 약 2배 느리다는 근사치다. 프로세스가 쓰는 메모리와 코어를 같은 노드에
두는 것이 목표다.

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

## 리눅스가 프로세스를 고르는 방식

코어 하나에서 돌 수 있는 프로세스가 여럿이면 커널이 순서를 정한다. 이 결정을 내리는 것이
스케줄러이고, 리눅스 기본 스케줄러는 CFS(Completely Fair Scheduler, 완전 공정 스케줄러)다.
이름대로 모든 프로세스에 CPU 시간을 고르게 나누는 것을 목표로 잡는다.

CFS는 프로세스마다 vruntime(virtual runtime, 가상 실행 시간)이라는 값을 들고 있다. 프로세스가
CPU를 쓴 만큼 이 값이 올라가고, 스케줄러는 vruntime이 가장 작은 프로세스를 다음에 올린다. 적게
쓴 쪽부터 주니 시간이 고르게 퍼진다. nice 값은 이 vruntime이 올라가는 속도를 바꾼다. nice가 낮은
프로세스는 같은 시간을 써도 vruntime이 천천히 올라 더 자주 선택된다. nice는 우선순위 숫자를 직접
지정하는 값이 아니라 가중치(weight)를 정하는 값이고, 한 단계 차이가 대략 1.25배의 CPU 몫으로
이어진다. -20에서 +19까지 있고, 값이 작을수록 몫이 크다.

CFS로 관리되는 일반 정책이 SCHED_OTHER다. 이와 달리 실시간 정책은 vruntime을 따지지 않고
우선순위가 높은 쪽이 CPU를 계속 쥔다.

| 정책 | 성격 | 쓰는 곳 |
| --- | --- | --- |
| `SCHED_OTHER` | CFS가 관리하는 일반 정책, 공정 분배 | 대부분의 프로세스 |
| `SCHED_BATCH` | 대화형이 아님을 알려 전환을 줄인다 | 배치 계산 |
| `SCHED_IDLE` | 남는 시간에만 돈다 | 최하 우선순위 백그라운드 |
| `SCHED_FIFO` | 실시간, 스스로 놓기 전까지 안 뺏긴다 | 지연이 치명적인 소수 스레드 |
| `SCHED_RR` | 실시간, 같은 우선순위끼리 타임슬라이스로 번갈아 | 위와 같으나 여럿일 때 |

정책과 우선순위는 `chrt`로 바꾸고, 코어 묶기는 `taskset`으로 한다.

```bash
chrt -f 50 ./low_latency_app        # SCHED_FIFO 우선순위 50으로 실행한다
chrt -p $(pgrep trainer)            # 프로세스의 현재 정책과 우선순위를 본다
taskset -c 8-15 ./trainer           # 코어 8~15에만 묶는다
taskset -pc $(pgrep dataloader)     # 어느 코어에 묶였는지 본다
```

실시간 정책은 강한 도구라 잘못 쓰면 SCHED_FIFO 프로세스가 무한 루프에 빠졌을 때 그 코어의 다른
작업이 통째로 굶는다. 커널은 이를 막으려고 실시간 대역폭 한도(`kernel.sched_rt_runtime_us`)를 두는데,
계산 노드에서 실시간 정책을 쓸 때는 이 한도와 대상 코어를 함께 정해야 한다.

HPC 워크로드에서 기본값이 어긋나는 지점은 타임슬라이스와 이주(migration)에 있다. CFS는 응답성을
위해 프로세스를 자주 번갈아 올리고, 부하가 한쪽으로 쏠리면 프로세스를 다른 코어로 옮긴다. 대화형
데스크톱에는 맞지만, MPI 집합 통신처럼 모든 랭크가 같은 지점에서 만나야 하는 작업에는 독이 된다.
한 랭크의 계산 스레드가 잠깐 밀려 늦게 배리어에 도착하면 나머지 전부가 그 랭크를 기다린다. 잦은
전환과 이주는 캐시도 식혀 계산 자체를 느리게 만든다.

두 값으로 이 동작을 눅인다. `sched_min_granularity_ns`는 한 프로세스가 최소로 쥐고 있는 시간이라,
키우면 전환이 줄어든다. `sched_migration_cost_ns`는 이 시간 안에 돈 작업은 캐시가 뜨겁다고 보고
다른 코어로 옮기지 않는 문턱이라, 키우면 이주가 줄어든다.

```bash
# 오래된 커널에서는 sysctl로 보이고 조정한다
sysctl kernel.sched_min_granularity_ns
sysctl kernel.sched_migration_cost_ns
sysctl -w kernel.sched_min_granularity_ns=10000000   # 10ms
sysctl -w kernel.sched_migration_cost_ns=5000000     # 5ms
# 최근 커널은 이 값을 debugfs로 옮겼다
cat /sys/kernel/debug/sched/min_granularity_ns
```

데이터 로더와 학습 프로세스의 우선순위를 나누는 것이 실제로 효과가 큰 예다. 학습 주 프로세스는
GPU에 커널을 밀어 넣고 통신을 담당하므로 잠깐이라도 밀리면 GPU가 논다. 로더 워커는 CPU를 많이
쓰지만 잠깐 늦어도 큐가 흡수한다. 그래서 학습 프로세스는 우선순위를 올려 통신 스레드가 밀리지
않게 하고, 로더 워커는 계산 코어와 겹치지 않는 코어에 묶는다.

```bash
# 학습 주 프로세스는 통신 스레드가 밀리지 않게 우선순위를 올린다
nice -n -5 taskset -c 0-7 python train.py &
# 로더 워커는 남은 코어에 묶어 통신 코어를 건드리지 않게 한다
taskset -c 8-31 python -m data.serve &
chrt -p $(pgrep -f train.py)        # 의도한 정책이 걸렸는지 확인한다
```

코어를 나눌 때는 앞의 NUMA 배치와 함께 본다. 통신 코어를 NIC이 붙은 NUMA 노드에 두고, 로더
워커를 다른 노드에 두면 인터럽트와 계산이 서로를 밀어내지 않는다. 우선순위만 바꾸고 코어 배치를
안 맞추면 효과가 반감된다.

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

## HugePages

프로세스가 쓰는 주소는 가상 주소라, 실제 물리 메모리 주소로 바꾸는 변환이 매 접근마다 일어난다.
이 대응표가 페이지 테이블(page table)이다. 메모리를 페이지라는 고정 크기 조각으로 끊어 관리하는데,
기본 페이지는 4KB다. 페이지 테이블을 매번 뒤지면 느리므로, CPU 안에 최근 변환 결과를 담아 두는
작은 캐시가 있다. 이것이 TLB(Translation Lookaside Buffer, 변환 색인 버퍼)다. 접근하려는 주소의
변환이 TLB에 있으면 바로 물리 주소를 얻고, 없으면(TLB 미스) 페이지 테이블을 뒤지는 느린 경로로
빠진다.

4KB 페이지로 큰 메모리를 다루면 TLB 미스가 늘어난다. TLB가 담을 수 있는 항목 수는 수백에서 수천
사이로 정해져 있는데, 페이지 하나가 4KB이니 항목 수천 개를 다 채워도 겨우 수십 MB만 덮는다. 수십
GB를 오가는 학습 프로세스는 접근 주소가 TLB 범위를 금방 벗어나 미스가 잦아지고, 그때마다 페이지
테이블을 뒤지는 비용이 쌓인다. 페이지를 크게 만들면 항목 하나가 덮는 범위가 넓어져 같은 TLB로
훨씬 큰 메모리를 덮는다. 2MB 대용량 페이지 하나는 4KB 페이지 512개를 대신한다.

대용량 페이지를 쓰는 방식은 둘이다.

| 방식 | 성격 | 특징 |
| --- | --- | --- |
| 정적 HugePages | 부팅이나 실행 중에 미리 예약한 풀 | 크기가 고정되고 예측 가능, 애플리케이션이 명시적으로 요청 |
| 투명 HugePages(THP) | 커널이 자동으로 4KB를 2MB로 병합 | 코드 수정 없이 적용, 병합·분해가 뒤에서 일어남 |

정적 HugePages는 관리자가 풀을 잡아 두고, 애플리케이션이 그 풀에서 받아 쓴다.

```bash
grep Huge /proc/meminfo                 # 현재 대용량 페이지 상태
cat /proc/sys/vm/nr_hugepages           # 예약된 2MB 페이지 수
sysctl -w vm.nr_hugepages=8192          # 2MB 8192개 = 16GB 예약
# 1GB 페이지는 부팅 파라미터로 잡는다
# default_hugepagesz=1G hugepagesz=1G hugepages=32
```

THP는 커널이 알아서 병합하므로 코드를 바꿀 필요가 없지만, 병합과 분해가 뒤에서 일어난다는 점이
지연을 튀게 만든다. 큰 영역을 병합하는 khugepaged 작업이나, 조각난 메모리에서 연속 2MB를 확보하려
compaction이 도는 순간 프로세스가 수 밀리초에서 수십 밀리초씩 멈춘다. 처리량만 보는 워크로드에는
이 지연이 묻히지만, 매 스텝 시간이 고르게 나와야 하는 학습이나 지연이 목표인 추론에서는 이 순간의
튐이 문제가 된다.

GPU 워크로드에서 THP를 끄는 판단은 이 튐과 이득을 견줘 내린다. 핀 메모리처럼 이미 큰 영역을
연속으로 잡아 쓰는 경우 THP가 주는 이득이 작고, 대신 compaction 지연이 스텝 시간에 얼룩을 남긴다.
지연이 튀는 증상이 보이면 `madvise`로 바꿔 요청한 영역에만 적용하거나 아예 끈다.

```bash
cat /sys/kernel/mm/transparent_hugepage/enabled     # [always] madvise never
echo never > /sys/kernel/mm/transparent_hugepage/enabled
cat /sys/kernel/mm/transparent_hugepage/defrag       # 병합 시 compaction 정책
echo madvise > /sys/kernel/mm/transparent_hugepage/defrag
```

정적 HugePages 할당이 실패하는 원인은 대개 메모리 조각화다. 부팅 직후에는 연속 메모리가 넉넉해
풀이 잡히지만, 오래 돌아 메모리가 조각나면 연속 2MB나 1GB를 못 찾아 요청한 수보다 적게 잡힌다.
확인은 예약 요청과 실제 확보를 견줘 본다.

```bash
# 요청한 수와 실제 잡힌 수를 견준다
grep -E "HugePages_Total|HugePages_Free|HugePages_Rsvd" /proc/meminfo
cat /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages
cat /sys/kernel/mm/hugepages/hugepages-2048kB/free_hugepages
# 노드별로 나눠 본다
numastat -m | grep -i huge
```

`HugePages_Total`이 요청보다 작으면 그만큼 확보에 실패한 것이라, 1GB 페이지는 부팅 파라미터로
잡아 조각화 전에 확보하는 편이 안전하다. 애플리케이션이 대용량 페이지를 못 받으면 조용히 4KB로
떨어져 도는 경우가 있어, 성능이 안 나올 때 이 값을 확인해 실제로 대용량 페이지가 쓰이는지 본다.

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

`vm.dirty_background_ratio`는 백그라운드로 내려쓰기를 시작하는 문턱이고, `vm.dirty_ratio`는 쓰는
쪽을 붙잡아 직접 내려쓰게 만드는 문턱이다. 앞의 값을 넘으면 커널이 조용히 뒤에서 내려쓰기
시작하고, 뒤의 값을 넘으면 쓰던 프로세스가 멈춘 채 버퍼가 빌 때까지 기다린다. 대용량 체크포인트가
바로 이 뒤 문턱을 넘겨 학습이 몇 초씩 정지하는 원인이다.

효과는 값으로 확인한다. 체크포인트를 쓰는 동안 `/proc/meminfo`의 `Dirty`와 `Writeback`을 지켜본다.
`Dirty`는 아직 안 내려간 데이터, `Writeback`은 지금 내려가는 중인 데이터다.

```bash
grep -E "Dirty|Writeback" /proc/meminfo   # 값이 치솟았다가 한꺼번에 빠지는지 본다
watch -n1 'grep -E "Dirty|Writeback" /proc/meminfo'
```

```bash
sysctl vm.dirty_ratio               # 이 비율을 넘으면 쓰는 쪽이 직접 내려쓴다
sysctl vm.dirty_background_ratio    # 이 비율부터 백그라운드로 내려쓰기 시작
sysctl -w vm.dirty_background_ratio=3
sysctl -w vm.dirty_ratio=10
# 되돌리기: sysctl -w vm.dirty_background_ratio=10; sysctl -w vm.dirty_ratio=20
```

메모리가 큰 노드에서는 비율 대신 절대량으로 두는 편이 예측하기 쉽다. `vm.dirty_bytes`와
`vm.dirty_background_bytes`를 쓰면 메모리 크기와 무관하게 상한이 고정된다. 권장값은 워크로드가
정하지만, 버퍼가 한 번에 내려가며 멈추는 증상이 보이면 문턱을 낮춰 조금씩 자주 내려가게 만드는
방향이 맞다.

## GPU 노드에서 특히 문제가 되는 설정

위 항목들이 GPU 학습에서 왜 문제가 되는지는 GPU가 메모리와 네트워크를 쓰는 방식과 연결된다.

**페이지 잠금 메모리(page-locked memory).** GPU로 데이터를 보낼 때 CPU 메모리가 디스크로 밀려나지
않도록 고정한 영역을 쓴다. 이걸 핀 메모리(pinned memory)라고 부른다. 데이터 로더가
`pin_memory=True`로 이 영역을 많이 잡는데, 고정된 메모리는 스왑 대상이 아니라서 스왑을 켜 둔
노드에서도 이 부분은 물리 메모리를 계속 차지한다. 한도가 낮으면 고정에 실패한다.

```bash
ulimit -l                          # 잠글 수 있는 메모리 한도(KB). unlimited 여야 안전하다
grep memlock /etc/security/limits.conf
# 되돌리기: limits.conf 의 해당 줄을 원래대로 두고 다시 로그인한다
```

**GPUDirect.** GPU가 CPU를 거치지 않고 NIC이나 다른 GPU와 직접 데이터를 주고받는 기능이다.
GPUDirect RDMA는 네트워크 카드가 GPU 메모리를 바로 읽고, GPUDirect Storage는 저장장치가 GPU
메모리로 바로 넣는다. CPU를 거치는 복사가 사라져 대역폭이 오르고 지연이 준다. 이 경로는 NIC과
GPU가 같은 PCIe 스위치 아래, 같은 NUMA 노드에 있을 때 가장 잘 나온다. 앞의 NUMA 배치가 GPU
노드에서 특히 중요한 까닭이다.

**`vm.max_map_count`.** 한 프로세스가 가질 수 있는 메모리 매핑 영역의 최대 개수다. 기본값
65530은 큰 학습 프레임워크나 여러 GPU를 쓰는 프로세스에 부족할 때가 있고, 넘으면
`Cannot allocate memory`나 매핑 실패로 죽는다.

```bash
sysctl vm.max_map_count             # 기본 65530
sysctl -w vm.max_map_count=1048576  # 운영 중 바로 적용, 위험 낮음
# 되돌리기: sysctl -w vm.max_map_count=65530
```

## 설정별 위험도

설정을 바꾸기 전에 되돌리기가 얼마나 쉬운지 알아야 한다. 운영 중에 바꿔도 되는 것과 재부팅이
필요한 것, 잘못 두면 노드가 안 뜨는 것을 구분한다.

| 설정 | 되돌리기 | 위험도 |
| --- | --- | --- |
| `vm.swappiness`, `vm.dirty_ratio` | `sysctl -w`로 즉시 | 낮음. 운영 중 조정 가능 |
| I/O 스케줄러 | sysfs에 다시 써서 즉시 | 낮음 |
| CPU 거버너 | `cpupower`로 즉시 | 낮음 |
| THP 설정 | sysfs에 다시 써서 즉시 | 낮음 |
| 인터럽트 affinity | 값 되돌리면 즉시 | 중간. 잘못 묶으면 처리량이 준다 |
| `vm.max_map_count` | `sysctl -w`로 즉시 | 낮음 |
| `isolcpus`, `nohz_full` | 부팅 파라미터 수정 후 재부팅 | 높음. 배치를 안 하면 코어가 논다 |
| C-state 제한 | 부팅 파라미터 수정 후 재부팅 | 중간. 전력이 오른다 |
| 마운트 옵션 | fstab 수정 후 재마운트 | 중간. 오타면 부팅이 막힐 수 있다 |

`sysctl -w`로 바꾼 값은 재부팅하면 사라진다. 재부팅 후에도 유지하려면 `/etc/sysctl.d/`에
파일로 남긴다. 부팅 파라미터(`isolcpus` 등)는 잘못 적으면 노드가 정상적으로 뜨지 않으므로, 한
대에서 재부팅까지 확인한 뒤 나머지에 배포한다.

```bash
echo 'vm.max_map_count=1048576' > /etc/sysctl.d/90-hpc.conf
sysctl --system                     # sysctl.d 파일을 다시 읽어 적용한다
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

프로파일이 무엇을 바꾸는지 모른 채 적용하면, 나중에 문제가 생겼을 때 원인을 가릴 수 없다.
`tuned.conf`를 열어 어떤 `sysctl` 값과 거버너, 디스크 설정이 들어 있는지 확인하고 적용한다. 예를
들어 `latency-performance`는 CPU 거버너를 `performance`로 두고 C-state를 얕게 제한하며 THP를
조정한다. `hpc-compute`는 여기에 네트워크 버퍼와 커널 스케줄러 설정을 더한다.

```bash
tuned-adm verify                     # 적용값이 실제 설정과 일치하는지 검사한다
tuned-adm off                        # 프로파일을 걷어 기본값으로 되돌린다
```

`tuned-adm verify`는 프로파일이 지정한 값이 실제로 걸려 있는지 확인한다. 다른 스크립트나 사람이
값을 덮어썼으면 여기서 어긋남이 드러난다. 프로파일과 수동 설정을 섞으면 이 검사가 실패하므로,
프로파일로 큰 틀을 잡고 정말 필요한 몇 개만 `/etc/sysctl.d/`로 덧붙이는 방식이 관리하기 쉽다.
노드 종류마다 다른 프로파일이 필요하면 이름을 붙여 관리하고, 어느 노드에 무엇이 걸렸는지
목록으로 유지한다.

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

비교에는 규칙이 있다. 한 번에 한 항목만 바꾼다. 두 개를 같이 바꾸고 좋아지면 어느 쪽이
기여했는지 알 수 없다. 같은 부하를 최소 세 번 돌려 중앙값을 쓴다. 한 번의 측정은 캐시 상태나
이웃 작업 때문에 튄다. 바꾸기 전 값을 baseline으로 저장해 두고, 바꾼 뒤 같은 명령으로 재서
나란히 놓는다.

```bash
# 바꾸기 전
sar -u -r -d -n DEV 1 60 > before.txt
# 설정 변경 후 동일 부하로
sar -u -r -d -n DEV 1 60 > after.txt
sdiff before.txt after.txt | less    # 열을 나란히 놓고 차이를 본다
```

측정할 지표는 워크로드에 맞춘다. 메모리 대역폭이 중요한 학습은 STREAM 수치를, 통신이 중요한
분산 학습은 `ib_write_bw`와 NCCL 벤치마크를 본다. 실제 학습의 스텝 시간을 재는 것이 가장
정확하다. 합성 벤치마크가 좋아져도 학습이 안 빨라지면 그 튜닝은 이 워크로드에 의미가 없다. 바꾼
항목과 날짜, 이유, 측정값을 노드 종류별로 한 표에 남기면, 몇 달 뒤 성능이 달라졌을 때 무엇을
건드렸는지 되짚을 수 있다.

## perf와 eBPF로 커널 안을 보기

성능이 안 나오는데 원인이 코드 밖에 있을 때가 있다. 캐시 미스, 커널 대기, 디스크 지연 같은 것은
애플리케이션 로그로는 안 보인다. `perf`와 eBPF는 커널이 이미 세고 있는 값을 꺼내 이 안쪽을
들여다보는 도구다.

`perf`는 CPU가 내장한 성능 카운터(PMC)와 커널 이벤트를 읽는다. 쓰임에 따라 세 하위 명령을 갈라
쓴다.

| 명령 | 무엇을 하는가 | 언제 쓰는가 |
| --- | --- | --- |
| `perf top` | 지금 CPU를 많이 먹는 함수를 실시간으로 | 어디가 뜨거운지 즉석에서 볼 때 |
| `perf record`/`report` | 일정 시간 표본을 모아 나중에 분석 | 프로파일을 남겨 파고들 때 |
| `perf stat` | 정해진 카운터의 총량을 센다 | 캐시 미스·분기 실패 비율을 잴 때 |

`perf stat`은 프로그램을 감싸 돌리면 그동안의 카운터를 모아 준다.

```bash
perf stat -d ./trainer                  # 캐시·분기 카운터를 함께 낸다
perf stat -e cache-misses,cache-references,branch-misses,branches ./trainer
perf top                                # 지금 뜨거운 함수를 실시간으로 본다
perf record -g -- ./trainer             # 콜 그래프까지 표본을 모은다
perf report                             # 모은 표본을 함수별로 정렬해 본다
```

읽는 법은 비율로 본다. `cache-misses`를 `cache-references`로 나누면 캐시 미스율이 나오고, 이 값이
높으면 메모리 접근 패턴이 캐시에 안 맞는다는 뜻이라 NUMA 원격 접근이나 자료구조 배치를 의심한다.
`branch-misses`를 `branches`로 나눈 분기 예측 실패율이 높으면 조건 분기가 불규칙해 CPU가 앞질러
실행한 것을 자주 버린다는 뜻이다. 절대 개수보다 이 두 비율이 판단 기준이다.

eBPF는 커널 안에서 도는 작은 프로그램을 안전하게 붙이는 장치다. 커널을 다시 빌드하거나 모듈을
올리지 않고, 특정 이벤트가 일어날 때 값을 세거나 기록하는 코드를 커널에 끼워 넣는다. 검증기가
올리기 전에 프로그램이 무한 루프에 빠지거나 잘못된 메모리를 건드리지 않는지 확인해서, 운영 중인
커널에 붙여도 커널이 죽지 않는다. bcc와 bpftrace가 이 위에서 도는 도구 모음이다.

| 도구 | 무엇을 보여주는가 |
| --- | --- |
| `biolatency` | 블록 I/O 지연을 히스토그램으로, 디스크가 느린지 |
| `execsnoop` | 새로 뜨는 프로세스를 실시간으로, 예기치 않은 실행을 잡는다 |
| `runqlat` | 실행 큐 대기 시간, CPU를 기다린 시간이 긴지 |
| `tcpretrans` | TCP 재전송, 네트워크 구간이 패킷을 흘리는지 |

```bash
biolatency-bpfcc 10 1                    # 10초 동안 블록 I/O 지연 분포
execsnoop-bpfcc                          # 새 프로세스가 뜰 때마다 한 줄
runqlat-bpfcc 10 1                       # 실행 큐 대기 시간 분포
tcpretrans-bpfcc                         # 재전송이 일어날 때마다 출발지·도착지
```

`runqlat`의 대기 시간이 길면 CPU가 모자라거나 스케줄러가 프로세스를 자주 밀어낸다는 뜻이라, 앞의
스케줄러 조정과 이어진다. `biolatency`의 꼬리가 길면 특정 디스크나 파일시스템 경합을 본다.
`tcpretrans`가 자주 찍히면 분산 학습 통신 구간의 손실을 의심한다.

운영 중인 클러스터에서 쓸 때는 오버헤드와 범위를 정해 둔다. `perf record`의 표본 주기를 높이면
부하가 늘어나므로, 기본 주기로 짧게 모으고 필요할 때만 올린다. eBPF 도구는 대개 커널 안에서
집계까지 끝내고 요약만 넘겨 오버헤드가 낮지만, `execsnoop`처럼 이벤트마다 한 줄을 내는 도구는
이벤트가 폭주하면 출력이 부하가 된다. 학습이 도는 노드에서는 관찰 시간을 수십 초로 끊고, 재현이
되는 노드 한 대에서 먼저 확인한 뒤 넓히는 순서가 안전하다. bcc 도구 이름은 배포판에 따라
`biolatency` 또는 `biolatency-bpfcc`로 다르니 설치된 이름을 확인해 쓴다.

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

도구마다 성격이 조금씩 다르다. 셋을 언제 쓰는지 갈라 둔다.

| 도구 | 성격 | 언제 쓰는가 |
| --- | --- | --- |
| `pdsh` | 가벼운 병렬 SSH | 빠른 점검, 한 줄 명령을 전 노드에 |
| `clush`(ClusterShell) | 노드 그룹과 취합이 강함 | 그룹을 나눠 다루고 결과를 접어서 볼 때 |
| `srun` | 스케줄러가 할당한 노드에만 | 작업에 실제로 배정된 노드에서 실행할 때 |

`clush`는 노드 그룹을 이름으로 정의해 두고 그룹 단위로 명령을 보낸다. `/etc/clustershell/groups`에
`gpu: gpu[01-64]`처럼 정의하면 `-g gpu`로 부른다.

```bash
clush -g gpu 'nvidia-smi --query-gpu=driver_version --format=csv,noheader' | dshbak -c
clush -bg gpu uptime                # -b 는 같은 출력끼리 묶어 보여준다
```

`dshbak -c`나 `clush -b`는 출력이 같은 노드를 한 덩어리로 접는다. 64대 중 63대가 같고 1대만
드라이버 버전이 다르면, 그 1대만 따로 떨어져 나와 바로 눈에 띈다. 점검은 이렇게 "다른 것만
남기는" 방식이 빠르다.

위험한 명령은 습관으로 막는다. 배포 전에 `clush -g gpu true`나 `pdsh -w ... hostname`으로 대상이
맞는지 먼저 확인하고, 재부팅이나 삭제처럼 되돌릴 수 없는 명령은 한 노드에서 검증한 뒤 그룹으로
넓힌다. 범위 표기(`gpu[01-64]`)를 손으로 적을 때 오타 하나가 전 노드로 퍼지므로, 실행 대상을
출력해 눈으로 확인하는 절차를 건너뛰지 않는다.
