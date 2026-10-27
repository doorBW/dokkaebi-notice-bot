# 도깨비의세계 공지 알림 봇

도깨비의세계 공식 공지에 새 글이 올라오면 디스코드 채널에 **요약 + 원문 링크**를 보내 줍니다.
본문은 옮기지 않고, 짧은 요약과 [고객센터 공지](https://bbs.kakaogames.com/ko/1329429/notice/list) 링크만 보냅니다.

| 공지 | 웹훅 |
|---|---|
| 제목에 `업데이트`가 들어간 공지 | `DISCORD_WEBHOOK_UPDATE` |
| 그 밖의 공지 (점검, 운영 안내, 라이브 등) | `DISCORD_WEBHOOK_NOTICE` |

## 어디서 가져오나

**카카오게임즈 고객센터 공지 API**를 읽습니다. 게임 안 공지와 고객센터 공지 페이지가 쓰는 공개 API입니다.

```
GET https://web-api.kakaogame.com/supportreal/v2/notice?appId=1329429&country=KR&lang=ko&market=googlePlay&type=notice&cnt=30
GET https://web-api.kakaogame.com/supportreal/v2/notice/1329429/<seq>?offset=%2B09%3A00   (본문, base64 HTML)
```

- 15분마다 목록을 1번 요청하고, 새 글이 있을 때만 그 글 본문을 1번 더 요청합니다.
- 요청에는 봇임을 밝히는 User-Agent(`dokkaebi-notice-relay/1.0 (+저장소 주소)`)를 붙입니다.
- 접속이 실패하면 확인 간격을 2배씩 늘리고(최대 1시간), 6번 연속 실패하면 공지 채널에 경고를 한 번 보냅니다.
- 공식 커뮤니티(forum.kakaogames.com)의 API는 운영 측이 자동 접근을 막고 있어서 쓰지 않습니다.

## 새 글은 이렇게 판단합니다

1. 공지 목록 첫 페이지(30개, 고정글 포함)를 가져옵니다.
2. 이미 본 공지 번호(seq)는 `state.json`에 저장해 둡니다 (최근 500개).
3. 처음 실행할 때는 지금 보이는 공지를 전부 '이미 본 글'로 저장만 하고 보내지 않습니다 (도배 방지).
   이때의 시각도 기억합니다.
4. 다음 실행부터는 **저장된 목록에 없고, 게시 시각(begin_time)이 처음 실행 무렵 이후인 공지**를 새 글로 보고 보냅니다.
   - 예전 공지가 나중에 다시 고정돼도 보내지 않습니다.
   - 미리 써 두고 예약 게시한 공지는 번호가 작아도 게시 시각이 늦어서 새 글로 잡힙니다.

알아둘 점
- 공지를 **수정**한 것은 새 글로 보지 않습니다 (예: 제목에 `[완료]`, `[링크추가]`가 붙는 경우).
- 확인 간격 사이에 30개 넘게 올라오면 넘친 글은 놓칩니다.

## 1. 디스코드 웹훅 만들기

공지 채널과 업데이트 채널에 각각 하나씩 만듭니다.

1. 알림을 받을 채널 → ⚙️ 채널 편집 → **연동** → **웹후크** → **새 웹후크**
2. 이름/프로필 사진은 원하는 대로 (봇이 보낼 때 이름은 "도깨비의세계 공지"로 덮어씀)
3. **웹후크 URL 복사** → 공지 채널 것은 `DISCORD_WEBHOOK_NOTICE`, 업데이트 채널 것은 `DISCORD_WEBHOOK_UPDATE`입니다.
   비밀번호처럼 다뤄 주세요.

한 채널로 다 받고 싶으면 `DISCORD_WEBHOOK_URL` 하나만 넣어도 됩니다 (채널 전용 웹훅이 없을 때 대신 쓰임).

## 2. Claude API 키 (요약용)

[console.anthropic.com](https://console.anthropic.com) → API Keys에서 키를 만듭니다 → `ANTHROPIC_API_KEY`.
공지 1건 요약에 몇 원~수십 원 정도 듭니다. 키 없이도 봇은 돌아갑니다 (규칙 기반 요약).

## 3. 24시간 돌리기: Oracle Cloud 무료 서버

[deploy/ORACLE.md](deploy/ORACLE.md)에 순서대로 정리돼 있습니다 (가입 → 비용 잠금 → 서버 생성 → 접속 테스트 → 설치).

GitHub Actions(`.github/workflows/notice.yml`)도 들어 있지만 예약 실행은 꺼 두었습니다. 수동 실행만 남아 있어요.

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
.venv\Scripts\python bot.py --post-latest --dry-run  # 최근 공지 1건을 디스코드 대신 화면에 출력
.venv\Scripts\python bot.py --post-latest            # 최근 공지 1건을 실제로 보내서 연결 테스트
.venv\Scripts\python bot.py --loop                   # 15분마다 계속 확인 (--interval 초 단위로 조절)
```

`--post-latest`는 이미 본 글이어도 가장 최근에 게시된 공지 1개를 보내고, 나머지는 읽음 처리합니다.

## 설정값

| 이름 | 기본값 | 설명 |
|---|---|---|
| `DISCORD_WEBHOOK_NOTICE` | 없음 | 업데이트 외 공지를 보낼 채널 |
| `DISCORD_WEBHOOK_UPDATE` | 없음 | 제목에 '업데이트'가 들어간 공지를 보낼 채널 |
| `DISCORD_WEBHOOK_URL` | 없음 | 위 두 개가 없을 때 대신 쓰는 채널. 셋 다 없으면 화면에 출력만 |
| `ANTHROPIC_API_KEY` | 없음 | 있으면 Claude(`claude-opus-5-5`)로 요약 |
| `CHECK_INTERVAL` | `900` | `--loop` 확인 간격(초). 공지 API를 배려해 15분보다 줄이지 않는 걸 권장 |
| `USER_AGENT` | `dokkaebi-notice-relay/1.0 (+저장소 주소)` | 공지 API에 보내는 User-Agent |
| `CLAUDE_DAILY_LIMIT` | `30` | 하루 Claude 요약 최대 횟수 |
