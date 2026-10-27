#!/usr/bin/env bash
# Oracle Cloud 등 Ubuntu 서버에 봇을 설치하고, 재부팅해도 자동으로 다시 켜지게 등록한다.
#   curl -fsSL https://raw.githubusercontent.com/doorBW/dokkaebi-notice-bot/main/deploy/setup.sh | bash
# 처음 실행하면 .env 파일만 만들고 멈춘다. 웹훅/API 키를 넣은 뒤 한 번 더 실행하면 설치가 끝난다.
set -euo pipefail

REPO=https://github.com/doorBW/dokkaebi-notice-bot.git
APP_DIR="$HOME/dokkaebi-notice-bot"
SERVICE=dokkaebi-notice-bot

echo "== 1/5 패키지 설치"
sudo apt-get update -qq
sudo apt-get install -y -qq git python3-venv unattended-upgrades >/dev/null

echo "== 2/5 SSH 잠그기 (비밀번호 로그인·root 로그인 금지, 키로만 접속)"
sudo tee /etc/ssh/sshd_config.d/99-notice-bot.conf >/dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
EOF
sudo systemctl reload ssh 2>/dev/null || sudo systemctl reload sshd
# 보안 업데이트 자동 설치
echo 'APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";' | sudo tee /etc/apt/apt.conf.d/20auto-upgrades >/dev/null

echo "== 3/5 코드 받기"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull -q --ff-only
else
  git clone -q "$REPO" "$APP_DIR"
fi
cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "== 4/5 설정 파일(.env)"
if [ ! -f .env ]; then
  cat > .env <<'EOF'
DISCORD_WEBHOOK_NOTICE=
DISCORD_WEBHOOK_UPDATE=
ANTHROPIC_API_KEY=
EOF
  chmod 600 .env
  echo
  echo "  $APP_DIR/.env 를 만들었어요. 아래 명령으로 열어서 값 3개를 채우고 저장한 뒤,"
  echo "  이 설치 명령을 한 번 더 실행해 주세요."
  echo "    nano $APP_DIR/.env      (저장: Ctrl+O, Enter / 나가기: Ctrl+X)"
  exit 0
fi
chmod 600 .env
if grep -qE '^(DISCORD_WEBHOOK_NOTICE|DISCORD_WEBHOOK_UPDATE)=$' .env; then
  echo "  .env 에 비어 있는 웹훅이 있어요. nano $APP_DIR/.env 로 채운 뒤 다시 실행해 주세요."
  exit 1
fi

echo "== 공지 API 접속 확인"
.venv/bin/python -c "import bot; print('  공지', len(bot.fetch_notices()), '개를 받았어요')" || true

echo "== 5/5 서비스 등록 (자동 시작)"
sudo tee /etc/systemd/system/$SERVICE.service >/dev/null <<EOF
[Unit]
Description=도깨비의세계 공지 알림 봇
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python bot.py --loop
Environment=PYTHONUNBUFFERED=1
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now $SERVICE
sudo systemctl restart $SERVICE
sleep 3
systemctl --no-pager --lines=10 status $SERVICE || true

echo
echo "설치 완료. 로그 보기:  journalctl -u $SERVICE -f"
