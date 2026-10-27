"""도깨비의세계 공지(카카오게임즈 고객센터 공지)의 새 글을 디스코드 채널로 전달하는 봇.

게임 안 공지와 https://bbs.kakaogames.com/ko/1329429/notice/list 가 쓰는 공개 공지 API 를 읽는다.
제목에 '업데이트'가 들어간 공지는 업데이트 채널로, 나머지는 공지 채널로 보낸다.

한 번 실행하면 새 공지를 확인해 웹훅으로 보내고 끝난다.
--loop 를 주면 계속 돌면서 일정 간격으로 확인한다 (상시 켜둔 서버용).
"""

import argparse
import base64
import binascii
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
STATE_PATH = Path(os.environ.get("STATE_PATH", ROOT / "state.json"))

APP_ID = "1329429"  # 도깨비의세계
API = "https://web-api.kakaogame.com/supportreal/v2"
LIST_PARAMS = {"appId": APP_ID, "country": "KR", "lang": "ko", "market": "googlePlay",
               "type": "notice", "cnt": 30}
NOTICE_URL = "https://bbs.kakaogames.com/ko/" + APP_ID + "/notice/detail?id={seq}"
HEADERS = {
    "User-Agent": os.environ.get(
        "USER_AGENT", "dokkaebi-notice-relay/1.0 (+https://github.com/doorBW/dokkaebi-notice-bot)"),
    "Accept": "application/json",
}

# 제목에 들어간 단어 → (채널 이름, 웹훅 환경변수). 위에서부터 먼저 맞는 것, 아무것도 안 맞으면 마지막 줄.
ROUTES = [
    ("업데이트", "업데이트", "DISCORD_WEBHOOK_UPDATE"),
    ("", "공지사항", "DISCORD_WEBHOOK_NOTICE"),
]

SEEN_LIMIT = 500          # 기억할 공지 번호 수
MAX_BACKOFF = 3600        # 공지 API 접속이 계속 실패할 때 확인 간격을 최대 이만큼(초)까지 늘린다
FAIL_ALERT_AFTER = 6      # 연속 실패가 이만큼 쌓이면 디스코드에 한 번 알림
SEND_MAX_TRIES = 12       # 디스코드 전송이 이만큼 실패하면 그 글은 포기 (요약은 다시 만들지 않음)
CLAUDE_DAILY_LIMIT = int(os.environ.get("CLAUDE_DAILY_LIMIT", 30))  # 하루 Claude 요약 최대 횟수
SUMMARY_MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """너는 모바일 MMORPG '도깨비의세계' 공식 공지를 디스코드 문파 채널용으로 요약한다.
- 한국어, 3~6줄의 글머리표(•)로만 답한다. 인사말이나 머리말은 쓰지 않는다.
- 점검 공지면 점검 일시(시작~종료), 대상 서버, 점검 중 제한 사항, 보상을 우선 적는다.
- 업데이트 공지면 핵심 신규 콘텐츠와 변경점, 이벤트 기간, 보상을 우선 적는다.
- 그 밖의 공지(이벤트, 운영 안내 등)는 핵심 내용, 기간, 대상, 보상을 적는다.
- 공지에 없는 내용은 추측하지 않는다. 날짜와 시간은 공지 표기 그대로 쓴다."""


