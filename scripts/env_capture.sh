# 시스템 프록시를 무시하는 CLI(node/gh/git 등)용 환경변수.
# 사용:  source scripts/env_capture.sh
# 현재 셸 세션에만 적용됩니다.

_GHCP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
_GHCP_PORT="${LISTEN_PORT:-10801}"

export HTTP_PROXY="http://127.0.0.1:${_GHCP_PORT}"
export HTTPS_PROXY="http://127.0.0.1:${_GHCP_PORT}"
export http_proxy="$HTTP_PROXY"
export https_proxy="$HTTPS_PROXY"
# 로컬/대시보드는 우회
export NO_PROXY="127.0.0.1,localhost,.local"
export no_proxy="$NO_PROXY"
# Node 기반 도구(VS Code 확장 등)가 사내 CA 를 신뢰하도록
export NODE_EXTRA_CA_CERTS="${_GHCP_ROOT}/.mitmproxy/mitmproxy-ca-cert.pem"
# git 이 CA 를 신뢰하도록(선택)
export GIT_SSL_CAINFO="${_GHCP_ROOT}/.mitmproxy/mitmproxy-ca-cert.pem"
# Python(requests/httpx 등)·curl 이 사내 CA 를 신뢰하도록
export REQUESTS_CA_BUNDLE="${_GHCP_ROOT}/.mitmproxy/mitmproxy-ca-cert.pem"
export SSL_CERT_FILE="${_GHCP_ROOT}/.mitmproxy/mitmproxy-ca-cert.pem"
export CURL_CA_BUNDLE="${_GHCP_ROOT}/.mitmproxy/mitmproxy-ca-cert.pem"

echo "Copilot 캡처 프록시 env 적용: $HTTPS_PROXY (CA: $NODE_EXTRA_CA_CERTS)"
