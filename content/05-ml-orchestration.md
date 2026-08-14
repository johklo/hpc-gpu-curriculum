---
id: m5-ml
no: "05"
title: ML 인프라 오케스트레이션
subtitle: Slurm과 Kubernetes 중 무엇으로 학습을 돌릴 것인가
level: 심화
---

대규모 학습을 어디에서 돌릴지에 대한 선택 문제를 다룬다. 두 플랫폼의 자원 모델을 비교하고,
각각에서 분산 학습을 실행하는 방법과 장애 대응을 정리한다.

## 두 플랫폼의 자원 모델

같은 GPU 클러스터를 두고도 Slurm과 Kubernetes는 다른 전제로 자원을 다룬다.

| 항목 | Slurm | Kubernetes |
| --- | --- | --- |
| 기본 단위 | 작업(job). 시작과 끝이 있다 | 파드(pod). 계속 살아 있는 것을 전제한다 |
| 자원 요청 | 노드 수, 태스크 수, GRES | 컨테이너별 requests/limits |
| 동시 시작 | 기본으로 보장한다 | 별도 스케줄러 플러그인이 필요하다 |
| 실패 처리 | 작업이 끝난다. 재제출은 사용자 몫 | 재시작이 기본 동작이다 |
| 강점 | 대기열, 공정 배분, 노드 간 통신 최적화 | 서비스 운영, 롤아웃, 자동 확장 |

차이의 핵심은 전제다. Slurm은 유한한 계산을 순서대로 처리하는 배치 시스템이고, Kubernetes는
오래 사는 서비스를 유지하는 시스템이다. 학습은 배치에 가깝고 추론은 서비스에 가깝다.

## Slurm에서 분산 학습 실행

`srun`이 프로세스를 띄우면 각 프로세스에 rank 관련 환경 변수가 자동으로 들어간다. 학습 코드는
이 값을 읽어 초기화한다.

```bash
#!/bin/bash
#SBATCH --nodes=4
#SBATCH --ntasks-per-node=8
#SBATCH --gres=gpu:8
#SBATCH --cpus-per-task=12
#SBATCH --time=24:00:00

export MASTER_ADDR=$(scontrol show hostnames "$SLURM_JOB_NODELIST" | head -n1)
export MASTER_PORT=29500

srun python -u train.py
```

```python
import os, torch.distributed as dist

dist.init_process_group(
    backend="nccl",
    world_size=int(os.environ["SLURM_NTASKS"]),
    rank=int(os.environ["SLURM_PROCID"]),
)
torch.cuda.set_device(int(os.environ["SLURM_LOCALID"]))
```

컨테이너로 실행하려면 Pyxis와 Enroot를 쓴다. Docker와 달리 데몬 없이 사용자 권한으로 돌기
때문에 다중 사용자 클러스터에 적합하다.

```bash
srun --container-image=nvcr.io#nvidia/pytorch:24.07-py3 \
     --container-mounts=/scratch:/scratch \
     python train.py
```

## Kubernetes에서 분산 학습 실행

Kubernetes에서 GPU를 쓰려면 device plugin이 설치되어 있어야 한다. 그다음 파드가 GPU를
자원으로 요청한다.

```yaml
resources:
  limits:
    nvidia.com/gpu: 8
```

문제는 동시 시작이다. 기본 스케줄러는 파드를 하나씩 배치하므로, 8개 중 5개만 자리를 잡고 나머지가
대기하면 자원을 쥔 채 아무 진전이 없다. 여러 워크로드가 이 상태로 얽히면 교착에 빠진다.

해결책은 갱 스케줄링을 지원하는 스케줄러를 얹는 것이다. Volcano나 Kueue가 이 역할을 한다.
학습 잡을 다루는 상위 도구도 있다.

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
  pytorchReplicaSpecs:
    Master:
      replicas: 1
      template: {spec: {containers: [{name: pytorch, image: myrepo/train:1.0,
        resources: {limits: {nvidia.com/gpu: 8}}}]}}
    Worker:
      replicas: 3
      template: {spec: {containers: [{name: pytorch, image: myrepo/train:1.0,
        resources: {limits: {nvidia.com/gpu: 8}}}]}}
```

## 체크포인트와 장애 복구

노드가 많아질수록 학습 중 한 대가 빠질 확률이 올라간다. 512 GPU로 일주일을 돌리는 작업에서
무중단을 기대할 수는 없다. 복구 설계가 성능 최적화보다 중요할 때가 많다.

체크포인트는 세 가지를 정해야 한다.

- 주기. 너무 잦으면 I/O가 학습을 방해하고, 드물면 사고 시 잃는 계산이 크다. 한 번 저장하는 데
  걸리는 시간의 20배에서 50배 사이 간격이 출발점으로 무난하다.
- 저장 위치. 공유 스토리지에 두어야 다른 노드에서 재개할 수 있다.
- 보존 개수. 최근 두세 개만 남기고 지운다. 체크포인트가 스토리지를 채우는 사고가 흔하다.

Slurm에서는 시간 초과 직전에 신호를 받아 저장하고 스스로 재제출하는 방식을 쓴다.

```bash
#SBATCH --signal=B:USR1@600      # 종료 600초 전에 USR1을 보낸다
#SBATCH --requeue
```

학습 코드는 이 신호를 받아 체크포인트를 쓰고 종료하면 된다. `--requeue`가 있으면 Slurm이 같은
작업을 대기열에 다시 넣는다.

## 무엇을 고를 것인가

정답은 조직 상황에 달렸다. 판단 근거는 다음과 같다.

Slurm이 유리한 경우는 학습이 주력이고, 노드 간 통신 성능이 중요하고, 사용자들이 배치 제출에
익숙한 환경이다. 대기열과 공정 배분이 이미 검증된 방식으로 동작한다.

Kubernetes가 유리한 경우는 추론 서비스를 함께 운영하고, 컨테이너 기반 배포가 표준이고, 팀이
이미 Kubernetes를 쓰고 있는 환경이다. 학습만 놓고 보면 손이 더 가지만 전체 스택이 하나로
모인다.

둘 다 운영하는 선택도 흔하다. 이때 비용은 스케줄러 두 벌이 아니라 두 스택을 아는 인력이라는
점을 감안해야 한다. 모듈 04의 분리 전략을 함께 본다.
