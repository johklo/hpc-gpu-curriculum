---
id: m10-automation
no: "10"
title: 자동화와 프로비저닝
subtitle: Ansible로 노드를 찍어내고 장애 노드를 되돌리는 법
level: 실무
---

노드 200대를 손으로 맞추는 일은 처음 열 대까지만 버틴다. 규모가 커지면 사람의 기억과 손이
클러스터의 병목이 된다. 노드 구성을 코드로 적고, 그 코드로 프로비저닝과 복구를 반복 가능하게
만드는 방법을 이 모듈에 담는다. 도구는 Ansible을 쓰고, 예제는 Slurm과 GPU 노드를 가정한다.

## 손으로 고친 노드가 만드는 문제

클러스터를 처음 세울 때는 노드 열 대를 하나씩 손으로 설정한다. 드라이버를 올리고, 마운트를
걸고, 커널 파라미터를 손보고, 스케줄러에 등록한다. 열 대까지는 이 방식이 돈다. 문제는 노드가
200대가 되고, 그중 몇 대에서만 문제가 났을 때 그 몇 대를 그때그때 손으로 고치기 시작하는
순간이다. 고친 내용은 사람의 기억과 터미널 히스토리에만 남는다.

구성 드리프트(configuration drift)는 같은 이미지로 시작한 노드들이 시간이 지나며 조금씩
달라지는 현상이다. gpu07에서 작업이 자꾸 죽어 누군가 커널 파라미터 하나를 바꿔 급히 살렸다.
그 변경은 문서에 남지 않았다. 반년 뒤 gpu07을 재설치하면 그 파라미터는 사라지고, 같은 증상이
다시 난다. "그 노드만 이상하다"가 반복되는 이유는 노드가 이상해서가 아니라, 노드에 가한 변경이
어디에도 기록되지 않아서다.

| 드리프트가 쌓이는 경로 | 실제로 벌어지는 일 |
| --- | --- |
| 급한 손수정 | 장애를 급히 막으려 한 대만 고치고 나머지에 반영하지 않는다 |
| 부분 배포 | 새 드라이버를 절반만 올리다 중단해 버전이 섞인다 |
| 재설치 누락 | 노드를 다시 깔면서 그동안의 손수정이 통째로 날아간다 |
| 사람 의존 | 그 설정을 아는 사람이 휴가를 가면 아무도 손대지 못한다 |

같은 이미지로 깔았는데 특정 노드에서만 학습이 죽는 전형적 사례가 여기서 나온다. 컨테이너는
같고 데이터도 같은데 gpu13에서만 NCCL 통신이 멈춘다. 원인을 파보면 gpu13은 지난달 링크 장애로
누가 `net.core.rmem_max`를 손대고 원복하지 않은 노드였다. 사람이 노드마다 다른 상태를 기억으로
관리하는 한, 이런 사건은 규모에 비례해 늘어난다. 노드 200대의 상태를 사람의 머릿속이 아니라
코드로 옮기는 것이 자동화의 출발점이다.

## 선언형으로 관리한다는 것

명령형(imperative)은 무엇을 어떤 순서로 실행할지 적는 방식이다. `apt install`, `systemctl
restart`처럼 동작을 나열한다. 선언형(declarative)은 노드가 어떤 상태여야 하는지를 적고, 그
상태로 맞추는 일은 도구에 맡기는 방식이다. "드라이버 550이 깔려 있어야 한다"만 적으면, 이미
깔려 있으면 아무 일도 하지 않고 없으면 설치한다.

이 차이의 핵심이 멱등성(idempotency)이다. 같은 작업을 몇 번 돌려도 결과가 같아야 한다는 성질
이다. 셸 스크립트로 짠 명령형 코드는 두 번 돌리면 문제가 생기기 쉽다.

```bash
# 명령형. 두 번 돌리면 fstab에 같은 줄이 두 번 들어간다
echo "10.0.0.1:/scratch /scratch nfs defaults 0 0" >> /etc/fstab
mount -a
```

```yaml
# 선언형. 몇 번을 돌려도 fstab에 그 줄은 하나만 존재한다
- name: scratch 마운트 등록
  ansible.posix.mount:
    src: 10.0.0.1:/scratch
    path: /scratch
    fstype: nfs
    opts: defaults
    state: mounted
```

