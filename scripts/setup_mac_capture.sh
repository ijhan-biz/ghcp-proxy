#!/usr/bin/env bash
# 이 macOS PC 전체 트래픽을 Copilot 캡처 프록시(10801)로 라우팅한다.
#   1) mitmproxy 사내 CA 를 System 키체인에 신뢰 등록
#   2) 활성 네트워크 서비스의 system 웹/보안 프록시를 127.0.0.1:10801 로 설정
#   3) 로컬/대시보드 주소는 프록시 우회(bypass)
#
# 되돌리기: scripts/teardown_mac_capture.sh
#
# 주의: TLS 인터셉트는 강한 통제입니다. 인증서 pinning 을 쓰는 일부 앱
# (예: 일부 클라우드/메신저)은 동작이 막힐 수 있으며, 그 경우 teardown 으로
# 복구하세요. 실행에는 sudo(암호)가 필요합니다.
set -euo pipefail

cd "$(dirname "$0")/.."
CA="$(pwd)/.mitmproxy/mitmproxy-ca-cert.pem"
PROXY_HOST="127.0.0.1"
PROXY_PORT="${LISTEN_PORT:-10801}"

if [[ ! -f "$CA" ]]; then
  echo "CA 파일이 없습니다: $CA"
  echo "먼저 프록시를 한 번 실행해 CA 를 생성하세요: ./scripts/run_proxy.sh"
  exit 1
fi

# 활성(기본 라우트) 인터페이스 → 네트워크 서비스 이름 매핑
IFACE="$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')"
SVC="$(networksetup -listnetworkserviceorder | awk -v dev="$IFACE" '
  /^\([0-9]+\)/ { name=$0; sub(/^\([0-9]+\) /,"",name) }
  $0 ~ ("Device: " dev "\\)") { print name; exit }
')"
if [[ -z "${SVC:-}" ]]; then
  echo "기본 인터페이스($IFACE)에 매핑되는 네트워크 서비스를 찾지 못했습니다."
  echo "networksetup -listallnetworkservices 로 확인 후 SVC 를 직접 지정하세요."
  exit 1
fi

echo "대상 네트워크 서비스 : $SVC ($IFACE)"
echo "프록시               : http://$PROXY_HOST:$PROXY_PORT"
echo "CA                   : $CA"
echo

echo "[1/3] System 키체인에 CA 신뢰 등록 (sudo 필요)"
sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain "$CA"

echo "[2/3] 시스템 웹/보안 프록시 설정 (sudo 필요)"
sudo networksetup -setwebproxy "$SVC" "$PROXY_HOST" "$PROXY_PORT"
sudo networksetup -setsecurewebproxy "$SVC" "$PROXY_HOST" "$PROXY_PORT"
sudo networksetup -setwebproxystate "$SVC" on
sudo networksetup -setsecurewebproxystate "$SVC" on

echo "[3/3] 로컬/대시보드 주소 프록시 우회 설정"
sudo networksetup -setproxybypassdomains "$SVC" \
  127.0.0.1 localhost "*.local" "169.254/16"

echo
echo "완료. 이 PC 의 시스템 프록시 트래픽이 10801 을 통과합니다."
echo "Copilot 도메인만 저장됩니다(config.yaml allowlist)."
echo "대시보드: http://127.0.0.1:10802"
echo
echo "※ 시스템 프록시를 무시하는 일부 CLI(node/gh/git 등)는 아래 env 도 함께 적용하세요:"
echo "   source scripts/env_capture.sh"
echo "되돌리기: ./scripts/teardown_mac_capture.sh"
