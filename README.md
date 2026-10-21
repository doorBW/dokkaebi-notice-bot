# 도깨비의세계 공지 알림 봇

도깨비의세계 공식 포럼(forum.kakaogames.com/dokkaebi)의 **공지사항**·**업데이트** 게시판에 새 글이 올라오면
디스코드 채널에 **요약 + 링크**를 보내 줍니다. 글 내용으로 거르지 않고 새 글은 전부 보냅니다.

| 포럼 게시판 | 웹훅 |
|---|---|
| 이름에 `업데이트`가 들어간 게시판 | `DISCORD_WEBHOOK_UPDATE` |
| 이름에 `공지`가 들어간 게시판 (공지사항) | `DISCORD_WEBHOOK_NOTICE` |

- 요약은 Claude API로 만듭니다. API 키가 없거나 요약이 실패하면 일시·대상·보상 같은 줄을 뽑아서 대신 보냅니다.
- 포럼에 계속 접속이 안 되면(12회 연속) 공지 채널에 경고를 한 번 보냅니다.

### 새 글은 이렇게 판단합니다

1. 실행할 때마다 각 게시판의 고정글과 첫 페이지(18개)를 가져옵니다.
2. 이미 본 글 번호는 `state.json`에 게시판별로 저장해 둡니다 (최근 300개).
3. 처음 실행할 때는 지금 보이는 글을 전부 '이미 본 글'로 저장만 하고 보내지 않습니다 (도배 방지).
   이때 본 가장 큰 글 번호도 함께 기억합니다.
4. 다음 실행부터는 **저장된 목록에 없고, 글 번호가 처음 본 가장 큰 번호보다 큰 글**을 새 글로 보고 보냅니다.
   그래서 예전 글이 나중에 고정글로 올라와도 다시 보내지 않습니다.

알아둘 점
- 글을 **수정**한 것은 새 글로 보지 않습니다 (예: 기존 점검 공지에 '점검 연장'을 덧붙인 경우).
- 확인 간격(10분) 사이에 한 게시판에 18개 넘게 올라오면 넘친 글은 놓칩니다.
- GitHub Actions의 `state.json` 캐시가 지워지면 처음 실행처럼 다시 저장만 하고 시작합니다.
  그 사이에 올라온 글은 보내지 않지만, 옛 글이 한꺼번에 쏟아지지도 않습니다.

## 1. 디스코드 웹훅 만들기

공지 채널과 업데이트 채널에 각각 하나씩 만듭니다.

1. 알림을 받을 채널 → ⚙️ 채널 편집 → **연동** → **웹후크** → **새 웹후크**
2. 이름/프로필 사진은 원하는 대로 (봇이 보낼 때 이름은 "도깨비의세계 공지"로 덮어씀)
3. **웹후크 URL 복사** → 공지 채널 것은 `DISCORD_WEBHOOK_NOTICE`, 업데이트 채널 것은 `DISCORD_WEBHOOK_UPDATE`입니다.
   비밀번호처럼 다뤄 주세요.

한 채널로 다 받고 싶으면 `DISCORD_WEBHOOK_URL` 하나만 넣어도 됩니다 (게시판 전용 웹훅이 없을 때 대신 쓰임).
포럼 접속이 계속 실패할 때 보내는 경고는 공지 채널로 갑니다.

## 2. Claude API 키 (요약용)

[console.anthropic.com](https://console.anthropic.com) → API Keys에서 키를 만듭니다 → `ANTHROPIC_API_KEY`.
공지 1건 요약에 몇 원~수십 원 정도 듭니다. 키 없이도 봇은 돌아갑니다 (규칙 기반 요약).

## 3. 24시간 돌리기: Oracle Cloud 무료 서버

[deploy/ORACLE.md](deploy/ORACLE.md)에 순서대로 정리돼 있습니다 (가입 → 비용 잠금 → 서버 생성 → 포럼 접속 테스트 → 설치).

GitHub Actions(`.github/workflows/notice.yml`)도 들어 있지만, 포럼 API가 GitHub 서버 IP를 막고 있어서(HTTP 403)
예약 실행은 꺼 두었습니다. 수동 실행만 남아 있어요.

### 비용 안전장치 (봇 자체)

- 디스코드 전송이 실패해도 요약은 다시 만들지 않고, 만들어 둔 메시지를 다음 확인 때 다시 보냅니다. 12번 실패하면 그 글은 포기합니다.
- Claude 요약은 하루 최대 `CLAUDE_DAILY_LIMIT`(기본 30)회. 넘으면 규칙 기반 요약으로 보냅니다.

## 4. 내 PC나 서버에서 돌리기

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

같은 폴더에 `.env` 파일을 만듭니다:

```
DISCORD_WEBHOOK_NOTICE=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_UPDATE=https://discord.com/api/webhooks/...
ANTHROPIC_API_KEY=sk-ant-...
```

```bash
.venv\Scripts\python bot.py --list-boards            # 게시판 목록과 각 게시판이 어느 웹훅으로 가는지 보기
.venv\Scripts\python bot.py --post-latest --dry-run  # 최근 공지 1건을 디스코드 대신 화면에 출력
.venv\Scripts\python bot.py --post-latest            # 최근 공지 1건을 실제로 보내서 연결 테스트
.venv\Scripts\python bot.py --loop                   # 5분마다 계속 확인 (--interval 초 단위로 조절)
```

`--post-latest`는 이미 본 글이어도 게시판마다 가장 최근 글 1개를 보내고, 나머지는 읽음 처리합니다.
GitHub에서는 Actions 탭 → "도깨비의세계 공지 확인" → **Run workflow**에서
"게시판마다 가장 최근 글 1개를 보내보기"를 체크하고 실행하면 같은 동작을 합니다.

## 설정값

| 이름 | 기본값 | 설명 |
|---|---|---|
| `DISCORD_WEBHOOK_NOTICE` | 없음 | 공지사항 게시판 글을 보낼 채널 |
| `DISCORD_WEBHOOK_UPDATE` | 없음 | 업데이트 게시판 글을 보낼 채널 |
| `DISCORD_WEBHOOK_URL` | 없음 | 위 두 개가 없을 때 대신 쓰는 채널. 셋 다 없으면 화면에 출력만 |
| `ANTHROPIC_API_KEY` | 없음 | 있으면 Claude(`claude-opus-5-5`)로 요약 |
| `BOARD_CODES` | 자동 | 비우면 이름에 `공지`/`업데이트`가 들어간 게시판을 자동 선택 |
| `CHECK_INTERVAL` | `300` | `--loop` 확인 간격(초) |
| `CLAUDE_DAILY_LIMIT` | `30` | 하루 Claude 요약 최대 횟수 |
