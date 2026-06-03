"""대시보드 서버 테스트: HTTP 엔드포인트 + SSE broadcast."""
import json
import os
import queue
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ghcp_proxy.dashboard import DashboardServer
from ghcp_proxy.storage import Storage, CaptureRecord


def _seed(db_path):
    with Storage(db_path) as st:
        st.insert(
            CaptureRecord(
                ts=CaptureRecord.now_ts(),
                developer="alice",
                host="api.githubcopilot.com",
                model="gpt-4o",
                request_tokens=10,
                response_tokens=5,
                total_tokens=15,
                token_source="api_usage",
            )
        )


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode("utf-8")


def test_dashboard_endpoints(tmp_path):
    db = tmp_path / "d.db"
    _seed(db)
    srv = DashboardServer(db, host="127.0.0.1", port=0)
    url = srv.start()
    try:
        st, body = _get(url)
        assert st == 200 and "실시간" in body

        st, body = _get(url + "api/recent")
        rows = json.loads(body)
        assert rows and rows[0]["developer"] == "alice"

        st, body = _get(url + "api/tokens")
        agg = json.loads(body)
        assert agg and agg[0]["total_tokens"] == 15
    finally:
        srv.stop()


def test_broadcast_reaches_registered_client(tmp_path):
    db = tmp_path / "d.db"
    _seed(db)
    srv = DashboardServer(db, host="127.0.0.1", port=0)
    q: queue.Queue = queue.Queue()
    srv._register(q)
    srv.broadcast({"id": 1, "developer": "bob", "total_tokens": 7})
    evt = q.get(timeout=2)
    assert evt["developer"] == "bob"
    assert srv.client_count == 1
    srv._unregister(q)
    assert srv.client_count == 0