앞의 스크립트는 실행할 때마다 부작용이 쌓인다. 뒤의 태스크는 목표 상태를 적었으므로 몇 번을
돌려도 fstab에 그 줄은 하나다. 이미 마운트돼 있으면 `ok`로 지나가고, 없을 때만 `changed`로
바꾼다. 멱등성이 있으면 전체 플레이북을 언제든 다시 돌려 노드를 원하는 상태로 되돌릴 수 있다.

| 구분 | 명령형 | 선언형 |
| --- | --- | --- |
| 적는 대상 | 실행할 동작의 순서 | 노드가 가져야 할 최종 상태 |
| 재실행 | 부작용이 쌓일 수 있다 | 같은 결과로 수렴한다 |
| 드리프트 교정 | 사람이 차이를 찾아 손댄다 | 다시 돌리면 목표 상태로 맞춰진다 |
| 검토 | 무엇이 바뀌는지 읽기 어렵다 | 원하는 상태가 코드에 그대로 있다 |

IaC(Infrastructure as Code)는 인프라 구성을 코드로 적어 버전 관리하는 방식이다. HPC 운영에서
IaC의 값어치는 재현성과 감사에 있다. 노드 200대가 같은 코드에서 나오면 드리프트가 원천적으로
줄고, 어떤 노드가 왜 그렇게 설정됐는지는 git 이력이 답한다. 노드를 잃어도 코드에서 다시 찍어
내면 되므로, 노드 한 대의 상태가 특정 개인의 기억에 묶이지 않는다.

## Ansible의 구성 요소

Ansible은 SSH로 원격 노드에 접속해 정해진 상태로 맞추는 자동화 도구다. 노드에 별도 에이전트를
설치하지 않는다. 관리 노드에서 SSH로 붙어 파이썬 모듈을 잠깐 실행하고 빠지는 구조라, 노드
쪽에는 SSH와 파이썬만 있으면 된다. 에이전트가 없으니 에이전트 자체가 죽어 노드를 관리하지 못하는
상황이 없다. 처음 보는 독자를 위해 구성 요소를 하나씩 본다.

| 요소 | 역할 |
| --- | --- |
| 인벤토리 | 어떤 노드가 있고 어떻게 묶이는지 적은 목록 |
| 플레이북 | 어느 노드에 어떤 태스크를 돌릴지 적은 YAML 파일 |
| 롤 | 태스크·변수·템플릿·핸들러를 기능 단위로 묶은 재사용 단위 |
| 모듈 | 실제 작업을 수행하는 단위. `apt`, `copy`, `mount` 등 |
| 팩트 | 접속한 노드에서 자동으로 수집한 정보. OS, 메모리, GPU 등 |
| 핸들러 | 변경이 생겼을 때만 호출되는 태스크. 서비스 재시작에 쓴다 |

인벤토리는 관리 대상 노드의 목록이다. 가장 단순한 형태는 ini 파일이다.

```ini
[compute]
gpu[01:16]

[login]
login01

[compute:vars]
ansible_user=root
```

플레이북은 어느 노드 그룹에 무엇을 시킬지 적은 YAML이다. 가장 작은 플레이북 하나는 이렇다.

```yaml
- name: 시간 동기화 데몬 보장
  hosts: compute
  become: true
  tasks:
    - name: chrony 설치
      ansible.builtin.apt:
        name: chrony
        state: present

    - name: chrony 활성화
      ansible.builtin.service:
        name: chrony
        state: started
        enabled: true
```

롤(role)은 관련된 태스크·변수·템플릿을 정해진 폴더 구조로 묶어 재사용하는 단위다. `slurm`
롤을 만들면 여러 플레이북에서 불러 쓴다.

```text
roles/slurm/
├── tasks/main.yml       # 실행할 태스크
├── templates/slurm.conf.j2   # 설정 템플릿
├── handlers/main.yml    # 재시작 같은 조건부 동작
├── defaults/main.yml    # 기본 변수
└── files/               # 그대로 복사할 파일
```

변수는 여러 곳에서 정의할 수 있고, 겹치면 우선순위로 결정된다. 낮은 쪽부터 높은 쪽으로 덮어쓴다.

| 위치 | 우선순위 |
| --- | --- |
| 롤 `defaults/main.yml` | 가장 낮다. 기본값 용도 |
| 인벤토리 그룹 변수 | 그룹 단위 설정 |
| 인벤토리 호스트 변수 | 특정 노드만 다르게 |
| 플레이북 `vars` | 플레이북 안에서 지정 |
| `-e` 명령행 인자 | 가장 높다. 일회성 덮어쓰기 |

