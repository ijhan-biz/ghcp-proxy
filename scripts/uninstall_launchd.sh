#!/usr/bin/env bash
# install_launchd.sh 로 등록한 LaunchAgent(프록시 자동시작 + GUI env)를 제거한다.
#   - 두 LaunchAgent 를 unload 하고 plist 삭제
#   - GUI 세션에 주입한 캡처 env 해제(launchctl unsetenv)
#
# 시스템 프록시/CA 신뢰는 그대로 둔다(되돌리려면 teardown_mac_capture.sh).
set -euo pipefail

cd "$(dirname "$0")/.."
LA_DIR="$HOME/Library/LaunchAgents"

PROXY_LABEL="biz.ijhan.ghcp-proxy"
ENV_LABEL="biz.ijhan.ghcp-proxy.env"
PROXY_PLIST="$LA_DIR/$PROXY_LABEL.plist"
ENV_PLIST="$LA_DIR/$ENV_LABEL.plist"

echo "[1/3] LaunchAgent unload"
launchctl unload "$PROXY_PLIST" 2>/dev/null || true
launchctl unload "$ENV_PLIST" 2>/dev/null || true

echo "[2/3] plist 삭제"
rm -f "$PROXY_PLIST" "$ENV_PLIST"

echo "[3/3] GUI 세션 env 해제"
for k in HTTP_PROXY HTTPS_PROXY http_proxy https_proxy NO_PROXY no_proxy NODE_EXTRA_CA_CERTS; do
  launchctl unsetenv "$k" 2>/dev/null || true
done

echo
echo "완료. 자동시작/세션 env 를 제거했습니다."
echo "이미 떠있는 GUI 앱은 env 해제를 반영하려면 재실행이 필요합니다."
echo "시스템 프록시/CA 도 되돌리려면: ./scripts/teardown_mac_capture.sh"
