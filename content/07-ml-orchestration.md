---
id: m7-ml
no: "07"
title: ML 인프라 오케스트레이션
subtitle: Slurm과 Kubernetes에서 분산 학습을 띄우고 지키는 법
level: 심화
---

대규모 학습을 어디에서 돌릴 것인가. 두 플랫폼의 자원 모델이 어떻게 다른지, 각각에서 분산
학습을 어떻게 띄우는지, 노드가 빠졌을 때 무엇이 남는지를 본다.

## 두 플랫폼의 자원 모델

같은 GPU 클러스터를 두고도 Slurm과 Kubernetes는 다른 전제로 자원을 다룬다.

| 항목 | Slurm | Kubernetes |
| --- | --- | --- |
| 기본 단위 | 작업. 시작과 끝이 있다 | 파드. 계속 살아 있는 것을 전제한다 |
| 자원 요청 | 노드 수, 태스크 수, GRES | 컨테이너별 requests와 limits |
| 동시 시작 | 기본으로 보장한다 | 스케줄러 플러그인을 얹어야 한다 |
| 대기열 | 내장. 우선순위와 공정 배분이 있다 | 없다. Kueue나 Volcano로 더한다 |
| 실패 처리 | 작업이 끝난다. 재제출은 정책으로 정한다 | 재시작이 기본 동작이다 |
| 토폴로지 인지 | `topology.conf`로 스위치를 안다 | 라벨과 어피니티로 흉내낸다 |
| 강점 | 대기열, 공정 배분, 노드 간 통신 최적화 | 서비스 운영, 롤아웃, 자동 확장 |

차이의 뿌리는 전제다. Slurm은 유한한 계산을 순서대로 처리하는 배치 시스템이고, Kubernetes는
오래 사는 서비스를 유지하는 시스템이다. 학습은 배치에 가깝고 추론은 서비스에 가깝다.

## 랭크와 통신 계층

플랫폼과 무관하게 분산 학습의 뼈대는 같다. 프로세스마다 전역 번호인 rank가 붙고, 노드 안에서의
번호인 local_rank로 어느 GPU를 쓸지 정한다. 전체 프로세스 수가 world_size다.

![노드마다 GPU에 랭크를 붙이고 노드 안은 NVLink, 노드 사이는 InfiniBand로 통신한다](img/rank-layout.svg)

통신 비용은 계층마다 다르다. 같은 노드 안 NVLink가 가장 빠르고, 노드 사이 InfiniBand가 그
다음이며, 경로가 이더넷으로 떨어지면 몇 분의 일로 내려간다. 그래서 배치할 때 같은 작업의
프로세스를 가까이 모으는 것이 성능에 직접 영향을 준다.

## Slurm에서 분산 학습 실행

`srun`이 프로세스를 띄우면 rank 관련 환경 변수가 자동으로 들어간다. 학습 코드는 그 값을 읽어
초기화한다.

```bash
#!/bin/bash
#SBATCH --job-name=train-7b
#SBATCH --nodes=4
#SBATCH --ntasks-per-node=8          # GPU 1장당 프로세스 1개
#SBATCH --gres=gpu:8
#SBATCH --cpus-per-task=12           # 데이터 로더 몫
#SBATCH --time=24:00:00
#SBATCH --signal=B:USR1@600          # 종료 10분 전에 신호를 받는다
#SBATCH --requeue
#SBATCH --output=logs/%x-%j.out

export MASTER_ADDR=$(scontrol show hostnames "$SLURM_JOB_NODELIST" | head -n1)
export MASTER_PORT=29500
export NCCL_DEBUG=WARN

srun --cpu-bind=cores python -u train.py
```

```python
import os, torch, torch.distributed as dist

dist.init_process_group(
    backend="nccl",
    world_size=int(os.environ["SLURM_NTASKS"]),
    rank=int(os.environ["SLURM_PROCID"]),
)
local_rank = int(os.environ["SLURM_LOCALID"])
torch.cuda.set_device(local_rank)
model = torch.nn.parallel.DistributedDataParallel(model.cuda(), device_ids=[local_rank])
```

`torchrun`을 쓰고 싶다면 노드마다 하나씩 띄우고 그 안에서 프로세스를 나누게 한다. 이때는
`--ntasks-per-node=1`로 두어야 한다.

