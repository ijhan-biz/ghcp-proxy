#!/usr/bin/env bash
# GitHub Copilot 캡처 Proxy 실행 헬퍼
#
# 사용:
#   ./scripts/run_proxy.sh              # 기본 포트 10801, macOS 시스템 프록시 자동 적용
#   LISTEN_PORT=9090 ./scripts/run_proxy.sh
#   ./scripts/run_proxy.sh --web        # mitmweb (브라우저 UI) 사용
#   ./scripts/run_proxy.sh --no-system-proxy  # 시스템 프록시 자동 적용 생략
set -euo pipefail

cd "$(dirname "$0")/.."

# venv 활성화 (있으면)
if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

LISTEN_PORT="${LISTEN_PORT:-10801}"
ADDON="addons/capture.py"
CONFDIR="$(pwd)/.mitmproxy"
USE_WEB=0
AUTO_SYSTEM_PROXY=1

active_service() {
  local iface svc
  iface="$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')"
  svc="$(networksetup -listnetworkserviceorder | awk -v dev="$iface" '
    /^\([0-9]+\)/ { name=$0; sub(/^\([0-9]+\) /,"",name) }
    $0 ~ ("Device: " dev "\\)") { print name; exit }
  ')"
  echo "$svc"
}

proxy_enabled_and_targeted() {
  local svc mode out enabled server port
  svc="$1"
  mode="$2"
  if [[ "$mode" == "web" ]]; then
    out="$(networksetup -getwebproxy "$svc" 2>/dev/null || true)"
  else
    out="$(networksetup -getsecurewebproxy "$svc" 2>/dev/null || true)"
  fi
  enabled="$(printf '%s\n' "$out" | awk -F': ' '/^Enabled:/{print $2}')"
  server="$(printf '%s\n' "$out" | awk -F': ' '/^Server:/{print $2}')"
  port="$(printf '%s\n' "$out" | awk -F': ' '/^Port:/{print $2}')"
  [[ "$enabled" == "Yes" && "$server" == "127.0.0.1" && "$port" == "$LISTEN_PORT" ]]
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --web)
      USE_WEB=1
      ;;
    --no-system-proxy)
      AUTO_SYSTEM_PROXY=0
      ;;
    *)
      echo "알 수 없는 옵션: $1"
      echo "사용법: ./scripts/run_proxy.sh [--web] [--no-system-proxy]"
      exit 2
      ;;
  esac
  shift
done

# macOS에서는 기본적으로 시스템 프록시를 자동 적용해 '이 PC 전체' 캡처를 활성화한다.
if [[ "${AUTO_SYSTEM_PROXY}" == "1" && "$(uname -s)" == "Darwin" ]]; then
  if [[ ! -x "scripts/setup_mac_capture.sh" ]]; then
    echo "[run_proxy] 오류: scripts/setup_mac_capture.sh 를 찾지 못했습니다."
    exit 1
  fi
  echo "[run_proxy] macOS 시스템 프록시 자동 적용 시작"
  echo "[run_proxy] 필요 시 sudo 프롬프트가 표시됩니다."
  LISTEN_PORT="${LISTEN_PORT}" ./scripts/setup_mac_capture.sh

  SVC="$(active_service)"
  if [[ -z "${SVC:-}" ]]; then
    echo "[run_proxy] 오류: 활성 네트워크 서비스를 확인하지 못했습니다."
    exit 1
  fi
  if ! proxy_enabled_and_targeted "$SVC" web || ! proxy_enabled_and_targeted "$SVC" secure; then
    echo "[run_proxy] 오류: 시스템 프록시가 완전히 적용되지 않았습니다."
    echo "[run_proxy] 확인 대상 서비스: $SVC"
    echo "[run_proxy] 요구 상태: web/secure 모두 Enabled: Yes, Server: 127.0.0.1, Port: $LISTEN_PORT"
    echo "[run_proxy] 필요 시 수동 실행: ./scripts/setup_mac_capture.sh"
    echo "[run_proxy] 우회 실행: ./scripts/run_proxy.sh --no-system-proxy"
    exit 1
  fi
fi

if [[ "${USE_WEB}" == "1" ]]; then
  exec mitmweb --set confdir="${CONFDIR}" --listen-port "${LISTEN_PORT}" -s "${ADDON}"
else
  exec mitmdump --set confdir="${CONFDIR}" --listen-port "${LISTEN_PORT}" -s "${ADDON}"
fi
