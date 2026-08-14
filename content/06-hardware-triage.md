---
id: m6-hardware
no: "06"
title: 하드웨어 점검과 장애 분석
subtitle: PCIe 링크, NVLink, Xid, DCGM
level: 실전
---

성능이 안 나오거나 작업이 죽었을 때 하드웨어 쪽을 확인하는 방법을 다룬다. 평상시 헬스체크
체계를 만드는 방법도 함께 정리한다.

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

자주 보는 코드와 의미는 다음과 같다.

| Xid | 의미 | 대개의 원인 |
| --- | --- | --- |
| 13 | 그래픽 엔진 예외 | 애플리케이션의 잘못된 메모리 접근 |
| 31 | GPU 메모리 페이지 폴트 | 커널 코드의 버그. 사용자 코드 쪽인 경우가 많다 |
| 43 | 소프트웨어에 의한 중단 | 앞선 오류의 후속. 원인은 다른 코드에 있다 |
| 48 | 정정 불가 ECC 오류 | 하드웨어. 페이지 리타이어 또는 교체 대상 |
| 63, 64 | 페이지 리타이어 | ECC 오류 후 해당 페이지를 격리했다 |
| 74 | NVLink 오류 | 링크나 NVSwitch 문제 |
| 79 | GPU가 버스에서 사라짐 | 전원, 과열, 물리 접속. 심각한 신호다 |

판단의 기준은 재현성과 범위다. 특정 사용자 코드에서만 나면 애플리케이션 문제일 가능성이 높고,
같은 노드에서 사용자와 무관하게 반복되면 하드웨어를 의심한다. 여러 노드에서 동시에 나면 드라이버
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

## 성능 저하 진단

오류 없이 느려지는 경우가 조사하기 더 까다롭다. 스로틀링 여부부터 확인한다.

```bash
nvidia-smi -q -d PERFORMANCE | grep -A10 "Clocks Throttle Reasons"
nvidia-smi --query-gpu=index,clocks.sm,clocks.max.sm,temperature.gpu,power.draw \
           --format=csv -l 5
```

스로틀 사유별 대응은 다음과 같다.

| 사유 | 의미 | 대응 |
| --- | --- | --- |
| `SW Power Cap` | 전력 상한에 걸렸다 | 상한 확인. 의도한 설정인지 본다 |
| `HW Thermal Slowdown` | 온도가 한계에 닿았다 | 냉각, 먼지, 랙 배치를 본다 |
| `HW Power Brake` | 전원 공급 문제 | 전원 케이블과 PSU 용량을 본다 |
| `SW Thermal Slowdown` | 드라이버가 온도로 낮췄다 | 위와 같으나 여유가 조금 있다 |

스로틀이 없는데 느리다면 GPU 밖을 본다. GPU 사용률이 낮으면 데이터 로더나 전처리가 병목이고,
사용률은 높은데 처리량이 낮으면 통신이나 커널 효율 문제다. 모듈 03의 NUMA와 네트워크 항목을
함께 확인한다.
