import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ghcp_proxy import tokens


def test_estimate_tokens_nonempty():
    assert tokens.estimate_tokens("hello world") > 0


def test_estimate_tokens_empty():
    assert tokens.estimate_tokens("") == 0


def test_model_from_request_json():
    body = '{"model": "gpt-4o", "messages": []}'
    assert tokens.model_from_request(body) == "gpt-4o"


def test_model_from_request_none():
    assert tokens.model_from_request("not json") is None


def test_model_from_response_plain_json():
    body = '{"id": "x", "model": "gpt-5.3-codex", "choices": []}'
    assert tokens.model_from_response(body) == "gpt-5.3-codex"


def test_model_from_response_sse():
    body = (
        'data: {"choices":[{"delta":{"content":"hi"}}],"model":"claude-opus-4.8"}\n'
        "data: [DONE]\n"
    )
    assert tokens.model_from_response(body) == "claude-opus-4.8"


def test_model_from_response_absent():
    assert tokens.model_from_response('{"choices": []}') is None


def test_usage_from_plain_json():
    body = '{"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}'
    usage = tokens.usage_from_response(body)
    assert usage["total_tokens"] == 15
    assert usage["prompt_tokens"] == 10


def test_usage_from_sse_stream():
    body = (
        'data: {"choices":[{"delta":{"content":"hi"}}]}\n'
        'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}}\n'
        "data: [DONE]\n"
    )
    usage = tokens.usage_from_response(body)
    assert usage is not None
    assert usage["total_tokens"] == 5


def test_usage_absent():
    assert tokens.usage_from_response('{"choices": []}') is None