팩트(fact)는 접속한 노드에서 자동으로 모으는 정보다. 조건 분기에 쓴다.

```yaml
- name: 메모리가 큰 노드에만 적용
  ansible.builtin.debug:
    msg: "대용량 노드"
  when: ansible_memtotal_mb > 512000
```

이 여섯 조각이면 뒤 섹션의 플레이북을 다 읽는다. 인벤토리로 대상을 정하고, 플레이북과 롤로 할
일을 적고, 팩트로 노드마다 다른 조건을 처리하고, 핸들러로 변경 시에만 재시작한다.

## 인벤토리로 클러스터를 표현하기

인벤토리는 클러스터의 지도다. 노드를 역할별 그룹으로 묶으면 "GPU 노드 전부", "로그인 노드만"
같은 대상 지정이 한 줄로 끝난다. HPC 클러스터는 보통 로그인·컴퓨트·스토리지·관리 네 그룹으로
나뉘고, 컴퓨트는 다시 GPU 노드와 CPU 노드로 갈린다.

| 그룹 | 담는 노드 | 그룹 변수로 줄 것 |
| --- | --- | --- |
| login | 사용자 접속용 노드 | 홈 마운트, 사용자 셸 환경 |
| compute_gpu | GPU 컴퓨트 노드 | 드라이버 버전, GRES 설정 |
| compute_cpu | CPU 전용 컴퓨트 노드 | 코어 수, 메모리 한도 |
| storage | 파일서버 노드 | 익스포트 경로, 쿼터 |
| mgmt | 스케줄러 컨트롤러 등 | slurmctld, 모니터링 서버 |

YAML 인벤토리는 그룹의 상하 관계와 그룹 변수를 한 파일에 담기 좋다. GPU 노드와 CPU 노드를
나눈 실제 인벤토리는 이렇다.

```yaml
all:
  children:
    login:
      hosts:
        login01:
    compute_gpu:
      hosts:
        gpu[01:16]:
      vars:
        nvidia_driver_version: "550.90.07"
        slurm_gres: "gpu:8"
    compute_cpu:
      hosts:
        cpu[01:32]:
      vars:
        slurm_gres: ""
    storage:
      hosts:
        nfs01:
    mgmt:
      hosts:
        ctld01:
  vars:
    ansible_user: root
    ntp_server: 10.0.0.10
```

`gpu[01:16]`은 gpu01부터 gpu16까지 열여섯 대를 한 줄로 표현하는 범위 문법이다. 노드 수가 늘어도
줄이 늘지 않는다. 그룹 변수는 그 그룹 노드 전부에 적용되므로, GPU 노드의 드라이버 버전을 한
곳에서만 바꾸면 열여섯 대에 동일하게 반영된다.

호스트 패턴(host pattern)은 플레이북이나 명령행에서 대상을 좁히는 표현이다. 그룹 이름과 논리
연산을 섞어 쓴다.

```bash
# GPU 노드 전부
ansible compute_gpu -m ping
# GPU 노드 중 gpu01만 빼고
ansible 'compute_gpu:!gpu01' -m ping
# 컴퓨트 노드이면서 storage 그룹에도 든 노드 (교집합)
ansible 'compute_gpu:&storage' -m ping
```

인벤토리를 짜면 실제로 어떻게 묶였는지 눈으로 확인한다. `--graph`가 그룹 트리를 그려 준다.

```bash
ansible-inventory -i inventory.yml --graph
# @all:
#   |--@login:
#   |  |--login01
#   |--@compute_gpu:
#   |  |--gpu01
#   |  |--gpu02
#   ...
```

한 노드가 어떤 변수를 받는지 헷갈리면 `ansible-inventory --host gpu01 --vars`로 그 노드에
최종 적용되는 변수를 펼쳐 본다. 인벤토리가 클러스터의 실제 구조와 어긋나면 뒤의 모든 배포가
엉뚱한 노드로 간다. 인벤토리를 코드 저장소의 첫 검토 대상으로 두는 이유다.

## GPU 드라이버와 CUDA 배포

GPU 드라이버 버전은 클러스터 전체에서 고정해야 한다. 컨테이너 안의 CUDA 런타임은 호스트 드라이버
위에서 돈다. 드라이버가 노드마다 제각각이면, 같은 컨테이너가 어떤 노드에서는 돌고 어떤 노드에서는
`CUDA driver version is insufficient` 오류로 죽는다. 컨테이너의 CUDA 12.4를 쓰려면 호스트
드라이버가 그 이상을 지원해야 하므로, 드라이버 버전을 인벤토리에 박아 두고 전 노드를 그 버전에
맞춘다.

