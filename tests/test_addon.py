"""애드온 통합 테스트: 가짜 flow 로 캡처→저장 경로를 검증."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

os.environ["GHCP_DASHBOARD"] = "0"  # addon 단위 테스트에서는 대시보드 비활성화

import importlib.util

from ghcp_proxy.storage import Storage


def _load_addon():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "addons", "capture.py")
    spec = importlib.util.spec_from_file_location("capture_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Headers(dict):
    def get(self, k, default=None):  # case-insensitive
        for key, val in self.items():
            if key.lower() == k.lower():
                return val
        return default


class _Req:
    def __init__(self, host, body, headers=None, method="POST", path="/chat/completions"):
        self.pretty_host = host
        self.raw_content = body
        self.headers = _Headers(headers or {})
        self.method = method
        self.path = path


class _Resp:
    def __init__(self, body, status=200):
        self.raw_content = body
        self.status_code = status


class _Conn:
    peername = ("10.0.0.5", 5555)


class _Flow:
    def __init__(self, req, resp):
        self.request = req
        self.response = resp
        self.client_conn = _Conn()
        self.id = "flow-123"


def _make_addon(tmp_path):
    mod = _load_addon()
    addon = mod.CopilotCapture()
    addon.storage.close()
    addon.storage = Storage(tmp_path / "addon.db")

    class _StubAttr:
        def attribute(self, sport, body=""):
            return {
                "client_pid": sport,
                "client_process": "stub-proc",
                "project_dir": None,
                "project_source": None,
            }

    addon.attributor = _StubAttr()
    return addon


def test_allowlisted_flow_is_captured(tmp_path):
    addon = _make_addon(tmp_path)
    req = _Req(
        "api.githubcopilot.com",
        b'{"model":"gpt-4o","messages":[{"role":"user","content":"hi my key ghp_abcdefghijklmnopqrstuvwxyz0123456789"}]}',
        headers={"X-Copilot-User": "alice"},
    )
    resp = _Resp(b'{"choices":[{"message":{"content":"hello"}}],"usage":{"prompt_tokens":12,"completion_tokens":3,"total_tokens":15}}')
    addon.response(_Flow(req, resp))

    rows = addon.storage.recent()
    assert len(rows) == 1
    r = addon.storage.get(rows[0]["id"])
    assert r["developer"] == "alice"
    assert r["model"] == "gpt-4o"
    assert r["total_tokens"] == 15
    assert r["token_source"] == "api_usage"
    # 마스킹 적용 확인
    assert "ghp_" not in r["request_body"]
    assert r["mask_hits"] >= 1
    addon.storage.close()


def test_non_allowlisted_flow_skipped(tmp_path):
    addon = _make_addon(tmp_path)
    req = _Req("example.com", b'{"model":"x"}')
    resp = _Resp(b"{}")
    addon.response(_Flow(req, resp))
    assert addon.storage.count() == 0
    addon.storage.close()


def test_developer_falls_back_to_ip(tmp_path):
    addon = _make_addon(tmp_path)
    req = _Req("api.githubcopilot.com", b'{"model":"gpt-4o"}')
    resp = _Resp(b'{"choices":[]}')
    addon.response(_Flow(req, resp))
    r = addon.storage.get(addon.storage.recent()[0]["id"])
    assert r["developer"] == "10.0.0.5"
    addon.storage.close()
