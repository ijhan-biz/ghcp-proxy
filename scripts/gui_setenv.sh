#!/usr/bin/env bash
# macOS GUI 세션(Aqua) 전체에 Copilot 캡처용 환경변수를 주입한다.
# 이 스크립트 실행 이후 Dock/Finder 로 실행되는 GUI 앱(VS Code 등)이
# 해당 환경변수를 상속받아, 시스템 프록시를 우회하는 Electron/Node 앱도
# 캡처 프록시를 통과하게 된다.
#
# 보통은 LaunchAgent(biz.ijhan.ghcp-proxy.env)가 로그인 시 자동 실행한다.
# 수동 적용도 가능: ./scripts/gui_setenv.sh  (해제: launchctl unsetenv <KEY>)
#
# 주의: 단일 CA 만 담긴 *_CA_BUNDLE/SSL_CERT_FILE 을 전역 설정하면 비인터셉트
# 호스트의 TLS 가 깨질 수 있어, 전역에는 '추가형'인 NODE_EXTRA_CA_CERTS 와
# 프록시 변수만 설정한다(일반 TLS 무해). CLI 용 전체 변수는 env_capture.sh 사용.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
PORT="${LISTEN_PORT:-10801}"
CA="$ROOT/.mitmproxy/mitmproxy-ca-cert.pem"
PROXY="http://127.0.0.1:${PORT}"

launchctl setenv HTTP_PROXY  "$PROXY"
launchctl setenv HTTPS_PROXY "$PROXY"
launchctl setenv http_proxy  "$PROXY"
launchctl setenv https_proxy "$PROXY"
launchctl setenv NO_PROXY "127.0.0.1,localhost,.local"
launchctl setenv no_proxy "127.0.0.1,localhost,.local"
launchctl setenv NODE_EXTRA_CA_CERTS "$CA"

echo "[gui_setenv] GUI 세션 env 적용: $PROXY (NODE_EXTRA_CA_CERTS=$CA)"
echo "[gui_setenv] 이후 새로 실행되는 GUI 앱부터 적용됩니다(이미 떠있는 앱은 재실행 필요)."