배포 롤의 태스크는 설치·검증·재부팅 순으로 짠다. 설치가 실패하면 그 노드에서 즉시 멈춰야 다음
검증 단계로 넘어가지 않는다.

```yaml
# roles/nvidia_driver/tasks/main.yml
- name: 기존 드라이버 모듈 상태 확인
  ansible.builtin.command: nvidia-smi --query-gpu=driver_version --format=csv,noheader
  register: smi
  failed_when: false
  changed_when: false

- name: 드라이버 패키지 설치
  ansible.builtin.apt:
    name: "nvidia-driver-{{ nvidia_driver_version.split('.')[0] }}"
    state: present
  when: nvidia_driver_version not in smi.stdout
  notify: reboot node
```

핸들러는 변경이 있었을 때만 재부팅을 건다. 이미 맞는 버전이면 재부팅하지 않는다.

```yaml
# roles/nvidia_driver/handlers/main.yml
- name: reboot node
  ansible.builtin.reboot:
    reboot_timeout: 600
```

배포 후 검증은 실제로 GPU가 보이는지 확인하는 태스크로 둔다. 설치만 되고 커널 모듈이 안 올라온
상태를 잡아낸다.

```yaml
- name: 재부팅 후 드라이버 검증
  ansible.builtin.command: nvidia-smi --query-gpu=driver_version --format=csv,noheader
  register: verify
  changed_when: false
  failed_when: nvidia_driver_version not in verify.stdout
```

핵심은 한 번에 전 노드를 건드리지 않는 것이다. 드라이버 배포는 재부팅을 동반하므로, 전 노드를
동시에 재부팅하면 클러스터가 통째로 내려간다. `serial`은 한 번에 몇 대씩 나눠 처리할지 정하는
키워드다. 롤링(rolling) 배포로 앞 묶음이 검증까지 끝나야 다음 묶음으로 넘어간다.

```yaml
- name: GPU 드라이버 롤링 배포
  hosts: compute_gpu
  become: true
  serial: 2          # 한 번에 2대씩
  max_fail_percentage: 0   # 한 대라도 실패하면 전체 중단
  roles:
    - nvidia_driver
```

`serial: 2`는 열여섯 대를 두 대씩 여덟 묶음으로 나눈다. `max_fail_percentage: 0`은 한 묶음에서
한 대라도 실패하면 나머지 묶음을 시작하지 않고 멈춘다. 배포 전에 그 묶음의 노드를 미리 드레인해
돌던 작업이 없게 하는 것이 안전하다.

| 검증 항목 | 확인 명령 | 통과 기준 |
| --- | --- | --- |
| 드라이버 버전 | `nvidia-smi --query-gpu=driver_version` | 목표 버전과 일치 |
| GPU 개수 | `nvidia-smi -L` 줄 수 | 노드의 물리 GPU 수와 일치 |
| ECC 상태 | `nvidia-smi -q -d ECC` | 예정한 설정과 일치 |
| 퍼시스턴스 | `nvidia-smi -q -d PERFORMANCE` | 퍼시스턴스 모드 켜짐 |

배포 후 GPU 개수가 물리 장착 수와 다르면 커널 모듈이 일부 GPU를 못 잡은 것이다. 이 노드는
드레인 상태로 두고 사람이 확인한다. 검증을 배포 롤 안에 넣어야, 배포가 끝났다는 말과 실제로 쓸
수 있다는 상태가 어긋나지 않는다.

## Slurm 클러스터 구성 자동화

Slurm 클러스터에서 `slurm.conf`는 모든 노드가 같은 사본을 가져야 한다. 컨트롤러와 컴퓨트 노드가
서로 다른 설정을 보면 노드 인식이 어긋나 노드가 `DOWN`으로 떨어진다. 설정 파일을 노드마다 손으로
복사하면 언젠가 한 대가 빠지므로, 템플릿 하나에서 전 노드로 뿌리는 방식을 쓴다.

설정을 Jinja2 템플릿으로 만들면 노드 목록 같은 변경 지점을 변수로 뽑아낼 수 있다.

