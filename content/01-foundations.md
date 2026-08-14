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

## 개인 서버와의 차이

개인 서버는 SSH로 들어가 프로그램을 바로 실행한다. 클러스터에서는 그렇게 하지 않는다. 계산을
직접 실행하는 대신 스케줄러에 제출하고, 스케줄러가 실행할 자리를 잡아 준다. 이 차이가 처음
오는 사람에게 가장 낯선 부분이다.

이유는 자원을 나눠 쓰기 때문이다. 로그인 노드는 수십 명이 동시에 접속하는 공용 공간이다.
여기서 학습 스크립트를 직접 돌리면 CPU와 메모리를 혼자 차지하고, 같은 노드에 접속한 다른
사람의 편집기와 명령이 함께 느려진다. GPU도 로그인 노드에는 없거나 계산용으로 열려 있지 않다.
큰 데이터를 로그인 노드에서 읽으면 공유 스토리지 대역폭까지 잠식해 클러스터 전체가 굼떠진다.
관리자가 이런 프로세스를 강제로 종료하는 경우가 흔하다.

그래서 순서가 정해져 있다. 로그인 노드에서는 코드를 편집하고 작업 스크립트를 쓰는 데까지만
하고, 실제 계산은 제출해서 컴퓨트 노드에서 돌린다.

자주 나오는 용어부터 정리한다.

| 용어 | 뜻 |
| --- | --- |
| 로그인 노드 | 접속과 편집, 제출을 하는 공용 서버. 계산을 돌리는 곳이 아니다 |
| 컴퓨트 노드 | 제출한 계산이 실제로 도는 서버. 사람이 직접 들어가지 않는다 |
| 노드 | 서버 한 대. CPU 여러 개와 메모리, 때로는 GPU를 갖춘 단위다 |
| 대기열 | 제출된 작업이 자원이 빌 때까지 줄 서서 기다리는 목록 |
| 파티션 | 노드를 용도로 묶은 대기열. 시간 한도와 접근 권한을 파티션마다 다르게 준다 |
| 작업(job) | 스케줄러에 제출하는 요청 하나. 필요한 자원과 실행할 명령을 담는다 |
| 태스크(task) | 작업 안에서 실제로 실행되는 프로세스 하나. 작업 하나가 여러 태스크로 나뉜다 |
| GRES | 일반 자원(Generic Resource)의 약자. GPU처럼 코어나 메모리가 아닌 자원을 가리킨다 |
| 배열 작업 | 같은 스크립트를 번호만 바꿔 여러 번 제출하는 묶음 |

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

스케줄러가 실제로 하는 일은 네 가지로 나뉜다.

- **자원 매칭** 각 작업이 요청한 GPU 수, 코어 수, 메모리, 시간을 보고 그것을 모두 만족하는 빈
  노드를 찾는다. 조건에 맞는 노드가 없으면 작업은 대기 상태로 남는다.
- **순서 결정** 대기 중인 작업이 여럿이면 우선순위로 줄을 세운다. 우선순위는 기다린 시간,
  그동안 쓴 양, 소속 그룹의 몫 같은 요소로 계산한다.
- **빈틈 채우기** 큰 작업이 자원이 모이기를 기다리는 동안, 그 사이 시간에 끝날 수 있는 작은
  작업을 끼워 넣는다. 백필이라 부르며, 짧은 작업에 `--time`을 정확히 적으면 이 혜택을 받는다.
- **격리** 실행 중인 작업이 할당량을 넘겨 옆 작업의 GPU나 메모리를 건드리지 못하게 막는다.

이 규칙들이 있어서 사용자는 자원 상황을 몰라도 제출만 하면 된다. 언제 실행될지는 스케줄러가
정하고, 그 판단 근거는 관리자가 정한 정책이다. 정책이 곧 우선순위이므로, 내 작업이 자꾸
밀린다면 그룹의 사용량이 이미 많거나 요청이 과한 경우가 대부분이다. 요청한 자원과 시간을
줄이면 순번이 당겨질 여지가 생긴다.

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

