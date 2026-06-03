"""토큰 산정.

tiktoken 이 설치되어 있으면 정확한 토큰 수를, 없으면 문자 기반 휴리스틱
(대략 4 chars/token)을 사용한다. 응답 본문에 usage 가 있으면 그것을 우선한다.
"""
from __future__ import annotations

import json
from typing import Optional

try:
    import tiktoken  # 선택적 의존성
    _ENC = tiktoken.get_encoding("cl100k_base")
except Exception:  # pragma: no cover - 폴백 경로
    _ENC = None


def estimate_tokens(text: str) -> int:
    """텍스트의 토큰 수를 추정한다."""
    if not text:
        return 0
    if _ENC is not None:
        try:
            return len(_ENC.encode(text))
        except Exception:
            pass
    # 휴리스틱: 평균 4 문자 ≈ 1 토큰, 최소 1
    return max(1, round(len(text) / 4))


def estimator_name() -> str:
    return "tiktoken/cl100k_base" if _ENC is not None else "heuristic/4chars"


def usage_from_response(body: str) -> Optional[dict]:
    """응답 JSON 에서 usage(prompt_tokens/completion_tokens/total_tokens)를 추출.

    OpenAI 호환 스키마 기준. 스트리밍(SSE)에서는 마지막 data 청크에 usage 가
    포함될 수 있으므로 모든 JSON 후보를 스캔해 마지막 usage 를 사용한다.
    """
    if not body:
        return None
    found: Optional[dict] = None
    for candidate in _iter_json_objects(body):
        usage = candidate.get("usage") if isinstance(candidate, dict) else None
        if isinstance(usage, dict) and any(
            k in usage for k in ("total_tokens", "prompt_tokens", "completion_tokens")
        ):
            found = {
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
            }
    return found


def model_from_request(body: str) -> Optional[str]:
    """요청 JSON 에서 model 필드를 추출."""
    for candidate in _iter_json_objects(body):
        if isinstance(candidate, dict) and isinstance(candidate.get("model"), str):
            return candidate["model"]
    return None


def model_from_response(body: str) -> Optional[str]:
    """응답 JSON/SSE 에서 model 필드를 추출.

    요청 본문에 model 이 없거나 'auto' 류 라우팅이라 확정 모델을 알 수 없을 때
    실제 응답을 서빙한 모델명을 보조로 확인하기 위한 경로다. OpenAI 호환 응답과
    스트리밍(SSE) 청크는 model 을 포함하는 경우가 많으므로 첫 후보를 사용한다.
    """
    for candidate in _iter_json_objects(body):
        if isinstance(candidate, dict) and isinstance(candidate.get("model"), str):
            model = candidate["model"].strip()
            if model:
                return model
    return None


def _iter_json_objects(body: str):
    """본문에서 JSON 객체들을 best-effort 로 추출.

    - 전체가 하나의 JSON 이면 그대로
    - SSE(`data: {...}` 줄 단위)면 각 줄 파싱
    """
    body = body.strip()
    if not body:
        return
    # 1) 전체 JSON 시도
    try:
        yield json.loads(body)
        return
    except Exception:
        pass
    # 2) 라인 단위 (SSE 포함)
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("data:"):
            line = line[len("data:"):].strip()
        if line == "[DONE]" or not (line.startswith("{") or line.startswith("[")):
            continue
        try:
            yield json.loads(line)
        except Exception:
            continue
