"""mitmproxy 애드온: GitHub Copilot 트래픽 캡처.

사용:
    mitmdump -s addons/capture.py

동작:
- allowlist 호스트로 향하는 응답(flow)을 가로채 요청/응답 payload 를 캡처
- model/token 메타데이터 산정, 민감정보 마스킹 후 SQLite 에 저장

개발자 식별 우선순위:
    1) X-Copilot-User 요청 헤더
    2) Proxy-Authorization(Basic) 의 사용자명
    3) 클라이언트 IP
"""
from __future__ import annotations

import base64
import logging
import sys
from dataclasses import asdict
from pathlib import Path

# 패키지 임포트를 위해 프로젝트 루트를 path 에 추가
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from ghcp_proxy.config import load_config  # noqa: E402
from ghcp_proxy import masking, tokens  # noqa: E402
from ghcp_proxy.storage import Storage, CaptureRecord  # noqa: E402
from ghcp_proxy.dashboard import DashboardServer  # noqa: E402
from ghcp_proxy.attribution import Attributor  # noqa: E402

logger = logging.getLogger("ghcp_capture")


class CopilotCapture:
    def __init__(self) -> None:
        self.cfg = load_config()
        self.storage = Storage(self.cfg.resolved_db_path())
        self.attributor = Attributor()
        self.dashboard: DashboardServer | None = None
        if self.cfg.dashboard.enabled:
            self.dashboard = DashboardServer(
                self.cfg.resolved_db_path(),
                host=self.cfg.dashboard.host,
                port=self.cfg.dashboard.port,
            )
            url = self.dashboard.start()
            logger.info("실시간 대시보드: %s", url)
        logger.info(
            "ghcp capture 시작 | db=%s | 토큰=%s | 마스킹=%s",
            self.cfg.resolved_db_path(),
            tokens.estimator_name(),
            self.cfg.masking.enabled,
        )

    # mitmproxy hook
    def response(self, flow) -> None:  # noqa: ANN001
        try:
            host = flow.request.pretty_host
            if not self.cfg.host_allowed(host):
                return
            self._capture(flow)
        except Exception:  # 캡처 실패가 프록시 통신을 막지 않도록
            logger.exception("capture 처리 중 오류")

    def done(self) -> None:
        try:
            self.attributor.stop()
        except Exception:
            pass
        try:
            if self.dashboard is not None:
                self.dashboard.stop()
        except Exception:
            pass
        try:
            self.storage.close()
        except Exception:
            pass

    # 내부 로직
    def _capture(self, flow) -> None:  # noqa: ANN001
        req_body = self._decode(flow.request.raw_content)
        resp_body = ""
        if self.cfg.capture.store_response and flow.response is not None:
            resp_body = self._decode(flow.response.raw_content)

        model = (
            tokens.model_from_request(req_body)
            or tokens.model_from_response(resp_body)
            or "unknown"
        )

        # 호출 프로세스/프로젝트 귀속 (마스킹 전 원문 경로로 추론)
        attr = self.attributor.attribute(self._source_port(flow), req_body)

        # 토큰은 마스킹 전 원문 길이 기준으로 산정
        req_tokens = tokens.estimate_tokens(req_body)
        usage = tokens.usage_from_response(resp_body)
        if usage and usage.get("total_tokens"):
            resp_tokens = usage.get("completion_tokens")
            total_tokens = usage.get("total_tokens")
            req_tokens = usage.get("prompt_tokens") or req_tokens
            token_source = "api_usage"
        else:
            resp_tokens = tokens.estimate_tokens(resp_body)
            total_tokens = (req_tokens or 0) + (resp_tokens or 0)
            token_source = tokens.estimator_name()

        masked_flag = 0
        mask_hits = 0
        if self.cfg.masking.enabled:
            req_body, n1 = masking.mask_text(req_body)
            resp_body, n2 = masking.mask_text(resp_body)
            masked_flag = 1
            mask_hits = n1 + n2

        req_body = self._truncate(req_body)
        resp_body = self._truncate(resp_body)

        record = CaptureRecord(
            ts=CaptureRecord.now_ts(),
            developer=self._developer(flow),
            client_ip=self._client_ip(flow),
            host=flow.request.pretty_host,
            method=flow.request.method,
            path=flow.request.path,
            status_code=flow.response.status_code if flow.response else None,
            model=model,
            request_tokens=req_tokens,
            response_tokens=resp_tokens,
            total_tokens=total_tokens,
            token_source=token_source,
            masked=masked_flag,
            mask_hits=mask_hits,
            client_pid=attr.get("client_pid"),
            client_process=attr.get("client_process"),
            project_dir=attr.get("project_dir"),
            project_source=attr.get("project_source"),
            request_body=req_body,
            response_body=resp_body,
            flow_id=getattr(flow, "id", None),
        )
        cid = self.storage.insert(record)
        if self.dashboard is not None:
            event = asdict(record)
            event["id"] = cid
            # payload 는 대시보드 실시간 행에 불필요 → 제외(전송량/노출 최소화)
            event.pop("request_body", None)
            event.pop("response_body", None)
            self.dashboard.broadcast(event)
        logger.info(
            "captured #%d | %s | %s | proj=%s | model=%s | tokens=%s(%s) | mask=%d",
            cid, record.developer, record.client_process, record.project_dir,
            model, total_tokens, token_source, mask_hits,
        )

    def _truncate(self, text: str) -> str:
        limit = self.cfg.capture.max_body_bytes
        if limit and text and len(text.encode("utf-8")) > limit:
            return text.encode("utf-8")[:limit].decode("utf-8", "ignore") + "…[truncated]"
        return text

    @staticmethod
    def _decode(raw: bytes | None) -> str:
        if not raw:
            return ""
        return raw.decode("utf-8", "replace")

    @staticmethod
    def _client_ip(flow) -> str | None:  # noqa: ANN001
        peer = getattr(flow.client_conn, "peername", None)
        if peer and len(peer) >= 1:
            return str(peer[0])
        return None

    @staticmethod
    def _source_port(flow) -> int | None:  # noqa: ANN001
        peer = getattr(flow.client_conn, "peername", None)
        if peer and len(peer) >= 2:
            try:
                return int(peer[1])
            except (TypeError, ValueError):
                return None
        return None

    def _developer(self, flow) -> str | None:  # noqa: ANN001
        user = flow.request.headers.get("X-Copilot-User")
        if user:
            return user
        auth = flow.request.headers.get("Proxy-Authorization")
        if auth and auth.lower().startswith("basic "):
            try:
                decoded = base64.b64decode(auth.split(" ", 1)[1]).decode("utf-8", "ignore")
                return decoded.split(":", 1)[0] or None
            except Exception:
                pass
        return self._client_ip(flow)


addons = [CopilotCapture()]
