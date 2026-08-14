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

한쪽을 알면 다른 쪽은 말을 바꿔 읽으면 대체로 통한다.

| Slurm | Kubernetes | 뜻 |
| --- | --- | --- |
| 작업 | Job 또는 Pod | 실행 단위 하나 |
| 태스크 | 컨테이너 안의 프로세스 | 실제로 뜨는 프로세스 |
| 파티션 | 노드 라벨과 테인트로 만든 묶음 | 노드 그룹 |
| GRES `gpu:8` | `nvidia.com/gpu: 8` | GPU 요청 |
| `sbatch` | `kubectl apply` | 제출 |
| `squeue` | `kubectl get pods` | 상태 확인 |
| `scancel` | `kubectl delete` | 취소 |
| `sacct` | 기본 기능이 없다 | 지난 실행 이력 |
| 대기열 | 기본 기능이 없다. Kueue를 얹는다 | 자원이 없을 때 줄 세우기 |

말이 없는 칸이 중요하다. Kubernetes에는 대기열이라는 개념 자체가 없다. 자원이 모자라면 파드는
`Pending`으로 남을 뿐이고, 누가 먼저인지 정하는 규칙도 없다. 학습 작업을 여럿 돌리는 순간
이 빈칸을 무엇으로 메울지가 첫 번째 결정이 된다.

반대로 Slurm에는 살아 있는 서비스를 유지하는 개념이 없다. 작업이 죽으면 끝이고, 다시 띄우는
일은 사람이나 외부 스크립트가 한다. 추론 서비스를 Slurm으로 운영하기 어려운 이유가 이것이다.

## 랭크와 통신 계층

플랫폼과 무관하게 분산 학습의 뼈대는 같다. GPU 한 장마다 프로세스 하나를 띄우고, 프로세스마다
번호를 붙여 서로를 구분한다.

| 이름 | 뜻 | 예시 값 |
| --- | --- | --- |
| `rank` | 전체에서 몇 번째 프로세스인지 | 0부터 511까지 |
| `local_rank` | 그 노드 안에서 몇 번째인지. 어느 GPU를 쓸지 정한다 | 0부터 7까지 |
| `world_size` | 프로세스 총 개수 | 512 |
| `MASTER_ADDR` | 서로를 찾을 때 기준이 되는 노드 주소 | 첫 번째 노드 |
| `MASTER_PORT` | 그 노드에서 열어 둘 포트 | 29500 |

![노드마다 GPU에 랭크를 붙이고 노드 안은 NVLink, 노드 사이는 InfiniBand로 통신한다](img/rank-layout.svg)

가장 흔한 데이터 병렬은 세 단계로 돈다. 랭크마다 서로 다른 데이터 조각으로 같은 모델을 계산하고,
계산한 기울기를 전부 더해 평균을 내고, 그 평균으로 각자 모델을 갱신한다. 모든 랭크가 같은 값으로
갱신하기 때문에 모델은 항상 서로 같다. 중간의 더하는 연산이 all-reduce다. 모든 랭크가 가진 값을
합쳐서 그 결과를 다시 모든 랭크가 갖게 하는 동작이다.

병렬로 나누는 방법은 세 가지이고, 나누는 대상이 다르면 오가는 데이터도 다르다.

| 방식 | 무엇을 나누나 | 통신하는 것 | 쓰는 때 |
| --- | --- | --- | --- |
| 데이터 병렬 | 배치를 나눈다 | 스텝마다 기울기 전체 | 모델이 GPU 한 장에 들어갈 때 |
| 텐서 병렬 | 행렬 하나를 쪼갠다 | 층마다 활성값. 매우 잦다 | 노드 안에서만. NVLink가 필요하다 |
| 파이프라인 병렬 | 층을 구간으로 나눈다 | 구간 경계의 활성값 | 모델이 노드 하나에도 안 들어갈 때 |

큰 모델은 셋을 겹쳐 쓴다. 텐서 병렬은 통신이 잦아 노드 안 NVLink로 묶고, 파이프라인 병렬은
경계에서만 주고받으므로 노드를 넘겨도 견디며, 데이터 병렬이 그 묶음들을 다시 감싼다. 이 배치를
어긋나게 잡아 텐서 병렬이 노드를 넘어가면 스텝 시간이 몇 배로 늘어난다.