```bash
#SBATCH --ntasks-per-node=1
srun torchrun --nnodes=$SLURM_NNODES --nproc-per-node=8 \
     --rdzv-backend=c10d --rdzv-endpoint=$MASTER_ADDR:29500 train.py
```

컨테이너로 실행하려면 Pyxis와 Enroot를 쓴다. 데몬 없이 사용자 권한으로 돌기 때문에 다중 사용자
클러스터에 맞는다.

```bash
srun --container-image=nvcr.io#nvidia/pytorch:24.07-py3 \
     --container-mounts=/scratch:/scratch,/local/nvme:/cache \
     --container-workdir=/workspace \
     python train.py
```

## Kubernetes에서 분산 학습 실행

GPU를 쓰려면 device plugin이 먼저 있어야 한다. 그다음 파드가 GPU를 자원으로 요청한다.

```yaml
resources:
  limits:
    nvidia.com/gpu: 8
```

문제는 동시 시작이다. 기본 스케줄러는 파드를 하나씩 배치하므로 8개 중 5개만 자리를 잡고
나머지가 대기하면 진전 없이 자원만 점유한다. 여러 워크로드가 이 상태로 얽히면 교착에 빠진다.
갱 스케줄링을 지원하는 스케줄러를 얹어 해결한다.

| 도구 | 역할 |
| --- | --- |
| Kubeflow Training Operator | PyTorchJob 같은 리소스로 분산 학습을 선언한다 |
| Volcano | 갱 스케줄링, 큐, 공정 배분을 더한다 |
| Kueue | 배치 잡의 대기열과 할당량을 관리한다 |
| Ray | 파이썬 수준에서 클러스터를 다룬다. 학습과 추론을 함께 얹기 좋다 |

```yaml
apiVersion: kubeflow.org/v1
kind: PyTorchJob
metadata:
  name: train-7b
spec:
  runPolicy:
    schedulingPolicy:
      minAvailable: 4          # 넷이 다 모여야 시작한다
  pytorchReplicaSpecs:
    Master:
      replicas: 1
      template:
        spec:
          schedulerName: volcano
          containers:
            - name: pytorch
              image: myrepo/train:1.0
              resources:
                limits:
                  nvidia.com/gpu: 8
                  rdma/hca: 1        # RDMA 장치를 함께 요청한다
    Worker:
      replicas: 3
      template:
        spec:
          schedulerName: volcano
          containers:
            - name: pytorch
              image: myrepo/train:1.0
              resources:
                limits:
                  nvidia.com/gpu: 8
                  rdma/hca: 1
```

RDMA를 쓰려면 장치를 파드에 노출해야 한다. NVIDIA Network Operator나 SR-IOV device plugin이
이 일을 한다. 이 설정이 빠지면 통신이 조용히 TCP로 떨어지고, 오류 없이 몇 배 느려진다.

같은 작업의 파드를 가까이 모으려면 노드에 토폴로지 라벨을 붙이고 어피니티로 묶는다.

```yaml
affinity:
  podAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchLabels: {job-name: train-7b}
        topologyKey: topology.kubernetes.io/rack
```

## 통신 백엔드 확인

성능 문제의 상당수가 통신 경로에서 나온다. 학습을 띄우기 전에 경로부터 확인한다.

```bash
export NCCL_DEBUG=INFO
export NCCL_DEBUG_SUBSYS=INIT,NET
srun -N2 --ntasks-per-node=8 python -c "
import os, torch, torch.distributed as dist
dist.init_process_group('nccl')
t = torch.ones(1, device='cuda')
dist.all_reduce(t)
print(os.environ['SLURM_PROCID'], t.item())
"
```

로그에서 볼 것은 두 줄이다. `NET/IB`가 보이면 InfiniBand를 쓰는 것이고, `NET/Socket`이면 TCP로
떨어진 것이다. 후자라면 원인을 찾기 전에는 성능을 논할 수 없다.

