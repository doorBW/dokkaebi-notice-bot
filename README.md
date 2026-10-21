# 도깨비의세계 공지 알림 봇

도깨비의세계 공식 포럼(forum.kakaogames.com/dokkaebi)에 **점검·업데이트 공지**가 올라오면
디스코드 채널에 **요약 + 링크**를 보내 줍니다.

- 포럼 내부 API에서 공지 게시판의 고정글과 최신글을 가져와 새 글만 골라냅니다.
- 제목이나 말머리에 `점검`, `업데이트`, `패치`가 들어간 글만 보냅니다 (`NOTICE_KEYWORDS`로 바꿀 수 있음).
- 요약은 Claude API로 만듭니다. API 키가 없거나 요약이 실패하면 일시·대상·보상 같은 줄을 뽑아서 대신 보냅니다.
- 처음 실행할 때는 이미 올라와 있는 글을 '읽음'으로만 표시하고 보내지 않습니다 (도배 방지).
- 포럼에 계속 접속이 안 되면(12회 연속) 채널에 경고를 한 번 보냅니다.

## 1. 디스코드 웹훅 만들기

1. 알림을 받을 채널 → ⚙️ 채널 편집 → **연동** → **웹후크** → **새 웹후크**
2. 이름/프로필 사진은 원하는 대로 (봇이 보낼 때 이름은 "도깨비의세계 공지"로 덮어씀)
3. **웹후크 URL 복사** → 이 주소가 `DISCORD_WEBHOOK_URL`입니다. 비밀번호처럼 다뤄 주세요.

## 2. Claude API 키 (요약용)

[console.anthropic.com](https://console.anthropic.com) → API Keys에서 키를 만듭니다 → `ANTHROPIC_API_KEY`.
공지 1건 요약에 몇 원~수십 원 정도 듭니다. 키 없이도 봇은 돌아갑니다 (규칙 기반 요약).

## 3. 무료로 24시간 돌리기: GitHub Actions

공개(public) 저장소면 GitHub Actions가 무료·무제한입니다. 10분마다 공지를 확인합니다.

1. 이 폴더를 GitHub 새 저장소(public)로 올립니다.
2. 저장소 → Settings → Secrets and variables → Actions
   - **Secrets**: `DISCORD_WEBHOOK_URL`, `ANTHROPIC_API_KEY`
   - (선택) **Variables**: `BOARD_CODES` (게시판 코드 직접 지정, 쉼표 구분), `NOTICE_KEYWORDS`
3. Actions 탭 → "도깨비의세계 공지 확인" → **Run workflow**로 한 번 실행해 로그를 확인합니다.
   첫 실행 로그에 `처음 실행: 기존 글 N개를 읽음 처리`가 보이면 정상입니다.

주의할 점
- GitHub 예약 실행은 몇 분씩 늦게 돌 때가 많습니다 (보통 10~20분 안에 도착).
- 공개 저장소에서 60일 동안 커밋이 없으면 GitHub이 예약 실행을 멈춥니다. 메일이 오면 Actions 탭에서 다시 켜면 됩니다.
- 비공개 저장소는 월 2,000분 무료라 10분 간격이면 모자랍니다. 비공개로 쓰려면 cron을 `*/30 * * * *`로 바꾸세요.
- GitHub 서버는 해외에 있습니다. 포럼이 해외 접속을 막는다면 로그에 `HTTP 403`이 반복됩니다.
  그때는 아래 '로컬/국내 서버' 방식을 쓰세요 (Oracle Cloud 무료 VM은 춘천 리전 선택 가능).

## 4. 내 PC나 서버에서 돌리기

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

같은 폴더에 `.env` 파일을 만듭니다:

```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
ANTHROPIC_API_KEY=sk-ant-...
```

```bash
.venv\Scripts\python bot.py --list-boards            # 게시판 코드 목록 보기
.venv\Scripts\python bot.py --post-latest --dry-run  # 최근 공지 1건을 디스코드 대신 화면에 출력
.venv\Scripts\python bot.py --post-latest            # 최근 공지 1건을 실제로 보내서 연결 테스트
.venv\Scripts\python bot.py --loop                   # 5분마다 계속 확인 (--interval 초 단위로 조절)
```

`--post-latest`는 아직 `state.json`이 없을 때(처음 실행)만 동작합니다. 다시 테스트하려면 `state.json`을 지우세요.

## 설정값

| 이름 | 기본값 | 설명 |
|---|---|---|
| `DISCORD_WEBHOOK_URL` | (필수) | 없으면 보내지 않고 화면에 출력만 |
| `ANTHROPIC_API_KEY` | 없음 | 있으면 Claude(`claude-opus-5-5`)로 요약 |
| `NOTICE_KEYWORDS` | `점검,업데이트,패치` | 제목/말머리에 들어가야 보냄. 빈 값이면 공지 전부 |
| `BOARD_CODES` | 자동 | 비우면 이름에 `공지`/`업데이트`/`점검`이 들어간 게시판을 자동 선택 |
| `CHECK_INTERVAL` | `300` | `--loop` 확인 간격(초) |
