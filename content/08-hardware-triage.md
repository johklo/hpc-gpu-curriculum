---
id: m6-hardware
no: "08"
title: 하드웨어 점검과 장애 분석
subtitle: PCIe 링크, NVLink, Xid, DCGM
level: 실전
---

성능이 안 나오거나 작업이 이유 없이 죽었을 때 하드웨어를 어떻게 확인하는지, 평상시 헬스체크는
어떻게 걸어두는지를 본다.

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
