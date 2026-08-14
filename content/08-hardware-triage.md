---
id: m6-hardware
no: "08"
title: 하드웨어 점검과 장애 분석
subtitle: PCIe 링크, NVLink, Xid, DCGM
level: 실전
---

성능이 안 나오거나 작업이 이유 없이 죽었을 때 하드웨어를 어떻게 확인하는지, 평상시 헬스체크는
어떻게 걸어두는지를 본다.

## GPU 노드의 물리 구성

장애를 읽으려면 무엇이 어디에 붙어 있는지부터 그려야 한다. GPU 서버 한 대는 대략 이렇게 구성된다.

![소켓마다 메모리와 PCIe 스위치가 붙고 그 아래에 GPU와 네트워크 카드가 달린다](img/gpu-node-anatomy.svg)

- **GPU 보드.** 연산을 하는 카드다. 서버 한 대에 보통 4장이나 8장이 들어간다. 각 보드 안에 연산
  유닛과 전용 메모리가 함께 있다.
- **HBM(High Bandwidth Memory, 고대역폭 메모리).** GPU 보드에 바로 붙은 메모리다. GPU가 학습
  데이터와 가중치를 올려 두는 곳으로, 한 장에 40~80GB가 흔하다. CPU 쪽 메모리보다 훨씬 빠르지만
  용량은 작다. "GPU 메모리가 부족하다"는 이 HBM을 말한다.
- **PCIe 레인(lane).** CPU와 GPU, NIC을 잇는 범용 통로다. 레인을 여러 개 묶어 폭을 만들고, x16은
  레인 16개를 묶었다는 뜻이다. 세대(Gen4, Gen5)가 오를수록 레인당 속도가 오른다.
- **NVLink.** GPU끼리 직접 잇는 전용 고속 링크다. PCIe보다 대역폭이 크다. 여러 GPU가 가중치를
  주고받는 학습에서 이 링크가 처리량을 좌우한다.
- **NVSwitch.** NVLink를 여러 GPU가 서로 잇도록 모아 주는 스위치다. 8장 노드에서 모든 GPU가
  서로 최대 속도로 통신하게 한다. NVSwitch가 문제면 특정 GPU 쌍만이 아니라 여러 경로가 함께
  느려진다.
- **HCA(Host Channel Adapter).** InfiniBand 네트워크 카드다. 노드와 노드를 잇는다. 여러 노드로
  학습을 키울 때 노드 사이 통신이 이 카드를 지난다. 이더넷 NIC의 InfiniBand 판이라고 보면 된다.

이 구성에서 문제는 층마다 다르게 나타난다. HBM은 ECC 오류로, GPU 사이 경로는 NVLink나 NVSwitch
오류로, 노드 사이 경로는 HCA와 PCIe 링크 문제로 드러난다. 아래 절들이 각 층을 순서대로 짚는다.

## nvidia-smi 출력 읽기

`nvidia-smi`를 인자 없이 실행하면 표 하나가 나온다. 필드마다 뜻과 위험 신호가 다르다.

```bash
nvidia-smi
```

| 필드 | 뜻 | 문제로 보는 값 |
| --- | --- | --- |
| `Temp` | GPU 코어 온도(℃) | 83℃ 부근에서 스로틀이 시작된다. 90℃ 이상은 위험 |
| `Pwr:Usage/Cap` | 현재 전력/전력 상한(W) | 사용이 상한에 계속 붙어 있으면 전력 제한에 걸린 것 |
| `Memory-Usage` | HBM 사용/전체 | 전체에 근접하면 OOM 위험 |
| `GPU-Util` | 최근 표본에서 커널이 돈 시간 비율 | 학습 중인데 낮으면 GPU 밖이 병목 |
| `Perf` | 성능 상태 P0~P12 | P0가 최대 성능. 부하 중인데 P2 이하면 스로틀 의심 |
| `ECC` | 메모리 오류 정정 상태 | 오류 카운터가 늘면 메모리 이상 |

`GPU-Util`은 오해하기 쉽다. 커널이 하나라도 돈 시간의 비율일 뿐이라, 100퍼센트여도 GPU를
효율적으로 쓴다는 보장은 없다. 실제 효율은 클럭과 전력, 처리량을 함께 봐야 안다. 온도와 클럭은
질의 형식으로 자세히 본다.

