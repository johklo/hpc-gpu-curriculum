---
id: m2-multicore
no: "02"
title: 멀티코어 병렬 프로세싱
subtitle: 코어를 늘려도 빨라지지 않는 이유
level: 핵심
---

노드 한 대에 코어가 128개 있어도 프로그램이 저절로 128배 빨라지지는 않는다. 어디까지 나눌 수
있고 어디서 막히는지, 스레드를 어느 코어에 붙여야 하는지를 본다.

## 병렬화의 상한

프로그램에서 병렬로 돌릴 수 없는 구간이 조금이라도 있으면 전체 속도는 그 구간에 묶인다.
95퍼센트를 완벽히 병렬화해도 나머지 5퍼센트 때문에 최대 20배에서 멈춘다. 코어를 1000개
주더라도 마찬가지다.

| 병렬 가능 비율 | 코어 16개 | 코어 64개 | 코어 무한 |
| --- | ---: | ---: | ---: |
| 50% | 1.8배 | 2.0배 | 2배 |
| 90% | 6.4배 | 8.8배 | 10배 |
| 95% | 9.1배 | 15.4배 | 20배 |
| 99% | 13.9배 | 39.3배 | 100배 |

![병렬 가능 비율이 99퍼센트여도 코어 32개에서 24배에 그친다](img/scaling.svg)

여기서 나오는 결론은 두 가지다. 코어를 늘리기 전에 순차 구간을 먼저 줄여야 하고, 코어 수를
두 배로 늘렸을 때 성능이 두 배가 되지 않는 것은 정상이라는 점이다.

문제 크기를 함께 키우면 사정이 달라진다. 코어를 늘린 만큼 데이터도 늘리는 경우를 약한 확장이라
하고, 이쪽은 훨씬 잘 늘어난다. 대규모 학습에서 GPU를 늘리며 배치 크기를 함께 키우는 방식이
여기 해당한다.

## 프로세스와 스레드

병렬화 수단은 크게 둘이다. 무엇을 고르느냐에 따라 메모리와 통신 비용이 달라진다.

| 방식 | 메모리 | 통신 | 적합한 곳 |
| --- | --- | --- | --- |
| 멀티프로세스 (MPI) | 각자 따로 | 명시적 메시지 | 노드를 넘는 병렬 |
| 멀티스레드 (OpenMP) | 공유 | 공유 변수 | 노드 안의 병렬 |

노드 안에서는 스레드가 유리하다. 메모리를 복제하지 않아 데이터셋이 큰 작업에서 차이가 크다.
노드를 넘어가면 메모리가 공유되지 않으므로 프로세스와 메시지가 필요하다.

파이썬은 사정이 다르다. GIL 때문에 스레드로는 CPU 병렬이 되지 않는다. `multiprocessing`으로
프로세스를 띄우거나, NumPy처럼 GIL을 놓는 라이브러리 안에서 병렬이 일어나게 해야 한다.

## OpenMP로 스레드 병렬

반복문 앞에 지시자 한 줄을 붙이면 컴파일러가 스레드로 나눈다.

```c
#pragma omp parallel for
for (int i = 0; i < n; i++) {
    y[i] = a * x[i] + y[i];
}
```

반복 사이에 의존성이 없어야 한다. 앞 반복의 결과를 뒤에서 쓰면 결과가 실행할 때마다 달라진다.
합계처럼 하나의 변수에 모으는 경우는 축약을 명시한다.

```c
double sum = 0.0;
#pragma omp parallel for reduction(+:sum)
for (int i = 0; i < n; i++) sum += x[i] * y[i];
```

반복마다 걸리는 시간이 들쭉날쭉하면 정적 분배로는 일부 스레드가 먼저 끝나고 논다. 이럴 때
동적 분배로 바꾼다.

```c
#pragma omp parallel for schedule(dynamic, 64)
```

청크를 너무 작게 잡으면 분배 자체의 비용이 커진다. 수십에서 수백 사이에서 재보고 정한다.

## 스레드를 코어에 붙이기

기본 상태에서는 OS가 스레드를 옮겨 다니게 둔다. 캐시가 매번 식고 NUMA 노드를 넘나들면서
성능이 흔들린다. 붙여 두면 재현성도 함께 올라간다.

```bash
export OMP_NUM_THREADS=16
export OMP_PROC_BIND=close     # 스레드를 서로 가까이 붙인다
export OMP_PLACES=cores        # 배치 단위는 코어
```