```jinja
# roles/slurm/templates/slurm.conf.j2
ClusterName={{ slurm_cluster_name }}
SlurmctldHost={{ groups['mgmt'][0] }}

SelectType=select/cons_tres
GresTypes=gpu

{% for host in groups['compute_gpu'] %}
NodeName={{ host }} CPUs=128 RealMemory=1000000 Gres=gpu:8 State=UNKNOWN
{% endfor %}

PartitionName=train Nodes={{ groups['compute_gpu'] | join(',') }} MaxTime=72:00:00 Default=YES
```

이 템플릿은 인벤토리의 `compute_gpu` 그룹을 돌며 노드 정의를 자동으로 만든다. 노드를 인벤토리에
추가하면 설정에도 자동 반영되므로, 노드 목록이 인벤토리와 설정에서 어긋날 일이 없다.

munge는 Slurm 데몬 사이의 인증에 쓰는 키 기반 인증 서비스다. 모든 노드가 동일한 munge 키를
가져야 서로를 신뢰한다. 키가 다른 노드는 컨트롤러가 거부한다. 키는 컨트롤러에서 한 번 만들고
전 노드에 같은 파일로 뿌린다.

```yaml
# roles/slurm/tasks/main.yml
- name: munge 키 배포
  ansible.builtin.copy:
    src: files/munge.key
    dest: /etc/munge/munge.key
    owner: munge
    group: munge
    mode: "0400"
  notify: restart munge

- name: slurm.conf 배포
  ansible.builtin.template:
    src: slurm.conf.j2
    dest: /etc/slurm/slurm.conf
    mode: "0644"
  notify: reconfigure slurm
```

컨트롤러와 컴퓨트 노드는 역할이 다르므로 실행할 데몬도 다르다. 롤을 하나 두고 그룹으로 나눠
적용한다.

| 노드 역할 | 그룹 | 실행 데몬 |
| --- | --- | --- |
| 컨트롤러 | mgmt | slurmctld, munge |
| 컴퓨트 | compute_gpu, compute_cpu | slurmd, munge |
| DB(선택) | mgmt | slurmdbd |

설정을 바꾼 뒤에는 데몬을 재시작하지 않고 `scontrol reconfigure`로 다시 읽게 한다. 재시작은
돌던 작업에 영향을 줄 수 있지만, reconfigure는 설정만 다시 적용해 영향이 작다.

```yaml
# roles/slurm/handlers/main.yml
- name: restart munge
  ansible.builtin.service:
    name: munge
    state: restarted

- name: reconfigure slurm
  ansible.builtin.command: scontrol reconfigure
  delegate_to: "{{ groups['mgmt'][0] }}"
  run_once: true
```

`delegate_to`와 `run_once`는 이 명령을 컴퓨트 노드마다가 아니라 컨트롤러에서 한 번만 돌리게
한다. 설정이 전 노드에서 같다는 보장이 있으면, 노드가 `DOWN`으로 떨어지는 구축 초기의 흔한
문제 대부분이 사라진다.

## 노드 초기화 플레이북

새 노드를 받아 클러스터에 넣는 과정은 여러 단계로 이뤄진다. 이걸 한 번에 도는 초기화
플레이북으로 묶으면, 노드를 꽂고 인벤토리에 한 줄 넣고 플레이북 한 번 돌리는 것으로 끝난다.
단계는 순서가 중요하다. 앞 단계가 성립해야 뒤 단계가 의미를 갖기 때문이다.

![기본 설정부터 스케줄러 등록까지 단계마다 검증이 붙고 실패하면 멈춘다](img/automation-flow.svg)

| 순서 | 단계 | 왜 이 순서인가 | 검증 |
| --- | --- | --- | --- |
| 1 | 커널 파라미터 | 네트워크·메모리 튜닝이 뒤 단계의 전제 | `sysctl` 값 확인 |
| 2 | 스토리지 마운트 | 드라이버·이미지가 공유 경로에 있을 수 있다 | `mountpoint` 확인 |
| 3 | 시간 동기화 | 인증과 로그 정합성의 전제 | `chronyc tracking` |
| 4 | GPU 드라이버 | 스케줄러가 GRES로 GPU를 셀 수 있어야 한다 | `nvidia-smi` |
| 5 | 모니터링 에이전트 | 등록 직후부터 지표가 남아야 한다 | 에이전트 포트 응답 |
| 6 | 스케줄러 등록 | 앞이 다 서야 작업을 받아도 된다 | `sinfo`에 idle |