```bash
nvidia-smi --query-gpu=index,temperature.gpu,temperature.memory,\
clocks.sm,clocks.max.sm,power.draw,power.limit,pstate --format=csv
```

`temperature.memory`는 HBM 온도다. 코어 온도보다 HBM 온도가 먼저 한계에 닿는 경우가 있어, 둘을
따로 본다. `clocks.sm`이 `clocks.max.sm`보다 부하 중에 계속 낮으면 스로틀을 의심하고 열과 전력
문제 절로 넘어간다.

## PCIe 링크 점검

GPU가 규격대로 붙어 있지 않은 경우가 실제로 있다. 물리적으로는 꽂혀 있어도 링크가 절반 폭이나
낮은 세대로 협상되면 데이터 전송 구간에서 성능이 떨어진다.

```bash
nvidia-smi --query-gpu=index,pcie.link.gen.current,pcie.link.gen.max,\
pcie.link.width.current,pcie.link.width.max --format=csv
```

`current`가 `max`보다 낮으면 확인이 필요하다. 다만 유휴 상태에서는 절전으로 링크를 낮추는
경우가 있으므로, 부하를 준 상태에서 다시 본다.

```bash
nvidia-smi -q | grep -A4 "GPU Link Info"
lspci -vv -s $(nvidia-smi --query-gpu=pci.bus_id --format=csv,noheader | head -1 | cut -d: -f2-) \
  | grep -E "LnkCap|LnkSta"
```

`LnkCap`은 이 슬롯이 낼 수 있는 최대치이고 `LnkSta`는 지금 상태다. Gen5 x16 카드가 Gen4 x8로
붙어 있다면 대역폭이 4분의 1이다. 재장착이나 슬롯 변경, 라이저 케이블 점검이 필요하다.

## NVLink 상태

멀티 GPU 학습에서 NVLink가 죽으면 통신이 PCIe로 우회하면서 느려진다. 링크 상태와 오류
카운터를 함께 본다.

```bash
nvidia-smi nvlink --status          # 링크별 대역폭
nvidia-smi nvlink -e                # 오류 카운터
nvidia-smi topo -m                  # 연결 형태
```

오류 카운터는 누적값이라 절대값보다 증가 속도가 중요하다. 부팅 이후 몇 개는 흔하지만, 분 단위로
늘어난다면 물리 계층 문제다. 카운터를 초기화한 뒤 일정 시간 관찰해 증가율을 본다.

```bash
nvidia-smi nvlink -r 0              # 카운터 초기화
sleep 600
nvidia-smi nvlink -e                # 10분 동안의 증가분
```

리플레이와 복구 오류가 지속적으로 늘면 해당 노드를 드레인하고 점검 대상으로 돌린다.

`nvidia-smi nvlink -s`는 GPU마다 링크가 몇 개 올라왔고 각 링크가 몇 GB/s로 붙었는지 보여준다.
링크 수가 기대보다 적으면 죽은 링크가 있다는 뜻이다. H100은 GPU당 NVLink 18개가 규격이라, 16개만
잡혔다면 두 개가 내려간 것이다. 죽은 링크만큼 그 GPU의 통신 대역폭이 줄어, 집합 통신에서 그
GPU가 참여하는 경로가 느려진다.

`nvidia-smi nvlink -e`의 오류 카운터는 종류마다 심각도가 다르다.

| 카운터 | 뜻 | 심각도 |
| --- | --- | --- |
| `Replay` | 전송 실패로 재전송했다 | 낮음. 드물면 정상, 급증하면 물리 계층 |
| `Recovery` | 링크가 잠깐 끊겨 복구했다 | 중간. 반복되면 케이블·커넥터 |
| `CRC`(flit/data) | 오류 검출 부호 불일치 | 높음. 지속되면 링크 품질 문제 |

`Replay`는 이따금 나올 수 있지만 `Recovery`와 `CRC`가 분 단위로 늘면 물리 링크나 커넥터를 본다.