`close`는 한 소켓에 몰아 붙여 캐시 공유가 유리하고, `spread`는 흩어 놓아 메모리 대역폭을 더
쓴다. 대역폭에 묶인 연산은 `spread`가 나은 경우가 있다.

![close는 스레드를 한 소켓에 모으고 spread는 소켓에 흩어 배치한다](img/thread-binding.svg)

메모리도 함께 묶어야 효과가 난다.

```bash
numactl --cpunodebind=0 --membind=0 ./app
```

리눅스는 메모리를 처음 만지는 스레드가 있는 노드에 페이지를 붙인다. 초기화를 한 스레드가
몰아서 하면 데이터 전체가 한 노드에 몰리고, 이후 다른 노드의 스레드는 계속 원격 접근을 한다.
초기화도 실제 계산과 같은 방식으로 병렬화해야 한다.

```c
#pragma omp parallel for
for (int i = 0; i < n; i++) x[i] = 0.0;   // 계산과 같은 분배로 초기화한다
```

## 하이브리드 MPI + OpenMP

노드 안은 스레드로, 노드 사이는 프로세스로 나누는 구성이다. 소켓마다 프로세스 하나를 두고
그 소켓의 코어 수만큼 스레드를 붙이는 배치가 무난한 출발점이다.

```bash
#SBATCH --nodes=4
#SBATCH --ntasks-per-node=2      # 소켓당 프로세스 1개
#SBATCH --cpus-per-task=64       # 소켓의 코어 수

export OMP_NUM_THREADS=$SLURM_CPUS_PER_TASK
export OMP_PROC_BIND=close
srun --cpu-bind=cores ./app
```

프로세스를 늘릴수록 통신량이 늘고, 스레드를 늘릴수록 동기화 비용과 NUMA 원격 접근이 는다.
둘 사이 균형은 코드마다 다르므로 몇 가지 조합을 재보고 고른다.

## 배치가 제대로 됐는지 확인

설정을 넣었다고 적용되는 것은 아니다. 런타임이 무시하거나 스케줄러 설정과 충돌하는 경우가 있어
실제 배치를 눈으로 확인해야 한다.

```bash
export OMP_DISPLAY_ENV=verbose      # 시작할 때 적용된 설정을 찍는다
export OMP_DISPLAY_AFFINITY=true    # 스레드가 어느 코어에 묶였는지 찍는다
export OMP_AFFINITY_FORMAT="thread %0.3n bound to core %A on host %H"
```

Slurm에서는 할당 자체를 확인한다.

```bash
srun --cpu-bind=verbose,cores ./app 2>&1 | head    # 어느 마스크로 묶였는지
taskset -pc $$                                      # 현재 셸의 허용 코어
numastat -p <pid>                                   # 노드별 메모리 사용량
```

`numastat`에서 다른 노드의 값이 크면 원격 접근이 일어나는 중이다. 첫 접근 규칙 때문에 초기화
코드가 원인인 경우가 많다.

## 동기화 비용

스레드를 늘려도 안 빨라지는 두 번째 이유가 동기화다. 임계 구역과 배리어는 스레드 수에 따라
비용이 커진다.

```c
// 나쁜 예. 매 반복마다 락을 잡는다
#pragma omp parallel for
for (int i = 0; i < n; i++) {
    #pragma omp critical
    sum += x[i];
}

// 좋은 예. 각자 모았다가 마지막에 한 번 합친다
#pragma omp parallel for reduction(+:sum)
for (int i = 0; i < n; i++) sum += x[i];
```

앞의 코드는 스레드를 늘릴수록 느려진다. 락을 기다리는 시간이 계산 시간을 넘기기 때문이다.
축약은 스레드마다 지역 변수를 두고 마지막에 트리 형태로 합치므로 이 문제가 없다.

배리어도 마찬가지다. 반복문이 끝날 때마다 암묵적 배리어가 걸리는데, 다음 계산이 앞의 결과에
의존하지 않으면 없앨 수 있다.

```c
#pragma omp parallel
{
    #pragma omp for nowait          // 배리어를 없앤다
    for (int i = 0; i < n; i++) a[i] = f(i);

    #pragma omp for                 // 여기서는 필요하다
    for (int i = 0; i < n; i++) b[i] = g(a[i]);
}
```

## 거짓 공유를 눈으로 확인