통신 비용은 계층마다 다르다. 같은 노드 안 NVLink가 가장 빠르고, 노드 사이 InfiniBand가 그
다음이며, 경로가 이더넷으로 떨어지면 몇 분의 일로 내려간다. 그래서 배치할 때 같은 작업의
프로세스를 가까이 모으는 것이 성능에 직접 영향을 준다.

오가는 양도 계산된다. 데이터 병렬에서 링 방식 all-reduce가 실어 나르는 양은 파라미터 크기의
두 배 가까이다. 70B 모델의 bf16 기울기가 140 GB이므로 스텝마다 280 GB가 패브릭을 지난다.
200Gb 포트 하나가 실효 20 GB/s를 낸다면 이 통신에만 14초가 든다. 스텝 시간이 그보다 짧아야
한다면 포트를 늘리거나 통신과 계산을 겹쳐야 한다.

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

남기는 방법은 어렵지 않다. 스텝마다 시간을 재고, 정해진 간격으로 랭크 0이 모아서 기록한다.

```python
import time, torch, torch.distributed as dist

start = time.perf_counter()
loss = train_step(batch)                 # 계산
torch.cuda.synchronize()                 # 커널이 끝나기를 기다려야 시간이 맞는다
elapsed = time.perf_counter() - start

# 랭크별 스텝 시간을 모아 편차를 본다
times = torch.tensor([elapsed], device="cuda")
gathered = [torch.zeros_like(times) for _ in range(dist.get_world_size())]
dist.all_gather(gathered, times)
if dist.get_rank() == 0:
    values = torch.cat(gathered)
    print(f"step={step} avg={values.mean():.3f} max={values.max():.3f} "
          f"slowest_rank={values.argmax().item()}")
```

`torch.cuda.synchronize()`가 없으면 커널을 띄우는 시간만 재게 되어 값이 실제보다 훨씬 작게
나온다. 시간을 재는 코드에서 가장 흔한 실수다.

임계값은 절대값이 아니라 자기 클러스터의 평소 값에서 정한다. 처음 며칠은 기록만 하고, 안정된
구간의 값을 기준으로 삼는다.

| 지표 | 살펴볼 신호 | 그때 의심할 것 |
| --- | --- | --- |
| 스텝 시간 | 평소보다 20% 이상 길어진다 | 느린 노드가 섞였거나 통신 경로가 바뀌었다 |
| 랭크별 편차 | 가장 느린 랭크가 평균의 1.3배를 넘는다 | 그 랭크의 GPU나 데이터 배분 |
| 데이터 로더 대기 | 스텝 시간의 10%를 넘는다 | 읽기가 계산을 못 따라간다 |
| GPU 사용률 | 90% 아래에서 톱니처럼 흔들린다 | 데이터나 통신에서 기다린다 |
| 체크포인트 소요 | 스텝 시간의 20배를 넘는다 | 저장 방식을 바꾸거나 간격을 늘린다 |
| 재시작 횟수 | 하루 두 번을 넘는다 | 특정 노드를 의심하고 격리한다 |

느린 랭크 번호를 알면 노드를 특정할 수 있다. 랭크를 노드당 프로세스 수로 나눈 몫이 노드
순번이고, `scontrol show hostnames`로 이름을 얻는다. 같은 노드가 반복해서 걸리면 그 노드를
빼고 다시 돌려 비교한다.

## 한 클러스터에서 둘을 함께 쓰기

학습은 Slurm, 추론과 개발 환경은 Kubernetes로 두는 구성이 흔하다. 이때 지켜야 하는 규칙은
하나다. 노드는 반드시 한 스케줄러에만 속한다.

![노드는 스케줄러마다 나눠 갖고 파일시스템과 이미지와 신원과 네트워크와 지표는 함께 쓴다](img/slurm-k8s-split.svg)

한 노드를 둘이 동시에 관리하면 Slurm은 자기 할당표만 보고 GPU 0번부터 7번을 작업에 내주고,
kubelet도 자기 할당표만 보고 같은 GPU를 파드에 내준다. 서로의 할당을 모르기 때문에 두 프로세스가
같은 GPU에 올라가고 메모리가 터진다. 더 나쁜 것은 원인을 찾기 어렵다는 점이다. 학습 로그에는
OOM만 남고, 그 GPU를 누가 함께 쓰고 있었는지는 어느 쪽 로그에도 없다.