![작업은 대기에서 실행으로 가고 정상 종료, 실패, 시간 초과, 노드 장애 중 하나로 끝난다](img/job-states.svg)

`squeue`의 `NODELIST(REASON)` 열이 대기 이유를 알려준다. `Resources`는 자원이 빌 때까지
기다리는 정상 상태고, `Priority`는 앞에 우선순위가 높은 작업이 있다는 뜻이다.
`QOSMaxJobsPerUserLimit`처럼 정책 이름이 보이면 한도에 걸린 것이다.

## sbatch 스크립트 해부

`#SBATCH`로 시작하는 줄은 셸에게는 주석이다. `#`로 시작하니 bash는 무시하고 넘어간다. 같은
줄을 sbatch 명령이 제출 시점에 읽어 자원 요청으로 해석한다. 스크립트 하나가 셸 스크립트이면서
동시에 자원 요청서인 셈이다. 그래서 `#SBATCH` 줄은 반드시 실행 명령보다 위, 첫 실행 줄이
나오기 전에 와야 한다. 중간에 끼우면 무시된다.

한 줄씩 뜯어본다.

```bash
#!/bin/bash
#SBATCH --job-name=demo      # squeue와 로그 파일에 붙는 이름
#SBATCH --partition=short    # 어느 파티션(대기열)에 넣을지
#SBATCH --nodes=1            # 노드 몇 대를 잡을지
#SBATCH --ntasks=1           # 태스크(프로세스) 몇 개를 띄울지
#SBATCH --cpus-per-task=4    # 태스크 하나에 붙일 CPU 코어 수
#SBATCH --mem=8G             # 노드당 요청할 메모리
#SBATCH --time=00:30:00      # 최대 실행 시간. 넘기면 강제 종료된다
#SBATCH --output=logs/%x-%j.out   # 표준 출력이 저장될 경로
```

각 값은 요청량이다. 실제로 쓰는 양이 아니라 예약하는 양이므로, 크게 잡으면 그만큼 빈 노드를
오래 기다린다. `--time`은 특히 정확할수록 유리하다. 짧게 적은 작업이 백필로 먼저 실행될
여지가 커진다. 반대로 실제 소요보다 짧게 적으면 계산 도중에 잘린다.

`%x`와 `%j`는 sbatch가 치환하는 자리표시자다. `%x`는 작업 이름으로, `%j`는 작업 번호로
바뀐다. 출력 경로에 이 둘을 넣으면 작업마다 로그가 겹치지 않는다.

## 처음 제출하는 세 가지 예제

가장 작은 것부터 올린다. 첫 제출은 자원을 거의 안 쓰고 경로만 확인하는 용도다.

```bash
#!/bin/bash
#SBATCH --job-name=hello
#SBATCH --partition=short
#SBATCH --ntasks=1
#SBATCH --time=00:05:00
#SBATCH --output=logs/%x-%j.out

echo "실행 노드: $(hostname)"
echo "작업 번호: $SLURM_JOB_ID"
sleep 10
```

`mkdir -p logs` 뒤에 `sbatch hello.sh`로 제출하고, `squeue -u $USER`로 상태를 보고, 끝나면
`logs/` 밑의 파일을 열어 본다. 여기까지가 클러스터에서 무언가를 돌리는 최소 왕복이다.

두 번째는 CPU 여러 코어를 쓰는 예제다. 전처리나 데이터 변환이 여기 해당한다.

```bash
#!/bin/bash
#SBATCH --job-name=preprocess
#SBATCH --partition=short
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=logs/%x-%j.out

export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK
srun python preprocess.py --workers $SLURM_CPUS_PER_TASK
```

세 번째는 GPU를 잡는 예제다. `--gres=gpu:N`으로 GPU를 요청하는 부분이 앞의 두 예제와 다른
지점이다.

```bash
#!/bin/bash
#SBATCH --job-name=train
#SBATCH --partition=train
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=12
#SBATCH --mem=64G
#SBATCH --time=12:00:00
#SBATCH --output=logs/%x-%j.out

module purge
module load cuda/12.4
nvidia-smi --query-gpu=index,name --format=csv,noheader
srun python train.py
```

