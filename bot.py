"""도깨비의세계 공식 포럼 공지사항·업데이트 게시판의 새 글을 디스코드 채널로 전달하는 봇.

한 번 실행하면 새 공지를 확인해 웹훅으로 보내고 끝난다 (GitHub Actions, 작업 스케줄러용).
--loop 를 주면 계속 돌면서 일정 간격으로 확인한다 (상시 켜둔 PC/서버용).
"""

import argparse
import html
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
STATE_PATH = Path(os.environ.get("STATE_PATH", ROOT / "state.json"))

API = "https://forum-api.kakaogames.com/v1/dokkaebi"
POST_URL = "https://forum.kakaogames.com/dokkaebi/postView/?code={code}&id={post_id}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Origin": "https://forum.kakaogames.com",
    "Referer": "https://forum.kakaogames.com/dokkaebi/",
}

# 게시판 이름에 들어간 단어 → 그 게시판 글을 보낼 웹훅 환경변수 (위에서부터 먼저 맞는 것)
ROUTES = [
    ("업데이트", "DISCORD_WEBHOOK_UPDATE"),
    ("공지", "DISCORD_WEBHOOK_NOTICE"),
]

SEEN_LIMIT = 300         # 게시판별로 기억할 글 번호 수
FAIL_ALERT_AFTER = 12     # 연속 실패가 이만큼 쌓이면 디스코드에 한 번 알림
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


def env_list(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return [x.strip() for x in raw.split(",") if x.strip()]


# ---------------------------------------------------------------- forum API

class ForumError(Exception):
    pass


def api_get(path, **params):
    params.setdefault("lang", "ko")
    try:
        r = requests.get(f"{API}{path}", params=params, headers=HEADERS, timeout=20)
    except requests.RequestException as e:
        raise ForumError(f"{path}: {e}") from e
    if r.status_code != 200:
        raise ForumError(f"{path}: HTTP {r.status_code}")
    try:
        return r.json()
    except ValueError as e:
        raise ForumError(f"{path}: JSON 아님") from e


def find_dicts_with(obj, key):
    """응답 어딘가에 있는, key 를 가진 dict 들의 목록을 찾아 돌려준다."""
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj) and any(key in x for x in obj):
            return obj
        for x in obj:
            found = find_dicts_with(x, key)
            if found:
                return found
    elif isinstance(obj, dict):
        for v in obj.values():
            found = find_dicts_with(v, key)
            if found:
                return found
    return []


def list_boards():
    return find_dicts_with(api_get("/boards"), "board_code")


def route_env(board_name):
    for word, env_name in ROUTES:
        if word in board_name:
            return env_name
    return None


def webhook_for(board_name):
    """게시판 전용 웹훅이 없으면 DISCORD_WEBHOOK_URL 로 보낸다."""
    env_name = route_env(board_name)
    return (env_name and os.environ.get(env_name)) or os.environ.get("DISCORD_WEBHOOK_URL", "")


def pick_boards(boards, wanted_codes):
    picked = []
    for b in boards:
        code, name = b.get("board_code"), str(b.get("name", ""))
        if wanted_codes:
            if code in wanted_codes:
                picked.append((code, name or code))
        elif route_env(name):
            picked.append((code, name))
    return picked


def fetch_posts(code):
    posts = {}
    for path in (f"/boards/{code}/pinned", f"/boards/{code}/list"):
        try:
            data = api_get(path, page=1, size=18)
        except ForumError:
            if path.endswith("pinned"):
                continue  # 고정글이 없는 게시판일 수 있음
            raise
        for p in find_dicts_with(data, "post_id"):
            posts[str(p["post_id"])] = p
    return list(posts.values())


def fetch_post_detail(code, post_id):
    data = api_get(f"/boards/{code}/posts/{post_id}")
    return data.get("payload", data)


def prefix_text(post):
    prefix = post.get("prefix")
    if isinstance(prefix, dict):
        return str(prefix.get("name") or prefix.get("label") or "")
    return str(prefix or "")


# ---------------------------------------------------------------- HTML -> text

class _TextExtractor(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol"}

    def __init__(self):
        super().__init__()
        self.parts, self.images = [], []

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")
        if tag == "img":
            src = dict(attrs).get("src")
            if src and src.startswith("http"):
                self.images.append(src)

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
    return text.strip(), p.images


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

def notice_color(title, board_name=""):
    if "점검" in title:
        return 0xE67E22
    if "업데이트" in board_name or "업데이트" in title or "패치" in title:
        return 0x3498DB
    return 0x95A5A6


def parse_time(value):
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            ts = int(value)
            return datetime.fromtimestamp(ts / 1000 if ts > 1e12 else ts, tz=timezone.utc)
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone(datetime.now().astimezone().utcoffset()))
    except (ValueError, OSError):
        return None


