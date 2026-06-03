#!/usr/bin/env bash
# GitHub Copilot 캡처 Proxy 실행 헬퍼
#
# 사용:
#   ./scripts/run_proxy.sh              # 기본 포트 10801, web UI 없음
#   LISTEN_PORT=9090 ./scripts/run_proxy.sh
#   ./scripts/run_proxy.sh --web        # mitmweb (브라우저 UI) 사용
set -euo pipefail

cd "$(dirname "$0")/.."

# venv 활성화 (있으면)
if [[ -f .venv/bin/activate ]]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

LISTEN_PORT="${LISTEN_PORT:-10801}"
ADDON="addons/capture.py"

if [[ "${1:-}" == "--web" ]]; then
  exec mitmweb --listen-port "${LISTEN_PORT}" -s "${ADDON}"
else
  exec mitmdump --listen-port "${LISTEN_PORT}" -s "${ADDON}"
fi
