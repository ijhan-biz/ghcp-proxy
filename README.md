# GitHub Copilot Proxy 캡처 PoC

`032-github-copilot-proxy-architecture-2026-06-02.html` 아키텍처 가이드의 동작하는
구현체입니다. 사내 CA 기반 **TLS 인터셉트 Proxy(mitmproxy)** 로 GitHub Copilot 트래픽의
요청/응답 payload 를 캡처하고, 메타데이터(개발자·시간·모델·토큰)와 함께 **SQLite** 에
저장합니다. 민감정보 마스킹·토큰 산정·보존정책·조회 CLI 를 포함합니다.
상세 설계·내부 동작·사용 가이드는 `docs/ghcp-proxy-guide.html` 에서 확인할 수 있습니다.

> ⚠️ TLS 인터셉트는 전사 PC 에 사내 CA 를 신뢰시키는 강한 통제입니다. 실제 적용 전
> 반드시 **보안·프라이버시·법무 검토**를 거치세요. 프롬프트 원문에는 소스코드·비밀정보가
> 포함될 수 있습니다.

## 구성요소

| 경로 | 역할 |
|------|------|
| `addons/capture.py` | mitmproxy 애드온 — 핵심 인터셉트/캡처 로직 |
| `ghcp_proxy/config.py` | 설정 로더 (allowlist·마스킹·보존) |
| `ghcp_proxy/masking.py` | 민감정보 마스킹 (정규식 best-effort) |
| `ghcp_proxy/tokens.py` | 토큰 산정 (tiktoken 있으면 사용, 없으면 휴리스틱) + usage 파싱 |
| `ghcp_proxy/storage.py` | SQLite 스키마/삽입/조회/집계/보존정리 |
| `ghcp_proxy/attribution.py` | 호출 프로세스/프로젝트 폴더 귀속 (소스포트→PID→cwd 역추적) |
| `ghcp_proxy/cli.py` | 조회 CLI (`recent`/`tokens`/`projects`/`show`/`purge`) |
| `ghcp_proxy/dashboard.py` | 실시간 웹 대시보드 (SSE push, stdlib 전용) |
| `config.yaml` | allowlist 도메인·마스킹 토글·보존일수 |
| `docs/ghcp-proxy-guide.html` | 상세 설계·내부 동작·사용 가이드 HTML |
| `scripts/run_proxy.sh` | 프록시 실행 헬퍼 |
| `scripts/smoke_live.py` | 실제 mitmdump 프로세스 기반 라이브 스모크 테스트 |

## 빠른 시작

### 1. 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# (선택) 정확한 토큰 산정: pip install tiktoken
```

### 2. 프록시 실행 (CA 자동 생성)

```bash
./scripts/run_proxy.sh            # mitmdump, 포트 10801
# 또는 브라우저 UI:
./scripts/run_proxy.sh --web      # mitmweb
```

최초 실행 시 mitmproxy 가 `.mitmproxy/` 에 사내 CA(`mitmproxy-ca-cert.pem`)를
자동 생성합니다. 운영에서는 이 자리에 **사내 CA** 를 배치합니다.

### 2-1. 실시간 대시보드

프록시를 실행하면 애드온이 **실시간 모니터링 웹 대시보드**를 함께 띄웁니다
(기본 <http://127.0.0.1:10802>). 브라우저로 접속하면 캡처가 발생하는 즉시(SSE push)
테이블에 행이 추가되고, 상단 카드(총 캡처·총 토큰·마스킹 히트·개발자 수)와
개발자·모델별 토큰 집계가 갱신됩니다. payload 원문은 대시보드로 전송하지 않습니다.

`config.yaml` 의 `dashboard` 로 on/off·host·port 를 조정하며,
환경변수 `GHCP_DASHBOARD=0` / `GHCP_DASHBOARD_PORT=9000` 으로도 제어할 수 있습니다.


### 3. 클라이언트(개발자 PC)에 CA 신뢰 + 프록시 지정

아키텍처 가이드 §3 의 공식 조건을 그대로 따릅니다.

```bash
# Proxy URL 은 반드시 http:// (https:// 미지원). 인증은 Basic 또는 Kerberos.
export HTTP_PROXY="http://127.0.0.1:10801"
export HTTPS_PROXY="http://127.0.0.1:10801"