| 변수 | 쓰임 |
| --- | --- |
| `NCCL_IB_HCA` | 쓸 HCA를 지정한다. 여러 장이면 나열한다 |
| `NCCL_SOCKET_IFNAME` | 부트스트랩에 쓸 인터페이스. `docker0` 같은 가짜를 고르는 사고를 막는다 |
| `NCCL_IB_GID_INDEX` | RoCE에서 GID를 고른다. 값이 틀리면 연결이 안 된다 |
| `NCCL_P2P_DISABLE` | NVLink 문제를 배제하고 비교할 때 임시로 쓴다 |
| `NCCL_ALGO` / `NCCL_PROTO` | 알고리즘을 고정해 비교한다. 평소에는 자동에 맡긴다 |

대역폭은 학습 전에 따로 잰다. `nccl-tests`의 `all_reduce_perf`가 표준 도구다. 노드 수를 늘리며
재면 어디서 꺾이는지 보인다.

## 장애를 견디는 설계

노드가 많아질수록 학습 중 한 대가 빠질 확률이 올라간다. 512 GPU로 일주일을 돌리는 작업에서
무중단을 기대할 수는 없다. 복구 설계가 성능 최적화보다 중요할 때가 많다.

**신호를 받아 저장하고 다시 큐에 든다.** Slurm은 종료 전에 신호를 보낼 수 있다.

```python
import signal, sys

def on_signal(signum, frame):
    save_checkpoint(step)      # 마지막 상태를 남긴다
    sys.exit(0)                # requeue 가 걸려 있으면 Slurm 이 다시 넣는다

signal.signal(signal.SIGUSR1, on_signal)
```

**탄력 학습을 쓴다.** `torchrun`은 프로세스가 빠져도 남은 것으로 재구성할 수 있다. world_size가
바뀌므로 학습률과 배치 크기를 그에 맞춰 조정하는 코드가 필요하다.

```bash
torchrun --nnodes=4:8 --nproc-per-node=8 --max-restarts=3 \
         --rdzv-backend=c10d --rdzv-endpoint=$MASTER_ADDR:29500 train.py
```

**시작 전에 노드를 검사한다.** 문제 노드가 섞이면 학습 전체가 느려지거나 죽는다. 프롤로그에서
빠른 진단을 돌려 걸러낸다. 모듈 08의 헬스체크 항목과 함께 본다.

**재시작을 관측한다.** 몇 번 재시작했는지, 매번 어디서 죽었는지가 남아야 원인을 찾는다.
재시작 횟수를 지표로 내보내고 임계값을 넘으면 사람이 본다.

## 학습 작업에서 봐야 할 지표

작업 하나를 두고 볼 지표는 하드웨어 지표만이 아니다.

| 지표 | 어디서 | 무엇을 알려주는가 |
| --- | --- | --- |
| 스텝 시간 | 학습 코드 | 전체 진행 속도. 가장 중요한 값이다 |
| 랭크별 스텝 시간 편차 | 학습 코드 | 특정 랭크가 뒤처지는지 |
| 데이터 로더 대기 시간 | 학습 코드 | 스토리지가 계산을 못 따라가는지 |
| GPU 사용률 | DCGM | 계산 유닛이 노는지 |
| 통신 시간 비율 | 프로파일러 | 스케일이 통신에 먹히는지 |
| 체크포인트 소요 시간 | 학습 코드 | 저장이 학습을 멈추는지 |

하드웨어 지표만 보면 데이터 불균형이나 통신 비중을 알 수 없다. 학습 코드에서 남기는 값이
있어야 판단이 선다. 스텝 시간과 랭크 번호만 찍어도 조사 범위가 크게 준다.

## 무엇을 고를 것인가

| 상황 | 맞는 선택 |
| --- | --- |
| 학습이 주력이고 노드 간 통신이 중요하다 | Slurm |
| 사용자가 배치 제출에 익숙하다 | Slurm |
| 대기열과 공정 배분이 필요하다 | Slurm, 또는 Kubernetes에 Kueue를 얹는다 |
| 추론 서비스를 같은 스택에서 운영한다 | Kubernetes |
| 컨테이너 기반 배포가 이미 표준이다 | Kubernetes |
| 팀이 이미 Kubernetes를 운영한다 | Kubernetes |

둘 다 운영하는 선택도 흔하다. 이때 비용은 스케줄러 두 벌이 아니라 두 스택을 아는 인력이라는
점을 감안해야 한다. 노드를 어떻게 나눌지는 모듈 06의 분리 전략에서 다룬다.