세 예제는 요청하는 자원만 다르고 제출과 확인 절차는 똑같다. GPU 한 장으로 도는 것을 확인한
뒤에 노드 수와 GPU 수를 늘리는 순서가 안전하다.

## 대화형 작업

제출하고 기다리는 방식만 있는 것은 아니다. 개발과 디버깅에서는 자원을 잡은 채 셸에서 직접
명령을 두드리는 대화형 방식을 더 많이 쓴다. 코드를 고치고 바로 돌려 보고 오류를 확인하는
순환이 배치 제출보다 빠르기 때문이다.

두 가지 방법이 있다.

```bash
# 방법 1: 자원을 할당받고 그 안에서 셸을 연다
salloc --partition=short --gres=gpu:1 --cpus-per-task=8 --time=02:00:00
# 할당되면 프롬프트가 돌아온다. 이후 srun으로 컴퓨트 노드에서 실행한다
srun python train.py --debug

# 방법 2: 컴퓨트 노드의 대화형 셸로 바로 들어간다
srun --partition=short --gres=gpu:1 --cpus-per-task=8 --time=02:00:00 --pty bash
# 프롬프트가 컴퓨트 노드로 바뀐다. nvidia-smi로 GPU가 붙었는지 확인한다
```

`--pty bash`는 컴퓨트 노드 위에서 대화형 셸을 띄운다. 이 셸 안은 로그인 노드가 아니라
할당받은 컴퓨트 노드이므로, 여기서는 GPU를 써도 된다. 짧은 실험과 환경 점검, 오류 재현에
적합하다.

주의할 것이 있다. 대화형 세션은 사람이 붙어 있는 동안 자원을 계속 점유한다. 생각하는 사이에도
GPU가 놀며 잡혀 있으므로, 실험이 끝나면 셸을 빠져나와 할당을 반납한다. 긴 학습은 대화형으로
돌리지 않고 배치로 제출하는 편이 자원 활용에 낫다.

## 대기 사유 읽기

`squeue`의 `NODELIST(REASON)` 열은 작업이 왜 아직 안 도는지 알려준다. 값마다 뜻과 사용자가
할 수 있는 일이 다르다.

| REASON | 뜻 | 할 수 있는 일 |
| --- | --- | --- |
| `Priority` | 앞에 우선순위가 높은 작업이 있다 | 기다린다. 요청 자원이나 시간을 줄이면 순번이 당겨진다 |
| `Resources` | 조건에 맞는 노드가 빌 때까지 대기 중이다 | 정상 상태다. 요청을 줄이면 더 빨리 잡힌다 |
| `QOSMaxJobsPerUserLimit` | 사용자당 동시 실행 한도에 걸렸다 | 실행 중인 내 작업이 끝나야 다음이 시작된다 |
| `ReqNodeNotAvail` | 요청한 노드가 예약, 점검, 다운 상태다 | `sinfo`로 노드 상태를 보고 조건을 넓힌다 |
| `Dependency` | 선행 작업이 아직 안 끝났다 | 의존 대상 작업의 상태를 확인한다 |
| `AssocMaxJobsLimit` | 그룹 단위 한도에 걸렸다 | 그룹의 다른 작업이 끝나기를 기다린다 |
| `PartitionTimeLimit` | 요청 시간이 파티션 한도를 넘었다 | `--time`을 줄이거나 한도가 긴 파티션으로 옮긴다 |

`Resources`와 `Priority`는 기다리면 풀리는 정상 상태다. 정책 이름이 붙은 값은 한도에 걸린
것이므로 기다림만으로는 안 풀리고, 내 다른 작업이 끝나거나 요청을 조정해야 한다.

## 작업이 끝난 뒤 확인할 것

작업은 끝나는 방식이 여러 가지이고, 그때마다 볼 곳이 다르다.