노드는 나누되 아래 다섯은 한 벌만 두고 함께 쓴다.

**공유 파일시스템.** 양쪽에서 같은 경로로 보여야 한다. Slurm 작업이 `/scratch/run-42`에 남긴
체크포인트를 Kubernetes 추론 파드가 읽으려면 경로가 같아야 한다. 파드에서는 노드에 이미 마운트된
경로를 그대로 붙이는 방식이 단순하다.

```yaml
volumes:
  - name: scratch
    hostPath: { path: /scratch, type: Directory }
```

**컨테이너 이미지.** 레지스트리는 하나로 두되 형식이 다르다는 점을 감안한다. Kubernetes는
containerd가 OCI 이미지를 그대로 받는다. Slurm 쪽 Enroot는 같은 이미지를 squashfs 파일로 바꿔
쓴다. 변환을 작업마다 하면 시작이 느려지므로 공유 경로에 미리 만들어 둔다.

```bash
enroot import -o /shared/images/train-1.0.sqsh docker://myregistry#train:1.0
srun --container-image=/shared/images/train-1.0.sqsh python train.py
```

**uid와 gid.** 실무에서 가장 자주 걸리는 항목이다. 파일 권한은 uid로 매겨진다. Slurm 작업은
사용자 uid로 돌지만 Kubernetes 파드는 기본적으로 이미지에 적힌 사용자로 돈다. 그대로 두면 파드가
root로 만든 파일을 사용자가 지우지 못하고, 사용자 쿼터도 우회된다. 파드에 실제 uid를 지정해야
양쪽이 같은 파일을 다룬다.

```yaml
securityContext:
  runAsUser: 10042        # 실제 사용자 uid
  runAsGroup: 2000
  fsGroup: 2000
```

**GPU 드라이버.** 충돌이 나는 지점이다. NVIDIA GPU Operator는 기본 설정에서 드라이버를 자기가
설치한다. Slurm 쪽은 호스트에 설치된 드라이버를 쓴다. 드라이버가 두 벌이 되면 버전이 어긋나
한쪽이 깨진다. 드라이버는 호스트에 한 벌만 두고 Operator의 설치 기능을 끈다.

```bash
helm install gpu-operator nvidia/gpu-operator --set driver.enabled=false
```

**지표.** DCGM exporter 한 벌이 양쪽 GPU를 다 본다. 다만 어느 워크로드가 쓰는지 구분할 라벨이
필요하다. Slurm 쪽은 작업 번호, Kubernetes 쪽은 네임스페이스와 파드 이름을 지표에 붙여야
사용률을 나눠 볼 수 있다. 라벨이 없으면 전체 사용률만 보이고 어느 쪽이 노는지 알 수 없다.

풀 크기는 회수에 걸리는 시간으로 정한다. 이동 가능 풀이 클수록 유연하지만, 노드를 되찾으려면
그 위에서 돌던 작업이 끝나기를 기다려야 한다. 학습 작업의 최대 실행 시간이 그대로 회수 지연의
상한이 된다. 24시간짜리 작업을 허용하는 파티션에 넣어 두면 노드 한 대를 되찾는 데 최대 24시간이
걸린다. 자주 옮길 노드는 짧은 작업만 받는 별도 파티션에 둔다.

```
# slurm.conf : 이동 가능 풀은 4시간짜리 작업까지만 받는다
PartitionName=flex Nodes=gpu[049-056] MaxTime=04:00:00 State=UP
```

## 노드를 두 풀 사이에서 옮기기

![새 작업을 막고 돌던 작업이 끝나기를 기다린 뒤 넘긴다](img/node-move.svg)

두 스케줄러 모두 노드를 비우는 명령을 가지고 있지만 이름과 동작이 어긋난다. 이 차이를 모르면
돌던 작업을 죽인다.

| 명령 | 새 작업 차단 | 돌던 것 처리 |
| --- | --- | --- |
| `scontrol update ... State=DRAIN` | 막는다 | 끝까지 둔다. 기다려야 한다 |
| `kubectl cordon` | 막는다 | 그대로 둔다 |
| `kubectl drain` | 막는다 | 다른 노드로 옮긴다 |

Slurm의 DRAIN은 Kubernetes의 cordon에 해당하고, Kubernetes의 drain에 해당하는 동작은 Slurm에
없다. 학습 작업은 다른 노드로 옮길 수 없기 때문이다. 그래서 Slurm에서 노드를 빼는 일은 항상
기다림을 포함한다.

