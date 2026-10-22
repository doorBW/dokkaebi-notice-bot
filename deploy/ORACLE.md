# Oracle Cloud 무료 서버에 봇 올리기

순서가 중요해요. **잠금 장치(2~4단계)를 먼저 걸고**, 서버를 만든 뒤 **포럼 접속 테스트(6단계)가 통과하면** 그때 종량제로 바꾸고 봇을 설치합니다.
테스트에서 막히면 종량제 전환 없이 무료 계정 그대로 접으면 돼요.

---

## 0. Claude API 월 한도 (Oracle과 별개)

[console.anthropic.com](https://console.anthropic.com) → Settings → Limits(또는 Billing)에서 **월 사용 한도**를 작게 걸어 둡니다 (예: $5).
봇에도 하루 Claude 요약 30회 상한이 들어 있지만(`CLAUDE_DAILY_LIMIT`), 여기서 한 번 더 막는 게 확실합니다.

## 1. 가입

1. https://www.oracle.com/cloud/free/ → **Start for free**
2. **Home Region**은 가입할 때 한 번만 고를 수 있어요. 무료 서버는 홈 리전에서만 만들 수 있습니다.
   - 실제 운영 서버는 **Japan East (Tokyo), `ap-tokyo-1`** 입니다 (가입 당시 한국 리전이 목록에 없었음).
   - 포럼은 나라가 아니라 User-Agent와 일부 IP를 보고 막기 때문에 리전은 크게 상관없습니다. 아래 정책의 `ap-seoul-1`은 고른 리전 ID로 바꾸세요.
3. 카드 본인 확인을 마치면 무료 계정(Free Tier)이 만들어집니다. 이 상태에서는 요금이 나가지 않아요.

## 2. 2단계 인증(MFA) 켜기 — 계정 탈취 대비

오른쪽 위 프로필 아이콘 → 내 프로필 → **Multi-factor authentication** → 휴대폰 인증 앱(Oracle Mobile Authenticator, Google Authenticator 등)으로 등록.

## 3. 할당량(Quota)으로 유료 자원 생성 막기

메뉴 ☰ → **Governance & Administration** → **Tenancy Management** → **Quota policies** → **Create quota**

- 이름: `free-only`
- 정책 내용: 아래를 **한 정책 안에 통째로** 붙여 넣습니다. `ap-seoul-1` 세 군데를 홈 리전 ID(도쿄면 `ap-tokyo-1`)로 바꾸세요.

```
zero compute-core quotas in tenancy
set compute-core quota standard-e2-micro-core-count to 2 in tenancy where request.region = ap-seoul-1
zero compute-memory quotas in tenancy
zero block-storage quotas in tenancy
set block-storage quota total-storage-gb to 200 in tenancy where request.region = ap-seoul-1
set block-storage quota backup-count to 5 in tenancy where request.region = ap-seoul-1
zero load-balancer quotas in tenancy
zero database quotas in tenancy
zero filesystem quotas in tenancy
zero container-engine quotas in tenancy
zero object-storage quotas in tenancy
```

뜻: 서버는 무료 AMD Micro만 최대 2대(무료 한도와 같음), 디스크는 무료 한도(200GB, 백업 5개)까지만, 그 밖의 유료가 될 수 있는 서비스(로드밸런서, DB, 파일 스토리지, 쿠버네티스, 오브젝트 스토리지)는 전부 생성 금지.
같은 정책 안에서는 아래 줄이 위 줄을 덮어쓰기 때문에 `zero` 다음 `set` 순서가 중요해요.
적용까지 최대 10분 걸립니다. 저장할 때 오류가 나면 오류 문구를 그대로 알려 주세요.

## 4. 예산 알림 걸기 — 혹시 돈이 나가면 바로 알기

메뉴 ☰ → **Billing & Cost Management** → **Budgets** → **Create Budget**

- Budget Scope: **Compartment**, Target Compartment: 루트(계정 이름)
- Schedule: **Monthly**
- Budget Amount: **1** (계정 통화 단위. 원화 계정이면 1,000 정도로)
- Alert Rule: Threshold Metric **Actual Spend**, Threshold Type **Percentage of Budget**, Threshold **1** → 1원이라도 실제 청구가 생기면 메일
- Email Recipients: 받을 메일 주소

예산은 알림만 보내고 결제를 멈추지는 않아요. 알림은 하루 한 번 확인됩니다. 무료 계정 상태에서 만들 수 없게 막혀 있으면 8단계(종량제 전환) 뒤에 만드세요.

## 5. 서버 만들기

메뉴 ☰ → **Compute** → **Instances** → **Create instance**

- Image: **Canonical Ubuntu 24.04**
- Shape: **VM.Standard.E2.1.Micro** (`Always Free-eligible` 표시가 있는 것)
- Networking: 새 VCN + 공개 서브넷 만들기, **Public IPv4 주소 할당** 켜기
- Add SSH keys: **Generate a key pair for me** → **Save private key** 로 키 파일 저장
  - 저장한 파일을 `C:\Users\doorB\.ssh\oracle-notice-bot.key` 로 옮겨 주세요
- Boot volume: 기본값(약 50GB) 그대로. 키우지 마세요.

만들어지면 인스턴스 화면의 **Public IP address**를 알려 주세요. 그다음부터는 제가 이 PC에서 접속해서 진행할 수 있어요.

## 6. 포럼 접속 테스트 (가장 중요)

서버에 접속해서 아래를 실행합니다 (제가 대신 실행해도 됩니다).

```bash
curl -s -o /dev/null -w "%{http_code}\n" -A "notice-relay/1.0" "https://forum-api.kakaogames.com/v1/dokkaebi/boards?lang=ko"
```

- `200` → 통과. 7단계로.
- `403` → 이 서버 IP가 막혀 있거나 포럼 방화벽 규칙이 바뀐 것. 종량제 전환하지 말고 멈추세요.
  (curl 기본값·python-requests·PC 브라우저 User-Agent는 원래 403이 납니다. 반드시 위 명령 그대로 시험하세요.)

## 7. 종량제(Pay As You Go) 전환 — 놀고 있는 서버 자동 정지 막기

무료 계정은 7일간 CPU·네트워크 사용이 20% 미만이면 서버가 정지될 수 있어요. 이 봇은 거의 항상 그 상태라 매주 꺼질 수 있습니다.
메뉴 ☰ → **Billing & Cost Management** → **Upgrade and Manage Payment** → **Pay As You Go**로 전환.
전환해도 무료 자원은 계속 0원이고, 3단계 할당량이 유료 자원 생성을 막아 줍니다.

## 8. 봇 설치

서버에서:

```bash
curl -fsSL https://raw.githubusercontent.com/doorBW/dokkaebi-notice-bot/main/deploy/setup.sh | bash
nano ~/dokkaebi-notice-bot/.env        # 웹훅 2개 + Claude API 키 입력 후 Ctrl+O, Enter, Ctrl+X
curl -fsSL https://raw.githubusercontent.com/doorBW/dokkaebi-notice-bot/main/deploy/setup.sh | bash
```

설치 스크립트가 하는 일: 비밀번호·root SSH 로그인 금지, 보안 업데이트 자동 설치, 봇 설치, 재부팅해도 자동으로 켜지는 서비스 등록.
(방화벽은 Oracle 기본 설정이 SSH만 열어 둡니다. Oracle 안내에 따라 Ubuntu의 UFW는 켜지 마세요 — 부팅이 안 될 수 있어요.)

연결 테스트로 게시판마다 최근 글 1개를 보내 보려면:

```bash
cd ~/dokkaebi-notice-bot && .venv/bin/python bot.py --post-latest
```

로그 보기: `journalctl -u dokkaebi-notice-bot -f`

---

## 그래도 남는 비용 위험

| 상황 | 막는 장치 | 남는 위험 |
|---|---|---|
| 실수로 유료 서버·디스크·DB 생성 | 3단계 할당량 | 없음 (할당량을 직접 풀지 않는 한) |
| 계정 탈취 | 2단계 MFA, 4단계 예산 알림 | MFA까지 뚫리면 할당량도 풀 수 있음 |
| 서버 해킹 후 트래픽 남용 (월 10TB 초과분 GB당 $0.025) | SSH 키 전용 접속, SSH 외 포트 닫힘 | 이론상 최대 약 6TB 초과 ≈ $150 |
| Oracle 무료 정책 변경 | 4단계 예산 알림 | 알림 받을 때까지의 금액 |
| Claude 요약 비용 | 0단계 월 한도, 봇의 하루 30회 상한 | 한도 금액까지 |