def build_message(board_name, code, post, detail, use_claude=True):
    """(디스코드 payload, Claude 호출 여부) 를 돌려준다."""
    title = str(detail.get("title") or post.get("title") or "제목 없음")
    prefix = prefix_text(post)
    shown_title = title if not prefix or f"[{prefix}]" in title else f"[{prefix}] {title}"
    body, images = html_to_text(detail.get("content", ""))
    summary, used_claude = summarize(title, body, use_claude)

    embed = {
        "title": shown_title[:256],
        "url": POST_URL.format(code=code, post_id=post["post_id"]),
        "description": summary[:4000],
        "color": notice_color(shown_title, board_name),
        "footer": {"text": f"도깨비의세계 · {board_name}"},
    }
    when = parse_time(detail.get("published_at") or post.get("published_at"))
    if when:
        embed["timestamp"] = when.isoformat()
    if images:
        embed["image"] = {"url": images[0]}
    return {"username": "도깨비의세계 공지", "embeds": [embed]}, used_claude


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
    return {"seen": {}, "fail_count": 0}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def post_num(post):
    return int(post["post_id"]) if str(post["post_id"]).isdigit() else None


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
            send_discord(item["payload"], webhook_for(item["board"]), dry_run)
            print(f"[{item['board']}] 전송: {item['title']}")
        except Exception as e:
            item["tries"] = item.get("tries", 0) + 1
            if item["tries"] >= SEND_MAX_TRIES:
                print(f"[오류] 디스코드 전송 {item['tries']}회 실패, 포기: {item['title']} ({e})", file=sys.stderr)
            else:
                print(f"[경고] 디스코드 전송 실패 ({item['tries']}회), 다음에 다시 시도: {e}", file=sys.stderr)
                remaining.append(item)
    state["outbox"] = remaining


def check_once(args):
    board_codes = env_list("BOARD_CODES", [])
    state = load_state()
    state.setdefault("floor", {})
    state.setdefault("outbox", [])

    try:
        boards = list_boards()
        if args.list_boards:
            for b in boards:
                name = str(b.get("name", ""))
                print(f"{b.get('board_code')}\t{name}\t-> {route_env(name) or '(감시 안 함)'}")
            return 0
        targets = pick_boards(boards, board_codes)
        if not targets:
            raise ForumError("감시할 게시판을 못 찾음 (--list-boards 로 확인 후 BOARD_CODES 지정)")

        sent = 0
        for code, name in targets:
            posts = fetch_posts(code)
            seen = state["seen"].get(code)
            first_run = seen is None
            seen = set(seen or [])
            # 처음 본 글 번호 중 가장 큰 값. 이보다 번호가 작은 글은 나중에 고정글로
            # 올라와도 예전 글이므로 보내지 않는다.
            floor = state["floor"].get(code)
            new = [p for p in posts if str(p["post_id"]) not in seen
                   and not (floor is not None and post_num(p) is not None and post_num(p) <= floor)]
            new.sort(key=lambda p: post_num(p) or 0)

            if first_run:
                nums = [post_num(p) for p in posts if post_num(p) is not None]
                if nums:
                    state["floor"][code] = max(nums)
            if args.post_latest:  # 연결 테스트: 이미 본 글이어도 가장 최근 글 1개만 보낸다
                new = sorted(posts, key=lambda p: post_num(p) or 0)[-1:]
            if first_run and not args.post_latest:
                print(f"[{name}] 처음 실행: 기존 글 {len(new)}개를 읽음 처리 (전송 안 함)")
            else:
                for post in new:
                    detail = fetch_post_detail(code, post["post_id"])
                    payload, used_claude = build_message(name, code, post, detail, claude_allowed(state))
                    if used_claude:
                        state["claude_usage"]["count"] += 1
                    # 요약을 만든 즉시 '본 글'로 기록해서, 전송이 실패해도 요약을 다시 만들지 않는다
                    state["outbox"].append({"board": name, "title": str(post.get("title")), "payload": payload})
                    seen.add(str(post["post_id"]))
                    state["seen"][code] = sorted(seen, key=lambda x: int(x) if x.isdigit() else 0)
                    sent += 1
            seen.update(str(p["post_id"]) for p in posts)
            state["seen"][code] = sorted(seen, key=lambda x: int(x) if x.isdigit() else 0)[-SEEN_LIMIT:]

        state["fail_count"] = 0
        state.pop("fail_alerted", None)
        print(f"확인 완료: 게시판 {len(targets)}개, 새 공지 {sent}건")
        return 0
    except ForumError as e:
        state["fail_count"] = state.get("fail_count", 0) + 1
        print(f"[경고] 포럼 접속 실패 ({state['fail_count']}회 연속): {e}", file=sys.stderr)
        if state["fail_count"] >= FAIL_ALERT_AFTER and not state.get("fail_alerted"):
            # 장애 알림은 공지 채널로
            state["outbox"].append({"board": "공지", "title": "포럼 접속 실패 경고", "payload": {
                "username": "도깨비의세계 공지",
                "content": f"⚠️ 포럼 공지를 {state['fail_count']}회 연속 못 가져왔어요. ({e})"}})
            state["fail_alerted"] = True
        return 0
    finally:
        if not args.list_boards:
            flush_outbox(state, args.dry_run)
            if not args.dry_run:
                save_state(state)


def main():
    load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--loop", action="store_true", help="계속 돌면서 주기적으로 확인")
    ap.add_argument("--interval", type=int, default=int(os.environ.get("CHECK_INTERVAL", 300)),
                    help="--loop 확인 간격(초), 기본 300")
    ap.add_argument("--dry-run", action="store_true", help="디스코드로 보내지 않고 출력만")
    ap.add_argument("--post-latest", action="store_true",
                    help="게시판마다 가장 최근 글 1개를 보내본다 (연결 테스트, 나머지는 읽음 처리)")
    ap.add_argument("--list-boards", action="store_true", help="게시판 코드 목록 출력")
    args = ap.parse_args()

    if not args.loop:
        return check_once(args)
    while True:
        try:
            check_once(args)
        except Exception as e:  # 예상 못 한 오류가 나도 서버에서 계속 돌게 한다
            print(f"[오류] 확인 중 예외: {e!r}", file=sys.stderr)
        sys.stdout.flush()
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