NVSwitch가 있는 노드와 없는 노드는 경로가 다르다. 8장 노드는 보통 NVSwitch를 거쳐 모든 GPU가
서로 최대 속도로 붙는다. 이 경우 링크 오류가 NVSwitch 쪽일 수 있어 `nvidia-smi nvlink` 외에
NVSwitch 상태(`nvidia-smi -q`의 스위치 항목, `nvlsm` 로그)도 본다. NVSwitch가 없는 노드는 GPU가
직접 쌍으로 붙어, 링크 하나가 죽으면 그 두 GPU 사이만 PCIe로 우회한다.

링크 하나가 죽었을 때의 영향은 통신 패턴에 달렸다. 모든 GPU가 고르게 주고받는 올리듀스에서는
가장 느린 경로가 전체를 잡아, 링크 하나만 내려가도 스텝 시간이 눈에 띄게 는다. 드레인 후 재장착이나
GPU 리셋으로 링크가 돌아오는지 보고, 재발하면 교체 대상으로 돌린다.

## Xid 오류 읽기

Xid는 NVIDIA 드라이버가 커널 로그에 남기는 오류 코드다. GPU 관련 장애 조사는 대개 여기서
시작한다.

```bash
dmesg -T | grep -i xid
journalctl -k --since "2 hours ago" | grep -i xid
```

자주 보게 되는 코드는 스무 개 남짓이고, 그중에서도 이 정도가 대부분이다.

| Xid | 의미 | 대개의 원인 |
| --- | --- | --- |
| 13 | 그래픽 엔진 예외 | 애플리케이션의 잘못된 메모리 접근 |
| 31 | GPU 메모리 페이지 폴트 | 커널 코드의 버그. 사용자 코드 쪽인 경우가 많다 |
| 43 | 소프트웨어에 의한 중단 | 앞선 오류의 후속. 원인은 다른 코드에 있다 |
| 48 | 정정 불가 ECC 오류 | 하드웨어. 페이지 리타이어 또는 교체 대상 |
| 63, 64 | 페이지 리타이어 | ECC 오류 후 해당 페이지를 격리했다 |
| 74 | NVLink 오류 | 링크나 NVSwitch 문제 |
| 79 | GPU가 버스에서 사라짐 | 전원, 과열, 물리 접속. 심각한 신호다 |

재현성과 범위로 가른다. 특정 사용자 코드에서만 나면 애플리케이션 쪽일 가능성이 높고, 같은
노드에서 사용자와 무관하게 반복되면 하드웨어를 의심한다. 여러 노드에서 한꺼번에 나면 드라이버
버전이나 전원 계통을 본다.

![Xid가 특정 노드에서 반복되면 하드웨어를 의심하고 사용자 코드와 함께만 나면 애플리케이션을 본다](img/xid-triage.svg)

ECC 상태는 별도로 확인한다.

```bash
nvidia-smi -q -d ECC | grep -E "Volatile|Aggregate|Pending"
nvidia-smi --query-remapped-rows=gpu_bus_id,remapped_rows.pending,remapped_rows.failure \
           --format=csv
```

`remapped_rows.failure`가 1이면 더 이상 치환할 여유가 없다는 뜻이라 교체 대상이다.

## ECC 오류와 교체 판단

ECC(Error-Correcting Code, 오류 정정 부호)는 메모리 비트가 뒤집혔을 때 이를 감지하고 고치는
장치다. HBM은 방사선이나 노화로 비트가 드물게 뒤집히는데, ECC가 이를 처리한다. 오류는 두
종류다.

- **정정 가능 오류(correctable, 단일 비트).** ECC가 스스로 고친다. 계산 결과는 정상이다. 이따금
  나오는 것은 정상 범위이고, 한 GPU에서 급격히 늘면 그 메모리가 약해지는 신호다.
- **정정 불가 오류(uncorrectable, 다중 비트).** ECC가 감지는 하지만 고치지 못한다. 계산 결과를
  믿을 수 없어 작업이 중단된다. Xid 48, 63, 64가 여기에 관련된다. 한 번이라도 나오면 심각하게
  본다.

```bash
nvidia-smi -q -d ECC | grep -E "Volatile|Aggregate|Uncorrectable|Correctable"
```

