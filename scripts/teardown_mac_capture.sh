#!/usr/bin/env bash
# setup_mac_capture.sh 로 적용한 시스템 프록시/CA 설정을 되돌린다.
#   - 시스템 웹/보안 프록시 OFF
#   - (선택) System 키체인의 mitmproxy CA 제거
set -euo pipefail

cd "$(dirname "$0")/.."

IFACE="$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')"
SVC="$(networksetup -listnetworkserviceorder | awk -v dev="$IFACE" '
  /^\([0-9]+\)/ { name=$0; sub(/^\([0-9]+\) /,"",name) }
  $0 ~ ("Device: " dev "\\)") { print name; exit }
')"

if [[ -n "${SVC:-}" ]]; then
  echo "[1/2] 시스템 프록시 OFF: $SVC (sudo 필요)"
  sudo networksetup -setwebproxystate "$SVC" off || true
  sudo networksetup -setsecurewebproxystate "$SVC" off || true
else
  echo "네트워크 서비스 자동 탐지 실패 — 수동으로 프록시를 끄세요."
fi

echo "[2/2] System 키체인에서 mitmproxy CA 제거 (sudo 필요, 선택)"
read -r -p "CA 도 제거할까요? [y/N] " ans
if [[ "${ans:-N}" =~ ^[Yy]$ ]]; then
  sudo security delete-certificate -c mitmproxy /Library/Keychains/System.keychain || \
    echo "CA 제거 실패 또는 이미 없음(무시 가능)."
else
  echo "CA 는 유지합니다."
fi

echo "완료. 시스템 프록시 설정을 복구했습니다."
