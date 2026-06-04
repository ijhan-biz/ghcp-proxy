#!/usr/bin/env bash
# Copilot 캡처 프록시를 macOS 로그인 시 자동 실행되도록 LaunchAgent 로 등록한다.
#
# 설치 항목(2개):
#   1) biz.ijhan.ghcp-proxy      : mitmdump 프록시 자동 실행(죽으면 자동 재시작)
#   2) biz.ijhan.ghcp-proxy.env  : GUI 세션에 캡처 env 주입(VS Code 등이 상속)
#
# 사용:
#   ./scripts/install_launchd.sh
#
# 해제:
#   ./scripts/uninstall_launchd.sh
#
# 주의:
#   - 시스템 프록시(127.0.0.1:PORT)와 System 키체인 CA 신뢰는 재부팅 후에도
#     유지되므로, 최초 1회 ./scripts/setup_mac_capture.sh 로 적용돼 있어야 한다.
#   - 이 스크립트는 sudo 가 필요 없다(프록시 프로세스/유저 env 만 다룸).
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PORT="${LISTEN_PORT:-10801}"
CA="$ROOT/.mitmproxy/mitmproxy-ca-cert.pem"
LA_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$ROOT/logs"

PROXY_LABEL="biz.ijhan.ghcp-proxy"
ENV_LABEL="biz.ijhan.ghcp-proxy.env"
PROXY_PLIST="$LA_DIR/$PROXY_LABEL.plist"
ENV_PLIST="$LA_DIR/$ENV_LABEL.plist"

if [[ ! -f "$CA" ]]; then
  echo "오류: CA 파일이 없습니다: $CA"
  echo "먼저 프록시를 한 번 실행해 CA 를 생성하세요: ./scripts/run_proxy.sh"
  exit 1
fi

mkdir -p "$LA_DIR" "$LOG_DIR"

echo "[1/4] 프록시 LaunchAgent 작성: $PROXY_PLIST"
cat > "$PROXY_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PROXY_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$ROOT/scripts/run_proxy.sh</string>
        <string>--no-system-proxy</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$ROOT</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>LISTEN_PORT</key>
        <string>$PORT</string>
        <key>PATH</key>
        <string>/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/proxy.out.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/proxy.err.log</string>
</dict>
</plist>
PLIST

echo "[2/4] env LaunchAgent 작성: $ENV_PLIST"
cat > "$ENV_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$ENV_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$ROOT/scripts/gui_setenv.sh</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>LISTEN_PORT</key>
        <string>$PORT</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/setenv.out.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/setenv.err.log</string>
</dict>
</plist>
PLIST

echo "[3/4] 기존 등록 해제 후 재적재"
launchctl unload "$PROXY_PLIST" 2>/dev/null || true
launchctl unload "$ENV_PLIST" 2>/dev/null || true
launchctl load -w "$ENV_PLIST"
launchctl load -w "$PROXY_PLIST"

echo "[4/4] 상태 확인"
sleep 2
if launchctl list | grep -q "$PROXY_LABEL"; then
  echo "  - 프록시 에이전트 등록됨: $PROXY_LABEL"
else
  echo "  - 경고: 프록시 에이전트가 목록에 없습니다."
fi
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "  - 프록시 LISTEN 확인: 127.0.0.1:$PORT"
else
  echo "  - 경고: 포트 $PORT 가 아직 LISTEN 상태가 아닙니다(로그 확인: $LOG_DIR/proxy.err.log)."
fi

echo
echo "완료. 다음 로그인부터 자동 실행됩니다."
echo "VS Code 캡처는 env 상속이 필요하므로, 지금 열려있는 VS Code 는 한 번 종료 후 재실행하세요."
echo "  (이미 실행 중인 앱은 env 를 상속받지 못합니다)"
echo "해제: ./scripts/uninstall_launchd.sh"