`Volatile`은 부팅 이후 누적, `Aggregate`는 GPU 수명 전체 누적이다. 정정 불가 오류의 `Aggregate`가
늘고 있으면 그 카드를 신뢰하기 어렵다.

로우 리매핑(row remapping)은 문제가 생긴 메모리 행을 예비 행으로 바꿔 격리하는 기능이다. 최신
GPU는 불량 행을 예비 영역으로 치환해 계속 쓸 수 있다.

```bash
nvidia-smi --query-remapped-rows=gpu_bus_id,remapped_rows.correctable,\
remapped_rows.uncorrectable,remapped_rows.pending,remapped_rows.failure --format=csv
```

- `pending`이 있으면 재부팅이나 GPU 리셋 후 치환이 반영된다. 그 전까지는 성능이 눌릴 수 있다.
- `failure`가 1이면 예비 행을 다 썼다는 뜻이라 교체 대상이다.

RMA(Return Merchandise Authorization, 제조사 반품·교체)는 이런 조건에서 건다. 정정 불가 ECC
오류가 반복되거나, `remapped_rows.failure`가 1이거나, Xid 48·79가 재현되거나, 리셋으로도 링크나
카드가 돌아오지 않을 때다. 하나만으로 애매하면 노드를 드레인하고 전체 진단(`dcgmi diag -r 3`)을
돌려 근거를 모은 뒤 판단한다.

## DCGM으로 헬스체크

수동 확인은 노드가 늘면 유지되지 않는다. DCGM은 진단과 상시 감시를 함께 제공한다.

```bash
dcgmi discovery -l                  # 인식된 GPU 목록
dcgmi health -g 0 -c                # 상시 감시 항목 점검
dcgmi diag -r 1                     # 빠른 진단, 수십 초
dcgmi diag -r 2                     # 중간 진단, 몇 분
dcgmi diag -r 3                     # 전체 진단, 수십 분. 노드를 비우고 돌린다
```

운영에서는 세 단계로 나눠 쓴다. 작업 시작 전에 `-r 1`로 걸러내고, 노드를 대기열에 넣기 전에
`-r 2`를 돌리고, 의심 노드는 드레인한 뒤 `-r 3`으로 확인한다.

Slurm의 프롤로그에 빠른 진단을 넣으면 문제 노드에 작업이 배정되는 것을 막을 수 있다.

```bash
# prolog.sh
if ! dcgmi diag -r 1 > /dev/null 2>&1; then
    scontrol update NodeName=$SLURMD_NODENAME State=DRAIN Reason="dcgm diag failed"
    exit 1
fi
```

프롤로그는 모든 작업 시작마다 돌기 때문에 오래 걸리는 진단을 넣으면 안 된다. `-r 1`도 부담이면
주기적 배치로 옮긴다.

## 어느 노드를 봐야 하는지 좁히기

노드 수백 대에서 학습이 느려졌을 때, 지표를 노드마다 하나씩 열어 보는 방식은 유지되지 않는다.
볼 대상을 먼저 좁히는 절차가 필요하다.

**1단계, 규칙으로 거른다.** 눈으로 찾기 전에 기계가 먼저 표시하게 한다. 사용률이 일정 시간
이상 바닥인 GPU, 온도나 전력이 한계에 붙은 GPU, Xid가 찍힌 노드처럼 명확한 조건을 규칙으로
정의해 두면 후보가 수백에서 몇 개로 준다.

| 규칙 | 조건 예 | 뜻하는 것 |
| --- | --- | --- |
| 유휴 | 사용률 5% 미만이 10분 이상 | 할당은 됐는데 일을 안 한다 |
| 저효율 | 사용률은 높은데 처리량이 낮음 | 커널 효율이나 통신 문제 |
| 스로틀 | 클럭이 최대치 아래로 지속 | 전력이나 냉각 문제 |
| 오류 | Xid 발생, ECC 카운터 증가 | 하드웨어 의심 |

**2단계, 분포로 본다.** 노드별 평균값 하나로는 튀는 노드가 묻힌다. 같은 작업에 참여한 GPU들의
지표를 나란히 늘어놓고 모양을 비교하면 하나만 다른 것이 눈에 띈다. 값의 분포가 다른지, 시간에
따른 패턴이 다른지는 서로 다른 문제라 따로 본다.

