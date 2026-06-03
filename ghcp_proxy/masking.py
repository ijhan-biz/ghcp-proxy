"""민감정보 마스킹.

프롬프트/응답에는 소스코드·비밀정보가 포함될 수 있으므로 저장 전 마스킹한다.
대표적인 비밀 패턴을 정규식으로 치환한다. PoC 수준의 best-effort 이며,
운영 환경에서는 DLP 엔진/사내 룰과 병행해야 한다.
"""
from __future__ import annotations

import re
from typing import Pattern

# (이름, 패턴, 치환문자열) 순서대로 적용
_RULES: list[tuple[str, Pattern[str], str]] = [
    (
        "private_key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    (
        "github_token",
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}\b"),
        "[REDACTED_GITHUB_TOKEN]",
    ),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[REDACTED_OPENAI_KEY]"),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED_SLACK_TOKEN]"),
    (
        "bearer",
        re.compile(r"(?i)\b(authorization|bearer)\b\s*[:=]?\s*[A-Za-z0-9._\-]{20,}"),
        "[REDACTED_AUTH]",
    ),
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
        "[REDACTED_JWT]",
    ),
    (
        "email",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "[REDACTED_EMAIL]",
    ),
]


def mask_text(text: str) -> tuple[str, int]:
    """텍스트를 마스킹한다.

    반환: (마스킹된 텍스트, 매칭 건수)
    """
    if not text:
        return text, 0
    total = 0
    for _name, pattern, repl in _RULES:
        text, n = pattern.subn(repl, text)
        total += n
    return text, total


def rule_names() -> list[str]:
    return [name for name, _p, _r in _RULES]
