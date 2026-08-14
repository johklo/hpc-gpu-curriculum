---
id: m1-foundations
no: "01"
title: HPC 기초
subtitle: 클러스터의 구성과 작업 실행 경로
level: 입문
---

슈퍼컴퓨터는 거대한 한 대의 컴퓨터가 아니라 서버 수백 대를 빠른 네트워크로 묶은 것이다.
그 묶음이 어떤 부품으로 이루어지고 제출한 계산이 어느 경로로 실행되는지부터 본다.

## 클러스터의 구성

HPC 클러스터는 역할이 다른 네 덩어리로 나뉜다. 이 구분을 알아두면 장애가 났을 때 볼 곳이
빨리 좁혀진다.

| 구성 | 역할 | 하면 안 되는 것 |
| --- | --- | --- |
| 로그인 노드 | 사용자가 SSH로 접속해 코드를 편집하고 작업을 제출한다 | 무거운 계산. 로그인 노드가 멈추면 전원이 클러스터에 못 들어온다 |
| 컴퓨트 노드 | 계산이 도는 곳. GPU 노드는 보통 가속기 4~8장을 단다 | 직접 SSH로 들어가 임의 실행. 스케줄러가 모르는 부하가 생긴다 |
| 공유 스토리지 | 모든 노드가 같은 경로로 보는 파일시스템. 데이터셋과 체크포인트를 둔다 | 작은 파일 수십만 개를 동시에 여는 패턴. 메타데이터 서버가 먼저 죽는다 |
| 인터커넥트 | 노드 사이를 잇는 저지연 네트워크. InfiniBand나 RoCE를 쓴다 | 일반 이더넷과 같게 취급. 대역폭보다 지연과 집합 통신 성능이 중요하다 |

사용자 관점의 흐름은 단순하다. 로그인 노드에서 작업 스크립트를 쓰고, 스케줄러에 제출하고,
스케줄러가 빈 컴퓨트 노드를 골라 실행하고, 결과는 공유 스토리지에 남는다.

![로그인 노드에서 제출한 작업을 스케줄러가 컴퓨트 노드에 배치하고 결과가 공유 스토리지에 남는 구조](img/cluster-anatomy.svg)

노드 한 대가 죽어도 전체가 멈추지 않게 하려고, 또 비싼 GPU 노드를 계산에만 쓰게 하려고 이렇게
나눈다.

## 스케줄러가 필요한 이유

노드가 두세 대면 사용자끼리 말로 조율할 수 있다. 수십 대가 되고 사용자가 수십 명이 되면 그
방식은 무너진다. 배치 스케줄러는 이 문제를 대기열로 푼다.

사용자는 GPU 4장, 12시간, 이 스크립트라는 요청서를 내고 로그아웃한다. 스케줄러는 자원이 빌 때
그 요청을 꺼내 실행한다. 대화형 실행과는 세 군데가 다르다.

- 제출과 실행이 분리된다. 새벽 3시에 시작해도 문제없다.
- 실행 중인 작업은 할당받은 GPU와 메모리를 독점한다. 옆 사람 작업이 내 메모리를 잠식하지 않는다.
- 우선순위, 사용량 한도, 공정 배분을 규칙으로 강제할 수 있다.

클러스터 운영의 상당 부분은 누가 얼마나 오래 무엇을 쓰는가라는 정책 문제로 귀결된다.
모듈 06에서 이어 본다.

## Slurm의 구조

Slurm은 HPC에서 가장 널리 쓰는 오픈소스 스케줄러다. 데몬 세 개만 알면 그림이 잡힌다.

| 데몬 | 위치 | 역할 |
| --- | --- | --- |
| `slurmctld` | 컨트롤러 노드 | 대기열을 관리하고 어떤 작업을 어느 노드에 배치할지 결정한다 |
| `slurmd` | 모든 컴퓨트 노드 | 컨트롤러의 지시를 받아 프로세스를 띄우고 자원을 격리한다 |
| `slurmdbd` | DB 노드(선택) | 누가 언제 얼마나 썼는지 기록한다. 과금과 공정 배분의 근거가 된다 |

![사용자의 제출을 slurmctld가 받아 각 노드의 slurmd에 배치하고 slurmdbd가 사용량을 기록한다](img/slurm-flow.svg)

설정은 `slurm.conf` 하나가 중심이고, 모든 노드가 같은 사본을 가져야 한다. 노드마다 내용이
다르면 컨트롤러와 컴퓨트 노드의 인식이 어긋나 노드가 `DOWN`으로 떨어진다. 구축 초기에 가장
자주 만나는 문제다.