- 분포가 다른 경우. 다른 GPU는 사용률이 90% 근처에 몰려 있는데 하나만 40%대에 퍼져 있다면 그
  GPU가 뒤처지고 있다. 분포끼리의 거리는 젠슨-섀넌 발산 같은 척도로 수치화할 수 있다.
- 패턴이 다른 경우. 평균은 같아도 다른 GPU가 규칙적으로 오르내릴 때 하나만 불규칙하면 통신
  대기나 데이터 로딩을 의심한다. 시계열끼리의 유사도는 유클리드 거리나 상관계수로 잰다.

**3단계, 묶어서 본다.** 지표가 비슷한 노드끼리 군집으로 묶으면 다수 집단에서 떨어져 나온
소수가 드러난다. 노드 200대 중 3대만 다른 군집에 속한다면 그 3대부터 본다. 개별 임계값으로는
못 잡는 완만한 이상을 이 방법이 잡아낸다.

## 분산 학습의 불균형

집합 통신은 가장 느린 참여자를 기다린다. 랭크 하나가 10% 느리면 전체가 10% 느려진다. 그래서
평균 사용률이 아니라 **랭크 사이의 편차**를 봐야 한다.

```bash
# 작업에 참여한 노드들의 GPU 사용률을 같은 시각에 모아 비교한다
pdsh -w gpu[01-16] 'nvidia-smi --query-gpu=index,utilization.gpu,clocks.sm,power.draw \
  --format=csv,noheader' | sort
```

편차가 보이면 원인을 세 갈래로 나눠 확인한다.

| 관찰 | 확인할 것 |
| --- | --- |
| 특정 노드만 계속 낮다 | 그 노드의 스로틀, PCIe 링크 속도, NVLink 오류 |
| 매 스텝 같은 랭크가 늦다 | 데이터 분배 불균형. 샤드 크기가 고른지 본다 |
| 순서 없이 랜덤하게 늦다 | 공유 스토리지나 네트워크 경합 |

작업 안에서 랭크별 스텝 시간을 남기면 훨씬 빨리 좁혀진다. 학습 코드에서 스텝마다 랭크와 소요
시간을 로그로 찍고, 이후에 랭크별 분포를 비교하는 방식이다. 하드웨어 지표만으로는 데이터
불균형을 구분하지 못한다.

특정 랭크가 느릴 때는 네 층을 순서대로 걷어낸다. 위에서부터 확인하면 흔한 원인이 먼저 걸린다.

```bash
# 문제 랭크가 도는 노드에서 클럭·온도·ECC·친화도를 한 번에 본다
nvidia-smi --query-gpu=index,clocks.sm,clocks.max.sm,temperature.gpu,ecc.errors.uncorrected.volatile.total --format=csv
nvidia-smi topo -m                  # GPU와 NIC이 같은 NUMA 노드에 붙었는지
numastat -p <PID>                   # 원격 메모리 접근이 많은지
```

| 층 | 무엇을 보는가 | 판단 기준 |
| --- | --- | --- |
| 하드웨어 | 클럭이 낮은가, 온도가 높은가, ECC가 늘었는가 | 스로틀·오류가 있으면 그 노드 하드웨어 |
| 배치 | GPU와 코어·NIC이 같은 NUMA 노드인가 | 원격 접근이 많으면 친화도 문제 |
| 데이터 | 그 랭크의 샤드가 더 큰가 | 샤드 크기 편차가 크면 데이터 분배 |
| 통신 | 그 랭크만 경로가 다른가 | NVLink 대신 PCIe·TCP면 통신 경로 |

하드웨어는 앞의 열과 전력, NVLink 절의 명령으로 확인한다. 배치는 `nvidia-smi topo -m`과
`numastat`으로 원격 메모리 접근이 잦은지 본다. 데이터는 샤드별 표본 수를 찍어 편차를 재고, 통신은
`NCCL_DEBUG=INFO` 로그에서 그 랭크의 경로가 다른 랭크와 같은지 확인한다.