논리적으로 겹치지 않는 변수라도 같은 캐시 라인(보통 64바이트)에 있으면 코어끼리 그 줄을
주고받는다. 결과는 맞지만 성능이 크게 떨어진다.

```c
// 나쁜 예. sums 원소들이 같은 캐시 라인에 몰린다
double sums[8];
#pragma omp parallel num_threads(8)
{
    int t = omp_get_thread_num();
    for (int i = t; i < n; i += 8) sums[t] += x[i];
}

// 좋은 예. 캐시 라인 크기로 띄운다
struct { double v; char pad[56]; } sums[8];
```

의심되면 캐시 관련 카운터로 확인한다.

```bash
perf stat -e cache-misses,cache-references,LLC-load-misses ./app
```

같은 계산인데 스레드를 늘렸을 때 캐시 미스가 급증하면 거짓 공유를 의심한다.

## 작업 단위 병렬

반복문으로 나누기 어려운 구조, 예를 들어 재귀나 그래프 순회는 작업 단위로 나눈다.

```c
#pragma omp parallel
#pragma omp single
{
    #pragma omp task
    process(left);
    #pragma omp task
    process(right);
    #pragma omp taskwait
}
```

작업이 너무 잘게 쪼개지면 생성 비용이 계산을 넘는다. 일정 깊이 아래로는 순차로 처리하도록
잘라 주는 편이 낫다.

## 런타임별 환경 변수

같은 OpenMP라도 컴파일러 런타임에 따라 변수 이름이 다르다. 혼용하면 한쪽만 적용되어 원인을
찾기 어려워진다.

| 목적 | 표준 | GNU | Intel |
| --- | --- | --- | --- |
| 스레드 수 | `OMP_NUM_THREADS` | 동일 | 동일 |
| 바인딩 | `OMP_PROC_BIND` | `GOMP_CPU_AFFINITY` | `KMP_AFFINITY` |
| 대기 정책 | `OMP_WAIT_POLICY` | 동일 | `KMP_BLOCKTIME` |
| 스택 크기 | `OMP_STACKSIZE` | 동일 | `KMP_STACKSIZE` |

`KMP_BLOCKTIME`은 스레드가 일이 없을 때 얼마나 기다리다 잠들지 정한다. 기본값이 크면 유휴
스레드가 CPU를 붙잡고 있어 다른 프로세스와 경합한다. MPI와 섞어 쓸 때는 줄이는 편이 낫다.

## 자주 밟는 함정

**스레드 초과 할당**  라이브러리가 각자 스레드를 띄우면 코어 수보다 훨씬 많은 스레드가 생겨
서로를 방해한다. MPI 프로세스 8개가 각각 OpenMP 스레드 64개를 띄우면 512개가 된다. 데이터
로더나 전처리에서는 아예 1로 고정하는 편이 낫다.

```bash
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
```

**거짓 공유**  서로 다른 스레드가 같은 캐시 라인에 있는 다른 변수를 쓰면, 논리적으로는 겹치지
않는데도 캐시 라인이 계속 오간다. 스레드별 누적 변수를 배열 하나에 촘촘히 두면 이 현상이
생긴다. 각자 지역 변수에 모았다가 마지막에 합치면 사라진다.

**하이퍼스레딩**  논리 코어 수를 그대로 스레드 수로 쓰면 연산 위주 코드에서는 오히려 느려진다.
물리 코어 수로 시작해서 재보고 늘린다.

```bash
lscpu | grep -E "^CPU\(s\)|Thread|Core"
```

## 얼마나 늘어나는지 재기

느낌으로 판단하지 말고 코어 수를 바꿔가며 같은 입력으로 재본다.

```bash
for t in 1 2 4 8 16 32 64; do
  OMP_NUM_THREADS=$t /usr/bin/time -f "$t threads: %e s" ./app
done
```

코어를 두 배로 늘렸을 때 시간이 절반 가까이 줄면 그 구간까지는 잘 늘어나는 것이다. 어느
지점부터 시간이 줄지 않거나 오히려 늘면 거기가 상한이다. 그 지점을 넘겨 자원을 요청하면
클러스터 전체의 활용률만 떨어뜨린다.

어디에서 시간을 쓰는지는 프로파일러로 본다.

```bash
perf stat -d ./app                       # 명령어 수, 캐시 미스, 분기 예측
perf record -g ./app && perf report      # 함수별 비중
```

캐시 미스 비율이 높으면 데이터 배치를, 명령어 수 대비 시간이 길면 메모리 대역폭을 의심한다.