def load_dotenv():
    """로컬 실행용: 같은 폴더의 .env 를 환경변수로 읽는다 (이미 있는 값은 덮지 않음)."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# ---------------------------------------------------------------- notice API

class ApiError(Exception):
    pass


def api_get(path, params=None):
    try:
        r = requests.get(f"{API}{path}", params=params, headers=HEADERS, timeout=20)
    except requests.RequestException as e:
        raise ApiError(f"{path}: {e}") from e
    if r.status_code != 200:
        raise ApiError(f"{path}: HTTP {r.status_code}")
    try:
        data = r.json()
    except ValueError as e:
        raise ApiError(f"{path}: JSON 아님") from e
    if str(data.get("code", 200)) != "200":
        raise ApiError(f"{path}: code {data.get('code')} {data.get('message', '')}")
    return data


def fetch_notices():
    """공지 목록 첫 페이지. 고정글(is_top=1)이 앞에 오고 그다음 최신순이다."""
    return api_get("/notice", LIST_PARAMS).get("noticeList", [])


def fetch_notice_detail(seq):
    return api_get(f"/notice/{APP_ID}/{seq}", {"offset": "+09:00"})


def decode_content(content):
    """본문은 base64 로 인코딩한 HTML 이다."""
    try:
        return base64.b64decode(content or "").decode("utf-8", "replace")
    except (binascii.Error, ValueError):
        return content or ""


def route_for(title):
    for word, channel, env_name in ROUTES:
        if word in title:
            return channel, env_name
    return ROUTES[-1][1], ROUTES[-1][2]


def webhook_for(channel):
    """채널 전용 웹훅이 없으면 DISCORD_WEBHOOK_URL 로 보낸다."""
    env_name = next((e for _, c, e in ROUTES if c == channel), None)
    return (env_name and os.environ.get(env_name)) or os.environ.get("DISCORD_WEBHOOK_URL", "")


# ---------------------------------------------------------------- HTML -> text

class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol"}

    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_endtag(self, tag):
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(raw):
    p = _TextExtractor()
    p.feed(html.unescape(raw or ""))
    text = "".join(p.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------- summary

def summarize_with_claude(title, body):
    import anthropic

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=SUMMARY_MODEL,
        max_tokens=2000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"제목: {title}\n\n본문:\n{body}"}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("요약 거절됨")
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        raise RuntimeError("빈 요약")
    return text


KEY_LINE = re.compile(r"(일시|기간|시간|대상|서버|보상|내용|~|\d{1,2}:\d{2})")


def summarize_by_rules(body):
    """API 키가 없거나 요약이 실패했을 때: 일시/대상/보상 같은 줄을 우선 뽑는다."""
    lines = [l.strip(" -•·▶■□◆◇※") for l in body.splitlines()]
    lines = [l for l in lines if 4 <= len(l) <= 160]
    key = [l for l in lines if KEY_LINE.search(l)][:6]
    chosen = key or lines[:5]
    return "\n".join(f"• {l}" for l in chosen)


def summarize(title, body, use_claude=True):
    """(요약문, Claude 호출 여부) 를 돌려준다."""
    if len(body) < 30:
        return "• 본문이 이미지 위주라 요약할 글이 없어요. 링크에서 확인해 주세요.", False
    if use_claude and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return summarize_with_claude(title, body), True
        except Exception as e:  # 요약 실패로 공지 전달까지 막히면 안 됨
            print(f"[경고] Claude 요약 실패, 규칙 기반으로 대체: {e}", file=sys.stderr)
            return summarize_by_rules(body), True
    return summarize_by_rules(body), False


# ---------------------------------------------------------------- discord

def notice_color(title, channel=""):
    if "점검" in title:
        return 0xE67E22
    if "업데이트" in channel or "업데이트" in title or "패치" in title:
        return 0x3498DB
    return 0x95A5A6


def parse_time(value):
    """공지 API 시각은 ISO 형식 UTC 다 (예: 2026-10-27T13:21:00.000Z)."""
    if value in (None, ""):
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def build_message(notice, detail, use_claude=True):
    """(채널 이름, 디스코드 payload, Claude 호출 여부) 를 돌려준다. 본문은 옮기지 않고 요약과 링크만 보낸다."""
    title = str(detail.get("title") or notice.get("title") or "제목 없음").strip()
    channel, _ = route_for(title)
    body = html_to_text(decode_content(detail.get("content")))
    summary, used_claude = summarize(title, body, use_claude)

    embed = {
        "title": title[:256],
        "url": NOTICE_URL.format(seq=notice["seq"]),
        "description": summary[:4000],
        "color": notice_color(title, channel),
        "footer": {"text": f"도깨비의세계 · {channel}"},
    }
    when = parse_time(notice.get("begin_time") or detail.get("begin_time"))
    if when:
        embed["timestamp"] = when.isoformat()
    return channel, {"username": "도깨비의세계 공지", "embeds": [embed]}, used_claude


def send_discord(payload, webhook, dry_run=False):
    if dry_run or not webhook:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for _ in range(3):
        r = requests.post(webhook, json=payload, timeout=20)
        if r.status_code == 429:
            time.sleep(float(r.json().get("retry_after", 2)))
            continue
        r.raise_for_status()
        return
    raise RuntimeError("디스코드 전송 실패 (429 반복)")


# ---------------------------------------------------------------- main loop

def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def claude_allowed(state):
    usage = state.get("claude_usage", {})
    today = datetime.now().strftime("%Y-%m-%d")
    if usage.get("date") != today:
        state["claude_usage"] = usage = {"date": today, "count": 0}
    return usage["count"] < CLAUDE_DAILY_LIMIT


def flush_outbox(state, dry_run):
    """보낼 메시지를 전송한다. 실패한 건 다음 실행 때 같은 내용으로 다시 보낸다."""
    remaining = []
    for item in state.get("outbox", []):
        try:
            send_discord(item["payload"], webhook_for(item["channel"]), dry_run)
            print(f"[{item['channel']}] 전송: {item['title']}")
        except Exception as e:
            item["tries"] = item.get("tries", 0) + 1
            if item["tries"] >= SEND_MAX_TRIES:
                print(f"[오류] 디스코드 전송 {item['tries']}회 실패, 포기: {item['title']} ({e})", file=sys.stderr)
            else:
                print(f"[경고] 디스코드 전송 실패 ({item['tries']}회), 다음에 다시 시도: {e}", file=sys.stderr)
                remaining.append(item)
    state["outbox"] = remaining


def next_delay(interval, fail_count):
    """공지 API 접속이 연속으로 실패하면 확인 간격을 2배씩 늘린다 (최대 MAX_BACKOFF)."""
    return min(interval * 2 ** min(fail_count, 10), max(interval, MAX_BACKOFF))


def begin_key(notice):
    when = parse_time(notice.get("begin_time"))
    return when or datetime.min.replace(tzinfo=timezone.utc)


def check_once(args):
    state = load_state()
    state.setdefault("outbox", [])
    for old_key in ("seen", "floor"):  # 예전 공식 커뮤니티(포럼) 버전의 상태값
        state.pop(old_key, None)

    try:
        notices = fetch_notices()
        seen = state.get("notice_seen")
        first_run = seen is None
        seen = set(seen or [])
        if first_run:
            # 이 시각보다 먼저 게시된 공지는 나중에 목록에 다시 보여도(재고정 등) 새 글로 보지 않는다.
            # 미리 써 두고 예약 게시하는 공지는 번호가 작아도 게시 시각이 늦어서 새 글로 잡힌다.
            state["notice_since"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        since = parse_time(state.get("notice_since")) or datetime.min.replace(tzinfo=timezone.utc)

        new = [n for n in notices if str(n["seq"]) not in seen and begin_key(n) >= since]
        if args.post_latest:  # 연결 테스트: 이미 본 글이어도 가장 최근 게시 공지 1개만 보낸다
            new = sorted(notices, key=begin_key)[-1:]
        new.sort(key=begin_key)

        sent = 0
        if first_run and not args.post_latest:
            print(f"처음 실행: 기존 공지 {len(notices)}개를 읽음 처리 (전송 안 함)")
        else:
            for notice in new:
                detail = fetch_notice_detail(notice["seq"])
                channel, payload, used_claude = build_message(notice, detail, claude_allowed(state))
                if used_claude:
                    state["claude_usage"]["count"] += 1
                # 요약을 만든 즉시 '본 글'로 기록해서, 전송이 실패해도 요약을 다시 만들지 않는다
                state["outbox"].append({"channel": channel, "title": str(notice.get("title")), "payload": payload})
                seen.add(str(notice["seq"]))
                state["notice_seen"] = sorted(seen, key=int)
                sent += 1
        seen.update(str(n["seq"]) for n in notices)
        state["notice_seen"] = sorted(seen, key=int)[-SEEN_LIMIT:]

        state["fail_count"] = 0
        state.pop("fail_alerted", None)
        print(f"확인 완료: 공지 {len(notices)}개 확인, 새 공지 {sent}건")
        return 0
    except ApiError as e:
        state["fail_count"] = state.get("fail_count", 0) + 1
        print(f"[경고] 공지 API 접속 실패 ({state['fail_count']}회 연속): {e}", file=sys.stderr)
        if state["fail_count"] >= FAIL_ALERT_AFTER and not state.get("fail_alerted"):
            # 장애 알림은 공지 채널로
            state["outbox"].append({"channel": "공지사항", "title": "공지 API 접속 실패 경고", "payload": {
                "username": "도깨비의세계 공지",
                "content": f"⚠️ 공지를 {state['fail_count']}회 연속 못 가져왔어요. ({e})"}})
            state["fail_alerted"] = True
        return 0
    finally:
        flush_outbox(state, args.dry_run)
        if not args.dry_run:
            save_state(state)


def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--loop", action="store_true", help="계속 돌면서 주기적으로 확인")
    ap.add_argument("--interval", type=int, default=int(os.environ.get("CHECK_INTERVAL", 900)),
                    help="--loop 확인 간격(초), 기본 900(15분). 접속이 실패하면 자동으로 늘어난다")
    ap.add_argument("--dry-run", action="store_true", help="디스코드로 보내지 않고 출력만")
    ap.add_argument("--post-latest", action="store_true",
                    help="가장 최근 게시 공지 1개를 보내본다 (연결 테스트, 나머지는 읽음 처리)")
    args = ap.parse_args()

    if not args.loop:
        return check_once(args)
    while True:
        try:
            check_once(args)
        except Exception as e:  # 예상 못 한 오류가 나도 서버에서 계속 돌게 한다
            print(f"[오류] 확인 중 예외: {e!r}", file=sys.stderr)
        delay = next_delay(args.interval, load_state().get("fail_count", 0))
        if delay > args.interval:
            print(f"[경고] 접속 실패가 이어져 {delay}초 뒤에 다시 확인합니다", file=sys.stderr)
        sys.stdout.flush()
        sys.stderr.flush()
        time.sleep(delay)


if __name__ == "__main__":
    sys.exit(main())