초기화 플레이북은 각 단계를 롤로 부르고, 단계마다 검증을 붙인다.

```yaml
- name: 신규 노드 초기화
  hosts: new_nodes
  become: true
  serial: 4
  roles:
    - kernel_tuning
    - storage_mounts
    - chrony
    - nvidia_driver
    - monitoring_agent
    - slurm
  post_tasks:
    - name: 스케줄러에 노드가 보이는지 확인
      ansible.builtin.command: sinfo -n {{ inventory_hostname }} -h -o "%t"
      delegate_to: "{{ groups['mgmt'][0] }}"
      register: nodestate
      changed_when: false
      failed_when: nodestate.stdout not in ['idle', 'mix', 'alloc']
```

커널 파라미터는 GPU 통신과 대용량 I/O에 맞춰 잡는다. `sysctl` 모듈이 값을 설정하고 유지되게 한다.

```yaml
# roles/kernel_tuning/tasks/main.yml
- name: 네트워크 버퍼 확대
  ansible.posix.sysctl:
    name: "{{ item.name }}"
    value: "{{ item.value }}"
    sysctl_set: true
    state: present
    reload: true
  loop:
    - { name: net.core.rmem_max, value: "268435456" }
    - { name: net.core.wmem_max, value: "268435456" }
    - { name: vm.swappiness, value: "0" }
```

마운트와 시간 동기화는 앞서 본 모듈을 재사용한다. 중요한 것은 마지막에 스케줄러에 노드가 idle로
보이는지까지 검증한다는 점이다. 드라이버까지 다 깔렸는데 스케줄러가 노드를 못 보면, 그 노드는
클러스터에 들어온 것이 아니다. `post_tasks`의 확인이 통과해야 초기화가 끝났다고 본다. 이 검증이
없으면 "설치는 됐는데 작업이 안 들어간다"는 신고가 뒤늦게 뜬다. 각 단계가 자기 검증을 품고 있어야
초기화 플레이북 한 번으로 노드를 신뢰할 수 있다.

## 장애 노드 복구와 롤백

자동 복구는 어디까지 허용할지 선을 그어야 한다. 재부팅으로 낫는 일시적 문제는 자동으로 처리해도
되지만, 하드웨어 고장은 자동으로 반복 재부팅해 봐야 상태만 나빠진다. 자동 복구의 범위를 표로
고정해 두면 판단이 흔들리지 않는다.

| 증상 | 자동 복구 허용 | 처리 |
| --- | --- | --- |
| 드라이버 모듈 언로드 | 허용 | 드레인 후 재부팅, 검증 후 복귀 |
| 일시적 슬럼드 응답 없음 | 허용 | slurmd 재시작, 실패 시 재부팅 1회 |
| Xid 하드웨어 오류 반복 | 불가 | 드레인 유지하고 사람에게 넘긴다 |
| 파일시스템 마운트 실패 | 조건부 | 재마운트 1회, 실패 시 사람 |
| ECC 정정 불가 오류 | 불가 | 작업 보존하고 하드웨어 팀 |

복구 플레이북은 드레인, 재부팅, 재검증 순으로 돈다. 복구 시도 횟수를 제한하고, 초과하면
자동으로 멈춰 사람에게 넘긴다.

```yaml
- name: 장애 노드 복구
  hosts: "{{ target }}"
  become: true
  serial: 1
  tasks:
    - name: 스케줄러에서 드레인
      ansible.builtin.command: >
        scontrol update NodeName={{ inventory_hostname }}
        State=DRAIN Reason="auto-recovery {{ ansible_date_time.iso8601 }}"
      delegate_to: "{{ groups['mgmt'][0] }}"

    - name: 재부팅
      ansible.builtin.reboot:
        reboot_timeout: 600

    - name: GPU 검증
      ansible.builtin.command: nvidia-smi -L
      register: gpus
      changed_when: false
      failed_when: gpus.stdout_lines | length != 8

    - name: 검증 통과 시에만 복귀
      ansible.builtin.command: >
        scontrol update NodeName={{ inventory_hostname }} State=RESUME
      delegate_to: "{{ groups['mgmt'][0] }}"
```

검증이 실패하면 마지막 복귀 태스크에 도달하지 못하므로 노드는 드레인 상태로 남는다. 자동 복구가
못 살린 노드를 억지로 큐에 되돌리지 않는다는 것이 이 설계의 안전장치다. 사람이 아침에 드레인
사유를 보고 하드웨어를 판단한다.