# 사내 CA 를 OS trust store 에 설치 + Node 보조 경로
export NODE_EXTRA_CA_CERTS="$(pwd)/.mitmproxy/mitmproxy-ca-cert.pem"
```

CA 를 OS 신뢰 저장소에 설치 (예시):
```bash
# macOS
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain .mitmproxy/mitmproxy-ca-cert.pem

# Linux (Debian/Ubuntu)
sudo cp .mitmproxy/mitmproxy-ca-cert.pem /usr/local/share/ca-certificates/corp-ca.crt
sudo update-ca-certificates
```

운영 환경에서는 MDM/GPO 로 각 PC OS trust store 에 사내 CA 를 배포합니다.
allowlist 에는 `api.githubcopilot.com`, `copilot-proxy.githubusercontent.com`,
`*.githubcopilot.com`, `proxy.enterprise.githubcopilot.com` 을 포함합니다
(`config.yaml` 의 `allowlist_hosts`).

### 3-1. 이 PC 전체 캡처 (macOS, 원클릭)

이 Mac 의 **모든 앱 트래픽**을 캡처 프록시로 라우팅하려면(저장은 Copilot 만):

```bash
./scripts/run_proxy.sh &              # 프록시+대시보드(10801/10802) 기동
./scripts/setup_mac_capture.sh        # CA 신뢰 + 시스템 프록시 설정 (sudo 암호 필요)
```

`setup_mac_capture.sh` 는 기본 네트워크 서비스를 자동 탐지해
① mitmproxy CA 를 System 키체인에 신뢰 등록하고 ② 시스템 웹/보안 프록시를
`127.0.0.1:10801` 로 설정합니다(로컬·대시보드는 우회). 시스템 프록시를 무시하는
일부 CLI(node/gh/git)는 추가로:

```bash
source scripts/env_capture.sh         # 현재 셸에 HTTP(S)_PROXY + CA env 적용
```

되돌리기:

```bash
./scripts/teardown_mac_capture.sh     # 시스템 프록시 OFF (+ 선택적 CA 제거)
```

> ⚠️ 시스템 전체 TLS 인터셉트입니다. 인증서 pinning 을 쓰는 일부 앱은 동작이
> 막힐 수 있으며, 그 경우 teardown 으로 즉시 복구하세요.


### 4. 캡처 데이터 조회

```bash
python -m ghcp_proxy.cli recent --limit 20     # 최근 캡처 목록
python -m ghcp_proxy.cli tokens                # 개발자·모델별 토큰 집계(기본: 추론만)
python -m ghcp_proxy.cli tokens --all          # /models 등 비추론 보조 트래픽 포함
python -m ghcp_proxy.cli projects --all        # 프로젝트 집계도 전체 포함 가능
python -m ghcp_proxy.cli show 3                # 단일 캡처 상세(payload)
python -m ghcp_proxy.cli purge                 # 보존기간 지난 캡처 삭제
```

`tokens`/`projects` 집계는 기본적으로 `model='unknown'` 인 비추론 보조 트래픽
(`/models`, `/telemetry`, `/_ping`, `/agents/sessions` 등)을 제외하며, `--all` 로 전체를 포함합니다.
각 명령에 `--json` 을 붙이면 SIEM/DLP 연계용 JSON 으로 출력됩니다.

## 설정 (`config.yaml`)

- `allowlist_hosts`: 캡처 대상 호스트. `.githubcopilot.com` 처럼 `.` 으로 시작하면
  서브도메인 와일드카드(suffix) 매칭.
- `storage.db_path` / `storage.retention_days`: SQLite 경로·보존일수.
- `masking.enabled`: 저장 전 민감정보 마스킹 on/off.
- `capture.store_response` / `capture.max_body_bytes`: 응답 저장 여부·본문 크기 상한.

`GHCP_CONFIG=/path/to/config.yaml` 환경변수로 다른 설정 파일을 지정할 수 있습니다.

## 동작 방식

1. mitmproxy 가 클라이언트 TLS 를 사내 CA 로 인터셉트(복호화)합니다.
2. `addons/capture.py` 의 `response` 훅에서 **allowlist 호스트**만 선별합니다.
3. 모델은 요청 본문의 `model` → (없으면) 응답 본문의 `model`(`model_from_response`)
   → `unknown` 순으로 결정합니다. Copilot 모델 선택을 "auto" 로 둬도 추론 요청 본문에는
   라우팅된 구체 모델명이 담기는 경우가 많아 그 값이 그대로 집계됩니다. 토큰은 응답에
   `usage` 가 있으면 그 값을 우선(`token_source=api_usage`), 없으면 휴리스틱/tiktoken 으로
   추정합니다.
4. 민감정보를 마스킹한 뒤 메타데이터와 함께 SQLite 에 저장합니다.
5. 개발자 식별 우선순위: `X-Copilot-User` 헤더 → `Proxy-Authorization`(Basic) 사용자명
   → 클라이언트 IP.
6. **호출 프로세스/프로젝트 귀속**(`attribution.py`): 모든 트래픽이 127.0.0.1 이므로
   클라이언트 **소스 포트 → PID(소켓 소유자) → 프로세스명·cwd** 를 `lsof` 로 역추적합니다.
   백그라운드 폴러가 established 연결을 주기적으로 스냅샷해 매핑을 안정적으로 유지합니다.
   프로젝트 폴더 결정 우선순위:
   - ① 소켓 PID 의 cwd 가 프로젝트 폴더면 그대로 사용 — **터미널/CLI 발신은 정확**
     (`project_source=cwd`).
   - ② VS Code 등 공유 헬퍼(소켓 cwd=`/`)면, 열린 워크스페이스(확장호스트 cwd)로 추론
     (단일=확정 `vscode-workspace`, 복수=`|` 연결 `vscode-workspace?`).
   - ③ 요청 본문의 파일 경로로 좁힘(`body-path`).

   > ⚠️ IDE 는 단일 공유 소켓으로 다중 창 요청을 보내므로, 개별 요청↔워크스페이스 매칭은
   > **best-effort** 입니다. 터미널/CLI 기반 호출은 정확합니다.

## 조회 (CLI)

```bash
python -m ghcp_proxy.cli recent           # 최근 캡처 (프로세스/프로젝트 컬럼 포함)
python -m ghcp_proxy.cli projects          # 프로젝트·프로세스별 호출/토큰 집계(기본: 추론만)
python -m ghcp_proxy.cli projects --all    # 비추론(model='unknown') 보조 트래픽 포함
python -m ghcp_proxy.cli tokens            # 개발자/모델별 토큰 집계(기본: 추론만)
python -m ghcp_proxy.cli tokens --all      # /models, /telemetry, /_ping, /agents/sessions 등 포함
python -m ghcp_proxy.cli show <id>         # 단건 상세 (마스킹된 payload)
python -m ghcp_proxy.cli purge             # 보존기간 초과 레코드 정리
# 모든 서브커맨드 --json 지원
```

`tokens`/`projects` 는 기본적으로 추론 호출만 집계해 `/models`, `/telemetry`, `/_ping`,
`/agents/sessions` 같은 `model='unknown'` 보조 트래픽을 제외합니다. 운영 보조 트래픽까지
확인해야 할 때만 `--all` 을 사용하세요.

## 테스트

```bash
pytest -q                      # 단위/통합 테스트 (32 cases)
python scripts/smoke_live.py   # 실제 mitmdump 프로세스 라이브 캡처 검증
```

## 한계 / 다음 단계

- 마스킹은 PoC 수준의 정규식 best-effort 입니다. 운영에서는 DLP 엔진 연계 필요.
- 토큰 휴리스틱(≈4 chars/token)은 근사치입니다. 정확도가 필요하면 `tiktoken` 설치 또는
  GitHub Copilot Metrics API 로 조직 단위 집계를 교차 검증하세요(원문 미포함).
- SIEM/DLP 전송은 현재 `--json` 출력 기반입니다. 실시간 푸시(예: syslog/HTTP sink)는
  애드온에 sink 를 추가해 확장하세요.
- 인증(Basic/Kerberos), allowlist, 인증서 배포는 사내 Proxy/방화벽/MDM 정책과 연동 필요.
- 프로젝트 귀속은 IDE 공유 소켓 특성상 best-effort 입니다(터미널/CLI 는 정확). 정확한
  창↔요청 매칭이 필요하면 클라이언트 측 헤더 주입(예: 워크스페이스 ID) 방식을 검토하세요.

## 근거

아키텍처·공식 문서 근거는 `032-github-copilot-proxy-architecture-2026-06-02.html` §7 참조.