같은 노드가 매번 걸리면 그 노드를 후보에서 격리한다. 드레인해 두고 나머지로 학습을 이어가며,
빈 시간에 `dcgmi diag -r 3`으로 원인을 확인한다. 노드가 바뀌어도 같은 랭크 번호가 계속 느리면
하드웨어가 아니라 데이터나 코드의 랭크 의존 로직을 본다.

## 열과 전력 문제 진단

오류 없이 느려지는 원인의 상당수가 열과 전력이다. GPU는 온도나 전력이 한계에 닿으면 스스로
클럭을 낮춰 자신을 보호한다. 이것을 스로틀링(throttling)이라고 한다.

```bash
nvidia-smi -q -d PERFORMANCE | grep -A12 "Clocks Throttle Reasons"
```

이 출력은 각 사유가 `Active`인지 `Not Active`인지 보여준다. `Active`인 줄이 지금 클럭을 누르는
원인이다.

| 사유 | 뜻 | 볼 곳 |
| --- | --- | --- |
| `SW Power Cap` | 소프트웨어 전력 상한에 걸렸다 | 상한값이 의도한 것인지 확인한다 |
| `HW Thermal Slowdown` | 하드웨어가 온도 한계로 낮췄다 | 냉각, 먼지, 흡배기 온도 |
| `SW Thermal Slowdown` | 드라이버가 온도로 낮췄다 | 위와 같으나 여유가 조금 있다 |
| `HW Power Brake` | 외부 전원 신호로 급히 낮췄다 | 전원 케이블, PSU 용량, 랙 전력 |

전력 상한은 값으로 확인한다. 상한이 기본보다 낮게 잡혀 있으면 카드가 멀쩡해도 성능이 눌린다.

```bash
nvidia-smi -q -d POWER | grep -E "Power Limit|Power Draw"
nvidia-smi -pl 700              # 전력 상한을 700W로 되돌린다(관리자 권한)
```

열 문제는 한 노드 안에서도 자리를 탄다. 랙 위쪽이나 흡기구에서 먼 GPU가 먼저 뜨거워진다. 같은
노드의 GPU 온도를 나란히 놓고, 특정 슬롯만 계속 높으면 그 자리의 통풍이나 히트싱크 접촉을 본다.

```bash
nvidia-smi --query-gpu=index,temperature.gpu,temperature.memory,fan.speed \
           --format=csv -l 5
```

흡기 온도가 규격을 넘으면 GPU 잘못이 아니라 전산실 냉방 문제다. 여러 노드가 동시에 열 스로틀에
걸리면 개별 카드가 아니라 랙이나 공조를 본다.

## 성능 저하 진단

오류 없이 느려지는 경우가 조사하기 더 까다롭다. 스로틀링 여부부터 확인한다.

```bash
nvidia-smi -q -d PERFORMANCE | grep -A10 "Clocks Throttle Reasons"
nvidia-smi --query-gpu=index,clocks.sm,clocks.max.sm,temperature.gpu,power.draw \
           --format=csv -l 5
```

사유마다 볼 곳이 다르다.

| 사유 | 의미 | 대응 |
| --- | --- | --- |
| `SW Power Cap` | 전력 상한에 걸렸다 | 상한 확인. 의도한 설정인지 본다 |
| `HW Thermal Slowdown` | 온도가 한계에 닿았다 | 냉각, 먼지, 랙 배치를 본다 |
| `HW Power Brake` | 전원 공급 문제 | 전원 케이블과 PSU 용량을 본다 |
| `SW Thermal Slowdown` | 드라이버가 온도로 낮췄다 | 위와 같으나 여유가 조금 있다 |

스로틀이 없는데 느리다면 GPU 밖을 본다. GPU 사용률이 낮으면 데이터 로더나 전처리가 병목이고,
사용률은 높은데 처리량이 낮으면 통신이나 커널 효율 문제다. 모듈 04의 NUMA와 네트워크 항목을
함께 확인한다.

## 교체 전 증거 수집

하드웨어를 빼거나 RMA를 걸기 전에 증거를 남긴다. 카드를 뽑고 나면 같은 상태를 다시 만들 수
없고, 제조사도 근거를 요구한다. 노드를 드레인한 상태에서 아래를 모은다.