롤백을 위해 변경 전 상태를 남긴다. 설정 파일을 바꾸기 전에 타임스탬프 백업을 뜨면, 새 설정이
문제를 일으켰을 때 이전 파일로 되돌린다.

```yaml
- name: 설정 백업 후 배포
  ansible.builtin.copy:
    src: files/munge.key
    dest: /etc/munge/munge.key
    backup: true      # 기존 파일을 timestamp 붙여 남긴다
    owner: munge
    mode: "0400"
```

자동화가 상황을 악화시키는 경우가 있다. 원인이 공유 스토리지 장애인데 복구 플레이북이 전 노드를
동시에 재부팅하면, 멀쩡한 노드까지 내려가 장애가 커진다. 그래서 복구도 `serial: 1`로 한 대씩
처리하고, 같은 증상이 여러 노드에서 동시에 뜨면 자동 복구를 멈추고 공용 요소를 먼저 의심한다.
한 대의 문제는 그 노드를, 여러 대의 동시 문제는 공유 자원을 본다는 원칙이 자동화에도 그대로
적용된다.

## 바꾸기 전에 확인하기

운영 중인 클러스터에 플레이북을 돌리는 일은 위험하다. 실수 하나가 200대에 동시에 퍼진다. 그래서
바꾸기 전에 무엇이 바뀔지 미리 보는 습관이 필요하다. `--check`는 실제로 바꾸지 않고 무엇이 바뀔지
예고만 하는 모드다. `--diff`는 파일이 어떻게 달라지는지 줄 단위로 보여 준다.

```bash
# 실제 변경 없이 무엇이 바뀔지 예고
ansible-playbook site.yml --check --diff
```

한 대에서 먼저 시험한 뒤 전체로 넓힌다. `--limit`은 대상을 좁히는 인자다.

```bash
# gpu01 한 대에만 먼저 적용
ansible-playbook site.yml --limit gpu01
# 통과하면 GPU 노드 전체로
ansible-playbook site.yml --limit compute_gpu
```

태그를 붙이면 플레이북의 일부만 실행할 수 있다. 드라이버는 그대로 두고 모니터링 설정만 바꾸고
싶을 때 쓴다.

```yaml
- name: 모니터링 에이전트 설정
  ansible.builtin.template:
    src: agent.conf.j2
    dest: /etc/monitoring/agent.conf
  tags: [monitoring]
```

```bash
# monitoring 태그가 붙은 태스크만 실행
ansible-playbook site.yml --tags monitoring --limit gpu01 --check
```

| 확인 수단 | 하는 일 |
| --- | --- |
| `--check` | 바꾸지 않고 변경 예정만 표시 |
| `--diff` | 파일 변경 내용을 줄 단위로 표시 |
| `--limit` | 대상 노드를 한 대나 한 그룹으로 좁힘 |
| `--tags` | 플레이북의 일부 태스크만 실행 |
| `--start-at-task` | 특정 태스크부터 이어서 실행 |

운영 중 클러스터에서 절대 하지 말아야 할 것이 있다. 전 노드를 대상으로 `--check` 없이 처음
돌리는 것, 돌던 작업이 있는 노드를 드레인 없이 재부팅하는 것, 확인 안 된 플레이북을 `serial`
없이 전체에 거는 것이다. 새 플레이북은 항상 한 대에서 `--check`로 예고를 보고, 실제 적용을 한
대로 검증한 뒤, 묶음을 나눠 넓힌다. 이 순서를 건너뛰면 자동화가 사고를 자동으로 퍼뜨리는 도구가
된다.

## 변경을 기록하고 되돌리기

플레이북은 git 저장소에 둔다. 인벤토리, 롤, 플레이북, 그룹 변수를 한 저장소에 담으면 클러스터의
상태가 코드로 남고, 누가 언제 무엇을 왜 바꿨는지는 커밋 이력이 답한다. 저장소 구조는 역할별로
나눈다.

```text
cluster-ansible/
├── inventory/
│   ├── production.yml
│   └── staging.yml       # 테스트 클러스터
├── group_vars/
│   ├── compute_gpu.yml
│   └── all.yml
├── roles/
│   ├── nvidia_driver/
│   └── slurm/
├── site.yml              # 전체 배포 진입점
└── .ansible-lint         # 린트 규칙
```

