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


# usage 객체로 인식하기 위한 키(OpenAI + Anthropic 스키마 모두 포함).
_USAGE_KEYS = (
    "total_tokens", "prompt_tokens", "completion_tokens",  # OpenAI
    "input_tokens", "output_tokens",                        # Anthropic
    "cache_read_input_tokens", "cache_creation_input_tokens",
)


def usage_from_response(body: str) -> Optional[dict]:
    """응답 JSON 에서 usage 를 추출해 정규화한다.

    OpenAI(`prompt_tokens`/`completion_tokens`/`total_tokens`, 캐시는
    `prompt_tokens_details.cached_tokens`)와 Anthropic(`input_tokens`/
    `output_tokens`/`cache_read_input_tokens`/`cache_creation_input_tokens`)
    스키마를 모두 지원한다.

    스트리밍(SSE)에서는 usage 가 여러 청크에 나뉘어 온다. 특히 Anthropic 은
    `message_start` 에 입력/캐시 토큰을, `message_delta` 에 최종 출력 토큰을
    싣는다. 따라서 단순히 마지막 usage 로 덮어쓰지 않고 모든 청크의 값을
    필드별 최댓값으로 병합한다(각 카운터는 단일값이거나 누적 최종값이라 안전).

    반환 dict 키:
        prompt_tokens, completion_tokens, total_tokens,
        cache_read_tokens, cache_write_tokens
    """
    if not body:
        return None
    merged: dict[str, int] = {}
    seen = False
    for candidate in _iter_json_objects(body):
        usage = _find_usage(candidate)
        if usage is None:
            continue
        seen = True
        for key, val in _flatten_usage(usage).items():
            if isinstance(val, int):
                merged[key] = max(merged.get(key, 0), val)
    if not seen:
        return None
    return _normalize_usage(merged)


def _find_usage(candidate: object) -> Optional[dict]:
    """JSON 후보에서 usage dict 를 찾는다. Anthropic SSE 는 message 안에 둔다."""
    if not isinstance(candidate, dict):
        return None
    usage = candidate.get("usage")
    if not isinstance(usage, dict):
        message = candidate.get("message")
        usage = message.get("usage") if isinstance(message, dict) else None
    if isinstance(usage, dict) and any(k in usage for k in _USAGE_KEYS):
        return usage
    return None


def _flatten_usage(usage: dict) -> dict[str, int]:
    """중첩된 캐시 detail(예: OpenAI prompt_tokens_details)을 평탄화한다."""
    flat = {k: v for k, v in usage.items() if isinstance(v, int)}
    details = usage.get("prompt_tokens_details")
    if isinstance(details, dict) and isinstance(details.get("cached_tokens"), int):
        flat["cached_tokens"] = details["cached_tokens"]
    return flat


def _normalize_usage(u: dict[str, int]) -> dict:
    """OpenAI/Anthropic usage 를 공통 스키마로 변환한다.

    prompt_tokens 는 '전체 입력'(캐시 포함)을 의미하도록 통일한다. Anthropic 의
    input_tokens 는 캐시를 제외한 신규 입력이므로 캐시 read/write 를 더해 보정한다.
    """
    is_anthropic = "input_tokens" in u or "output_tokens" in u or \
        "cache_read_input_tokens" in u or "cache_creation_input_tokens" in u
    if is_anthropic:
        cache_read = u.get("cache_read_input_tokens", 0)
        cache_write = u.get("cache_creation_input_tokens", 0)
        prompt = u.get("input_tokens", 0) + cache_read + cache_write
        completion = u.get("output_tokens", 0)
        total = prompt + completion
    else:
        prompt = u.get("prompt_tokens", 0)
        completion = u.get("completion_tokens", 0)
        total = u.get("total_tokens") or (prompt + completion)
        cache_read = u.get("cached_tokens", 0)  # OpenAI: prompt 에 이미 포함된 부분
        cache_write = 0
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
    }


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
