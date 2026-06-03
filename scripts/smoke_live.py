"""실제 mitmdump 프로세스를 띄워 캡처 동작을 검증하는 라이브 스모크 테스트.

reverse 모드로 로컬 mock upstream 앞에 캡처 애드온을 두고, 임시 config(GHCP_CONFIG)
로 mock 호스트를 allowlist 에 넣어 캡처가 실제로 DB 에 기록되는지 검증한다.
실제 Copilot 도메인 필터링은 단위 테스트(test_config/test_addon)에서 검증한다.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class MockCopilot(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        body = json.dumps(
            {
                "choices": [{"message": {"content": "hello from mock"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15},
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def main():
    import requests

    mock_port = _free_port()
    rev_port = _free_port()
    tmpdir = tempfile.mkdtemp(prefix="ghcp_smoke_")
    db_path = os.path.join(tmpdir, "captures.db")
    cfg_path = os.path.join(tmpdir, "config.yaml")

    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write(
            "allowlist_hosts:\n  - 127.0.0.1\n"
            f"storage:\n  db_path: {db_path}\n  retention_days: 30\n"
            "masking:\n  enabled: true\n"
            "capture:\n  store_response: true\n  max_body_bytes: 1048576\n"
            "dashboard:\n  enabled: false\n"
        )

    httpd = ThreadingHTTPServer(("127.0.0.1", mock_port), MockCopilot)
    Thread(target=httpd.serve_forever, daemon=True).start()

    env = dict(os.environ, GHCP_CONFIG=cfg_path)
    cmd = [
        "mitmdump",
        "--listen-port", str(rev_port),
        "--set", f"confdir={ROOT}/.mitmproxy",
        "-s", os.path.join(ROOT, "addons", "capture.py"),
        "--mode", f"reverse:http://127.0.0.1:{mock_port}",
    ]
    proc = subprocess.Popen(
        cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    try:
        time.sleep(4)
        payload = {
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "secret ghp_abcdefghijklmnopqrstuvwxyz0123456789"}
            ],
        }
        r = requests.post(
            f"http://127.0.0.1:{rev_port}/chat/completions",
            json=payload,
            headers={"X-Copilot-User": "smoke-user"},
            timeout=10,
        )
        assert r.status_code == 200, r.status_code
        time.sleep(1)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        httpd.shutdown()

    sys.path.insert(0, ROOT)
    from ghcp_proxy.storage import Storage

    with Storage(db_path) as st:
        rows = st.recent(limit=1)
        assert rows, "캡처된 레코드가 없습니다"
        rec = st.get(rows[0]["id"])

    assert rec["developer"] == "smoke-user", rec["developer"]
    assert rec["model"] == "gpt-4o", rec["model"]
    assert rec["total_tokens"] == 15, rec["total_tokens"]
    assert rec["token_source"] == "api_usage", rec["token_source"]
    assert "ghp_" not in (rec["request_body"] or ""), "마스킹 실패"
    print(
        "LIVE SMOKE OK:",
        json.dumps(
            {
                "id": rec["id"],
                "developer": rec["developer"],
                "model": rec["model"],
                "total_tokens": rec["total_tokens"],
                "mask_hits": rec["mask_hits"],
                "token_source": rec["token_source"],
            },
            ensure_ascii=False,
        ),
    )


if __name__ == "__main__":
    main()