```ini
# 노드 정의. 실제 하드웨어와 값이 다르면 노드가 드레인된다
NodeName=gpu[01-16] CPUs=128 RealMemory=1000000 Gres=gpu:8 State=UNKNOWN

# 파티션은 대기열의 단위다. 시간 한도와 접근 권한을 여기서 나눈다
PartitionName=short Nodes=gpu[01-04] MaxTime=04:00:00 Default=YES
PartitionName=train Nodes=gpu[05-16] MaxTime=72:00:00 AllowGroups=ml
```

`RealMemory`를 실제 탑재량과 똑같이 적으면 OS가 쓰는 몫 때문에 노드가 곧바로 드레인된다.
보통 몇 GB를 빼고 적는다. 노드가 이유 없이 `DOWN`이 되면 `scontrol show node`의 `Reason`
필드를 먼저 본다.

## 매일 쓰는 Slurm 명령

손에 익어야 하는 명령은 예닐곱 개다.

| 명령 | 쓰임 |
| --- | --- |
| `sbatch job.sh` | 스크립트를 대기열에 제출한다 |
| `srun --pty bash` | 자원을 잡은 대화형 세션을 연다. 디버깅에 쓴다 |
| `squeue -u $USER` | 내 작업의 상태와 대기 사유를 본다 |
| `sinfo -N -l` | 노드별 상태를 본다. 유휴, 할당, 드레인이 한눈에 보인다 |
| `scancel <jobid>` | 작업을 취소한다 |
| `sacct -j <jobid>` | 끝난 작업의 종료 코드와 사용량을 조회한다 |
| `scontrol show job <id>` | 작업의 모든 속성을 펼쳐 본다 |

배치 스크립트는 주석처럼 보이는 `#SBATCH` 지시자로 자원을 요청한다.

```bash
#!/bin/bash
#SBATCH --job-name=train-7b
#SBATCH --partition=train
#SBATCH --nodes=4                 # 노드 4대
#SBATCH --ntasks-per-node=8       # 노드당 프로세스 8개, GPU 1장당 1개
#SBATCH --gres=gpu:8              # 노드당 GPU 8장
#SBATCH --cpus-per-task=12        # 프로세스당 CPU 12코어, 데이터 로더 몫
#SBATCH --time=24:00:00
#SBATCH --output=logs/%x-%j.out   # %x는 작업명, %j는 작업번호

srun python train.py
```

`squeue`의 `NODELIST(REASON)` 열이 대기 이유를 알려준다. `Resources`는 자원이 빌 때까지
기다리는 정상 상태고, `Priority`는 앞에 우선순위가 높은 작업이 있다는 뜻이다.
`QOSMaxJobsPerUserLimit`처럼 정책 이름이 보이면 한도에 걸린 것이다.

## MPI로 노드를 넘어 계산하기

한 노드 안에서는 스레드로 병렬화하면 되지만 노드를 넘어가면 메모리가 공유되지 않는다.
MPI는 이 상황에서 프로세스들이 메시지를 주고받아 협력하게 하는 표준이다.

`rank`는 프로세스마다 붙는 0부터의 번호이고 `size`는 전체 프로세스 수다. 이 둘이면 충분하다.
모든 프로세스가 같은 프로그램을 실행하되 자기 rank를 보고 다른 일을 한다.

```python
from mpi4py import MPI

comm = MPI.COMM_WORLD
rank, size = comm.Get_rank(), comm.Get_size()

local = sum(range(rank, 1_000_000, size))   # 각자 자기 몫만 계산한다
total = comm.allreduce(local, op=MPI.SUM)   # 하나로 합친다

if rank == 0:
    print(f"{size}개 프로세스로 계산한 합계: {total}")
```

점대점 통신은 `send`와 `recv`로 특정 상대와 주고받고, 집합 통신은
`broadcast`, `allreduce`, `allgather`처럼 전체가 함께 참여한다. 분산 학습에서 그래디언트를
평균 내는 연산이 `allreduce`이고, 학습 속도는 이 집합 통신 성능에 크게 좌우된다.

PyTorch의 `DistributedDataParallel`이 내부에서 하는 일도 allreduce다. NVIDIA 환경에서는 MPI
대신 NCCL이 그 역할을 맡아 NVLink와 InfiniBand를 활용한다. 개념은 같고 구현이 다르다.