변경 이력과 작업 기록을 잇는다. 커밋 메시지에 변경 사유와 관련 장애 번호를 적으면, 나중에 "이
설정이 왜 이렇게 됐나"라는 질문이 git blame으로 풀린다. gpu13의 커널 파라미터 사건이 반복되지
않는 이유가 여기 있다. 손수정 대신 커밋으로 바꾸면, 그 변경은 코드와 이력에 남아 재설치에도 살아
남는다.

CI에서 문법 검사와 테스트 적용을 자동으로 돌린다. `ansible-lint`는 문법 오류와 위험한 패턴을
잡아내는 린터다.

```bash
# 문법과 모범 사례 위반을 검사
ansible-lint site.yml
# 실행 전 구문 검사
ansible-playbook site.yml --syntax-check
```

CI 파이프라인은 병합 전에 린트와 테스트 클러스터 적용을 강제한다.

```yaml
# .github/workflows/ansible.yml
name: ansible-ci
on: [pull_request]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: 린트 실행
        run: ansible-lint site.yml
      - name: 구문 검사
        run: ansible-playbook site.yml --syntax-check
```

| 단계 | 검사 내용 | 통과 못 하면 |
| --- | --- | --- |
| 린트 | 문법과 위험 패턴 | 병합 차단 |
| 구문 검사 | 플레이북 구조 오류 | 병합 차단 |
| 테스트 클러스터 적용 | staging에서 실제 실행 | 검토 반려 |
| 승인 | 운영자 리뷰 | 프로덕션 배포 보류 |

프로덕션 인벤토리를 대상으로 하는 배포는 승인 절차를 둔다. 테스트 클러스터(staging)에서 먼저
돌려 문제가 없음을 확인하고, 최소 한 명의 운영자가 변경을 검토한 뒤 병합한다. 병합된 코드만
프로덕션에 적용한다. 이 절차가 있으면, 한 사람의 실수가 곧바로 200대에 퍼지는 경로가 막힌다.

## 무엇을 자동화하지 않을 것인가

자동화에는 비용이 있다. 플레이북을 짜고, 검증을 붙이고, 유지보수하는 시간이 든다. 한 번 쓰고 마는
작업을 자동화하면 만드는 데 든 시간을 회수하지 못한다. 노드 한 대에서 한 번만 할 진단 명령을
플레이북으로 만드는 것보다, 그냥 SSH로 들어가 실행하는 편이 빠르다. 자동화의 값어치는 반복
횟수와 노드 수에 비례한다.

사람의 판단이 필요한 지점은 자동화하지 않는다. 어느 노드를 언제 정비에서 뺄지, 장애의 근본
원인이 무엇인지, 하드웨어를 교체할지 수리할지는 상황을 읽어야 하는 결정이다. 자동화는 판단이
끝난 뒤의 반복 실행을 맡는 도구지, 판단 자체를 대신하지 못한다. 판단을 코드에 억지로 밀어 넣으면,
조건 분기가 끝없이 늘어난 플레이북이 되고, 그 플레이북을 읽는 일이 다시 사람의 부담이 된다.

| 항목 | 자동화가 위험한 이유 | 대신 |
| --- | --- | --- |
| 전 노드 동시 재부팅 | 클러스터가 통째로 내려간다 | `serial`로 나눠 처리 |
| 데이터 삭제 | 되돌릴 수 없다 | 목록 확인 후 사람이 실행 |
| 하드웨어 교체 판단 | 오진이면 멀쩡한 노드를 뺀다 | 사람이 진단 후 결정 |
| 원인 불명 장애 반복 복구 | 증상만 덮고 원인이 쌓인다 | 자동 복구 멈추고 조사 |
| 보안 키 재발급 | 순서 실수로 전 노드 인증 붕괴 | 검증된 절차로 단계 실행 |
| 파티션·쿼터 정책 변경 | 사용자 작업에 직접 영향 | 공지 후 승인받아 적용 |

자동화하지 않기로 한 것도 기록해 둔다. "이 작업은 수동으로 한다"는 결정과 그 이유를 문서에
남기면, 나중에 누가 그 부분을 자동화하려다 같은 위험을 다시 만나지 않는다. 자동화의 성숙도는
얼마나 많이 자동화했는가가 아니라, 무엇을 자동화하고 무엇을 사람에게 남길지 선을 얼마나 잘
그었는가로 드러난다. 반복되고 검증 가능한 일은 코드로, 판단과 되돌릴 수 없는 일은 사람에게
남기는 것이 원칙이다.