```bash
nvidia-smi -q > evidence_nvsmi_$(hostname)_$(date +%F).txt   # 전체 상태 덤프
nvidia-bug-report.sh                            # 드라이버·커널·Xid를 한 파일로 모은다
dmesg -T > evidence_dmesg_$(hostname).txt
dcgmi diag -r 3 > evidence_diag_$(hostname).txt # 전체 진단 결과
```

남길 목록은 이렇다.

- **로그.** `dmesg`의 Xid와 ECC 줄, `journalctl -k`의 해당 구간, `nvidia-bug-report.sh` 출력.
- **상태 덤프.** `nvidia-smi -q` 전체와 리매핑 행 질의 결과.
- **진단 결과.** `dcgmi diag -r 3`의 실패 항목과 전문.
- **재현 절차.** 어떤 작업, 어떤 명령, 몇 번 만에 재현되는지. 재현이 안 되면 마지막 발생 시각과
  그때의 지표.
- **범위.** 한 카드인지 노드 전체인지, 다른 노드에서도 나는지.

증거를 노드 이름과 날짜가 든 파일명으로 남기고, 자산 번호(시리얼)와 함께 티켓에 묶는다. 교체
후 같은 증상이 새 카드에서도 나면 카드가 아니라 슬롯이나 전원, 냉각을 의심하는 근거가 된다.

## 노드 반입 검사

새 GPU 노드를 받으면 대기열에 넣기 전에 검사를 돌린다. 초기 불량과 설정 누락을 이때 걸러야,
나중에 사용자 작업이 이상하게 죽는 일을 막는다. 검사는 구성 확인, 링크 확인, 부하 시험 순으로
한다.

구성이 기대와 맞는지 본다.

```bash
nvidia-smi -L | wc -l               # GPU 수가 사양과 같은가
nvidia-smi --query-gpu=name,vbios_version,driver_version --format=csv  # 모델과 버전 일치
nvidia-smi topo -m                  # NVLink 연결 형태가 정상인가
ibstat | grep -E "State|Rate"       # HCA 링크가 규격 속도로 붙었는가
```

각 링크가 규격 폭과 세대로 붙었는지 본다. PCIe가 x8로 협상되거나 NVLink 몇 개가 죽은 채로 오는
카드가 실제로 있다.

```bash
nvidia-smi --query-gpu=index,pcie.link.gen.max,pcie.link.width.max --format=csv
nvidia-smi nvlink --status          # 모든 링크가 기대 대역폭으로 잡혀야 한다
```

부하를 걸어 열과 오류를 본다. 전체 진단과 몇 시간짜리 부하 시험(burn-in)을 함께 돌린다.

```bash
dcgmi diag -r 3                     # 전체 진단. 실패 항목이 하나도 없어야 한다
# GPU에 지속 부하를 주며 온도와 스로틀, ECC 증가를 관찰한다
dcgmi diag -r 4 2>/dev/null || gpu-burn 3600
```

통과 기준을 미리 정해 두고 하나라도 어기면 반입을 보류한다.

| 항목 | 통과 기준 |
| --- | --- |
| GPU 수와 모델 | 사양과 정확히 일치 |
| 드라이버·VBIOS 버전 | 클러스터 표준과 동일 |
| PCIe 링크 | 모든 카드가 최대 세대·폭 |
| NVLink/NVSwitch | 모든 링크 정상, 오류 카운터 0 |
| HCA | 규격 속도로 링크 업 |
| 전체 진단 | `dcgmi diag -r 3` 전 항목 통과 |
| 부하 시험 | 수 시간 동안 정정 불가 ECC 0, 열 스로틀 없음 |
| 노드 간 통신 | 기존 노드와의 NCCL 대역폭이 기준 이상 |

부하 시험 중 온도가 다른 노드보다 눈에 띄게 높거나, 정정 불가 ECC가 하나라도 나오면 반입하지
않고 초기 불량으로 반품한다. 검사 결과를 노드별로 남겨 두면, 나중에 그 노드가 이상해졌을 때
반입 시점과 비교할 기준이 된다.