| 상태 | 뜻 | 확인할 것 |
| --- | --- | --- |
| `COMPLETED` | 정상 종료 | 없음 |
| `FAILED` | 종료 코드가 0이 아니다 | 애플리케이션 로그 |
| `TIMEOUT` | 요청 시간을 넘겼다 | `--time` 설정, 실제 소요 시간 |
| `OUT_OF_MEMORY` | 메모리 한도 초과 | `MaxRSS`와 요청량 |
| `NODE_FAIL` | 노드가 빠졌다 | 그 노드의 상태와 로그 |
| `CANCELLED` | 취소됐다 | 누가 취소했는지, 관리자 조치인지 |

```bash
sacct -j 12345 --format=JobID,JobName,State,ExitCode,MaxRSS,ReqMem,Elapsed,Timelimit,NodeList
```

`ExitCode`는 두 값이 콜론으로 이어진다. 앞은 프로세스 종료 코드, 뒤는 받은 신호 번호다.
`0:9`면 SIGKILL을 받은 것이고 `0:15`면 SIGTERM이다. 시간 초과로 스케줄러가 죽인 경우가 흔하다.

`MaxRSS`가 요청 메모리에 근접했다면 다음 제출에서 늘린다. 반대로 요청량의 10퍼센트만 썼다면
줄이는 편이 낫다. 과하게 요청하면 자기 작업이 대기열에서 밀린다.

## 재현 가능한 작업 만들기

같은 스크립트가 어제는 됐는데 오늘은 안 되는 상황은 대부분 환경 차이에서 온다. 작업
스크립트가 사용자 셸 설정에 기대지 않게 만들면 이 문제가 크게 준다.

```bash
#!/bin/bash
#SBATCH ...

set -euo pipefail            # 실패를 조용히 넘기지 않는다
module purge                 # 셸에 남아 있던 모듈을 내린다
module load cuda/12.4 nccl/2.21

echo "host=$(hostname) job=$SLURM_JOB_ID"    # 나중에 조사할 근거를 남긴다
nvidia-smi --query-gpu=index,name,driver_version --format=csv
python -c "import torch; print(torch.__version__, torch.version.cuda)"

srun python train.py
```

앞부분의 몇 줄이 로그에 남아 있으면 나중에 문제를 조사할 때 시간을 크게 줄인다. 어떤 노드에서
어떤 드라이버와 어떤 라이브러리 버전으로 돌았는지가 곧 단서다.

환경을 고정하는 방법은 네 군데를 잡는 것이다. 모듈은 `cuda`가 아니라 `cuda/12.4`처럼 버전을
박아 부른다. 버전을 빼면 클러스터의 기본값이 바뀔 때 결과가 조용히 달라진다. 컨테이너를 쓰면
태그를 `latest`가 아니라 다이제스트까지 고정한다. 시드는 실행 시작에서 한 번에 묶어 고정한다.

```bash
module load cuda/12.4 nccl/2.21                     # 버전을 박아 부른다
export PYTHONHASHSEED=0
export CUBLAS_WORKSPACE_CONFIG=:4096:8              # cuBLAS 결정성 확보

# 컨테이너는 태그가 아니라 다이제스트로 고정한다
CImg=nvcr.io/nvidia/pytorch@sha256:9f1c...          # 다이제스트 전체를 적는다
srun --container-image=$CImg python train.py
```

```python
import random, numpy as np, torch
SEED = 42
random.seed(SEED); np.random.seed(SEED)
torch.manual_seed(SEED); torch.cuda.manual_seed_all(SEED)
torch.use_deterministic_algorithms(True)           # 비결정 연산을 막는다
```

무엇으로 돌렸는지를 로그에 남겨야 나중에 되짚는다. 코드의 커밋 해시와 미커밋 변경 여부를 함께
찍는다.

```bash
echo "commit=$(git rev-parse HEAD) dirty=$(git status --porcelain | wc -l)"
pip freeze > logs/pip-$SLURM_JOB_ID.txt             # 실제 설치본을 통째로 남긴다
```

