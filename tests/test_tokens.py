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


def test_usage_openai_cached_tokens():
    body = (
        '{"usage": {"prompt_tokens": 100, "completion_tokens": 20,'
        ' "total_tokens": 120, "prompt_tokens_details": {"cached_tokens": 80}}}'
    )
    usage = tokens.usage_from_response(body)
    assert usage["prompt_tokens"] == 100
    assert usage["total_tokens"] == 120
    assert usage["cache_read_tokens"] == 80
    assert usage["cache_write_tokens"] == 0


def test_usage_anthropic_sse_merges_cache_and_output():
    # message_start 에 입력/캐시, message_delta 에 최종 출력이 나뉘어 온다.
    body = (
        'event: message_start\n'
        'data: {"type":"message_start","message":{"model":"claude-opus-4-8",'
        '"usage":{"input_tokens":2,"cache_read_input_tokens":52308,'
        '"cache_creation_input_tokens":1778,"output_tokens":2}}}\n'
        'event: message_delta\n'
        'data: {"type":"message_delta","usage":{"output_tokens":588}}\n'
    )
    usage = tokens.usage_from_response(body)
    assert usage is not None
    # prompt = input + cache_read + cache_write
    assert usage["prompt_tokens"] == 2 + 52308 + 1778
    assert usage["completion_tokens"] == 588
    assert usage["cache_read_tokens"] == 52308
    assert usage["cache_write_tokens"] == 1778
    assert usage["total_tokens"] == usage["prompt_tokens"] + 588