```bash
#!/bin/bash
# Slurm 풀에서 Kubernetes 풀로 옮긴다
NODE=gpu049
LIMIT=$((6 * 3600))          # 6시간까지만 기다린다

scontrol update NodeName=$NODE State=DRAIN Reason="k8s 로 이동"

waited=0
while [ "$(squeue -w "$NODE" -h -t running | wc -l)" -gt 0 ]; do
  sleep 60
  waited=$((waited + 60))
  if [ "$waited" -ge "$LIMIT" ]; then
    echo "$NODE 에서 작업이 아직 돈다. 사람이 확인해야 한다." >&2
    exit 1                   # 강제로 끊지 않는다
  fi
done

kubectl uncordon "$NODE"
```

```bash
#!/bin/bash
# Kubernetes 풀에서 Slurm 풀로 되돌린다
NODE=gpu049

kubectl cordon "$NODE"
kubectl drain "$NODE" --ignore-daemonsets --delete-emptydir-data --timeout=900s || exit 1
scontrol update NodeName="$NODE" State=RESUME
```

기다리는 구간에서 그 노드는 어느 쪽에도 쓸모가 없다. Slurm은 새 작업을 안 넣고 Kubernetes는
아직 받지 못한다. 이동이 잦으면 이 빈 시간이 쌓여 분리로 얻은 이득을 까먹는다. 이동에 걸린
시간과 그동안 논 시간을 기록해서 정책이 실제로 이득인지 확인한다.

| 확인할 값 | 어디서 | 판단 |
| --- | --- | --- |
| 이동 1회당 대기 시간 | 이동 스크립트 로그 | 평균이 작업 최대 시간에 가까우면 파티션 시간 제한을 줄인다 |
| 이동 빈도 | 이동 스크립트 로그 | 하루 여러 번이면 정적 분리가 낫다 |
| 이동 중 유휴 시간 합 | 위 둘의 곱 | 이 값이 분리로 얻은 활용률보다 크면 이동을 접는다 |

자동화할 때 지킬 것이 두 가지다. 대기에는 반드시 상한을 두고, 상한을 넘으면 사람에게 알리고
멈춘다. 그리고 돌던 작업을 강제로 끊는 자동화는 만들지 않는다. 며칠째 돌던 학습이 자동화
스크립트에 죽는 사고는 한 번으로 신뢰를 잃는다.

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

처음 고르는 자리라면 워크로드의 성격을 먼저 확인한다. 작업에 끝이 있고 시작할 때 필요한 자원이
정해져 있으면 배치 시스템이 맞는다. 요청이 오는 동안 계속 살아 있어야 하고 부하에 따라 개수가
변해야 하면 서비스 시스템이 맞는다. 학습은 앞쪽이고 추론은 뒤쪽이다.

| 물어볼 것 | 그렇다면 |
| --- | --- |
| 노드 여러 대가 동시에 시작해야 하는가 | Slurm은 기본으로 보장한다. Kubernetes는 Volcano나 Kueue를 얹어야 한다 |
| 자원이 모자랄 때 줄을 세워야 하는가 | Slurm은 내장이다. Kubernetes는 대기열 자체가 없다 |
| 사용자 여럿이 공정하게 나눠 써야 하는가 | Slurm의 공정 배분이 성숙하다 |
| 실패했을 때 자동으로 다시 띄워야 하는가 | Kubernetes의 기본 동작이다 |
| 트래픽에 따라 개수가 변해야 하는가 | Kubernetes다. Slurm에는 그런 개념이 없다 |
| 노드 간 통신이 성능을 좌우하는가 | Slurm의 토폴로지 인지 배치가 유리하다 |
| 이미 운영 중인 스택이 있는가 | 그쪽으로 맞추는 편이 대개 싸다 |

한쪽으로 통일할 수 있으면 통일하는 편이 낫다. 두 스택을 함께 두면 인증, 이미지, 파일 권한,
드라이버, 지표를 전부 두 번 맞춰야 하고, 문제가 났을 때 어느 쪽 문제인지 가리는 데 시간이
든다. 그래도 나누는 이유는 대개 학습과 추론의 요구가 정말 다르기 때문이다. 나눌 값어치가
있는지는 짐작이 아니라 유휴 시간 측정으로 정한다.