같은 결과가 안 나오면 넓은 쪽부터 좁힌다. 커밋 해시가 같은지, `pip freeze` 결과가 같은지,
모듈과 드라이버 버전이 같은지, 시드가 실제로 걸렸는지 순서로 본다. 여기까지 같은데도 값이
흔들리면 원자적 덧셈이나 비결정 커널이 원인인 경우가 많고, `torch.use_deterministic_algorithms`가
그 지점을 예외로 알려준다.

작업 스크립트는 코드와 같은 저장소에서 함께 버전 관리한다. 스크립트만 홈 디렉터리에 따로 두면
코드가 바뀔 때 스크립트가 뒤처져 재현이 깨진다. 저장소에 `slurm/` 디렉터리를 두고 제출 파일을
넣은 뒤, 어떤 커밋으로 제출했는지 태그로 남긴다.

```bash
git add slurm/train.sh && git commit -m "train: 노드 4대 설정"
git tag run-$(date +%Y%m%d)-$SLURM_JOB_ID           # 이 제출을 커밋에 고정한다
```

## 작업 의존성으로 단계 잇기

전처리가 끝난 뒤에 학습을 시작해야 하는 것처럼, 작업 사이에 순서가 있는 경우가 있다. 손으로
결과를 확인하고 다음을 제출하는 대신 의존성을 걸어 두면 스케줄러가 순서를 지킨다.

```bash
# 전처리를 제출하고 작업 번호를 받는다
pre=$(sbatch --parsable preprocess.sh)

# 전처리가 정상 종료(afterok)한 뒤에만 학습을 시작한다
sbatch --dependency=afterok:$pre train.sh
```

`--parsable`은 작업 번호만 출력해 변수에 담기 좋게 한다. `afterok:`은 선행 작업이 종료 코드
0으로 끝났을 때만 다음을 실행한다. 전처리가 실패하면 학습은 시작되지 않고
`DependencyNeverSatisfied` 상태로 남아, 잘못된 데이터로 학습하는 사고를 막는다.

조건은 몇 가지가 있다.

| 조건 | 실행 시점 |
| --- | --- |
| `afterok:ID` | 선행 작업이 정상 종료한 뒤 |
| `afterany:ID` | 선행 작업이 성공이든 실패든 끝난 뒤 |
| `afternotok:ID` | 선행 작업이 실패로 끝난 뒤. 복구용 |
| `after:ID` | 선행 작업이 시작된 뒤 |

여러 단계를 이어 학습, 평가, 리포트 생성을 하나의 사슬로 묶으면 사람이 중간에 개입하지 않아도
순서대로 돈다.

## 배열 작업으로 스윕 돌리기

같은 코드를 학습률만 바꿔 열 번 돌리는 상황에서, 스크립트를 열 개 만들 필요는 없다. 배열
작업은 스크립트 하나를 번호만 바꿔 여러 번 제출한다.

```bash
#!/bin/bash
#SBATCH --job-name=sweep
#SBATCH --partition=train
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --time=06:00:00
#SBATCH --array=0-4                     # 5개 작업. 인덱스는 0부터 4까지
#SBATCH --output=logs/%x-%A-%a.out      # %A는 배열 전체 번호, %a는 개별 인덱스

lrs=(0.1 0.05 0.01 0.005 0.001)
lr=${lrs[$SLURM_ARRAY_TASK_ID]}         # 인덱스로 자기 몫의 값을 고른다

srun python train.py --lr $lr
```

`--array=0-4`는 인덱스 0부터 4까지 다섯 개의 하위 작업을 만든다. 각 하위 작업은
`$SLURM_ARRAY_TASK_ID`로 자기 번호를 알고, 그 번호로 배열에서 학습률을 골라 쓴다. 다섯
작업이 자원이 있는 대로 병렬로 실행된다.

동시에 도는 개수를 제한하려면 `%`를 붙인다. `--array=0-19%4`는 스무 개 중 최대 네 개만
한꺼번에 돌린다. 클러스터를 혼자 점유하지 않으면서 큰 스윕을 걸 때 쓴다.

## 자주 하는 제출 실수

| 증상 | 원인 | 고치는 법 |
| --- | --- | --- |
| 계속 `PENDING` | 요청이 어떤 노드보다도 크다 | `sinfo -o "%n %c %m %G"` 로 실제 사양 확인 |
| GPU가 안 보인다 | `--gres` 를 빼먹었다 | `--gres=gpu:N` 추가 |
| 프로세스가 하나만 뜬다 | `python` 을 직접 실행했다 | `srun python` 으로 실행 |
| 데이터 로더가 느리다 | `--cpus-per-task` 가 작다 | GPU당 8~16코어를 잡는다 |
| 로그가 안 남는다 | 출력 경로의 디렉터리가 없다 | 제출 전에 `mkdir -p logs` |

표의 첫 줄이 가장 흔하다. 요청한 자원이 어떤 노드보다도 크면 작업은 영원히 `PENDING`으로
남는다. GPU 12장을 요청했는데 노드마다 8장뿐이면 조건을 만족하는 노드가 없기 때문이다. 제출
전에 실제 노드 사양을 확인하는 습관이 이 문제를 없앤다.

```bash
sinfo -o "%n %c %m %G"     # 노드 이름, 코어 수, 메모리, GRES(gpu 수)
```

`srun` 없이 `python`을 직접 부르는 실수도 잦다. 배치 스크립트에서 `srun`을 붙이면 스케줄러가
할당한 자원 배치대로 프로세스를 띄운다. 붙이지 않으면 지시자로 노드 여러 대를 잡아 놓고도
프로세스는 첫 노드에서 하나만 돌아, 나머지 자원이 통째로 논다. 멀티노드 작업에서 특히
치명적이다.

메모리 요청도 자주 어긋난다. `--mem`을 너무 작게 잡으면 작업이 `OUT_OF_MEMORY`로 죽고, 너무
크게 잡으면 빈 노드를 오래 기다린다. 첫 제출에서는 넉넉히 잡아 완주시킨 뒤, `sacct`의 `MaxRSS`를
보고 실제 사용량에 맞춰 줄이는 순서가 안전하다.

## 손에 클러스터가 없을 때

Slurm을 익히려고 클러스터를 기다릴 필요는 없다. 컨테이너로 노트북 위에 작은 클러스터를 세워
명령과 스크립트를 그대로 연습할 수 있다. GPU는 없지만 제출, 대기열, 의존성, 배열 작업 같은
동작은 실제와 같다.

```bash
# 컨트롤러 한 대와 컴퓨트 두 대를 띄운다
git clone https://github.com/giovtorres/slurm-docker-cluster
cd slurm-docker-cluster
docker compose up -d
docker compose exec slurmctld bash        # 로그인 노드에 들어간 셈이다
```

```bash
# 안에서 평소처럼 쓴다
sinfo
srun -N2 hostname
sbatch --wrap 'sleep 30; echo done'
squeue
sacct
```

macOS에서 Docker Desktop을 쓰지 않는다면 colima로 런타임만 띄워도 된다. 리눅스 가상 머신 하나를
올려 그 위에서 컨테이너를 돌리는 방식이라 동작은 같다.

```bash
brew install colima docker docker-compose
colima start --cpu 4 --memory 8
docker compose up -d
```

연습용 클러스터에서 확인할 수 있는 것과 없는 것을 구분해 둔다.

| 확인되는 것 | 확인되지 않는 것 |
| --- | --- |
| 제출과 대기열 동작 | GPU 자원 요청과 배치 |
| 스크립트 문법과 환경 변수 | 노드 간 고속 통신 |
| 의존성과 배열 작업 | 공유 파일시스템 성능 |
| 파티션과 시간 제한 정책 | 실제 대기 시간과 경합 |
| `sacct` 기록 읽기 | 하드웨어 장애 상황 |

스크립트를 여기서 다듬고 실제 클러스터에서는 자원 요청만 바꿔 제출하면 실수가 준다. 특히 처음
쓰는 사람이 `#SBATCH` 지시어를 잘못 적어 겪는 실패는 대부분 여기서 미리 걸러진다.

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
