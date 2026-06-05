import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ghcp_proxy.storage import Storage, CaptureRecord


def _rec(**kw):
    base = dict(
        ts=CaptureRecord.now_ts(),
        developer="alice",
        host="api.githubcopilot.com",
        model="gpt-4o",
        request_tokens=10,
        response_tokens=5,
        total_tokens=15,
    )
    base.update(kw)
    return CaptureRecord(**base)


def test_insert_and_get(tmp_path):
    with Storage(tmp_path / "t.db") as st:
        cid = st.insert(_rec(request_body="hi", response_body="yo"))
        row = st.get(cid)
        assert row["developer"] == "alice"
        assert row["request_body"] == "hi"
        assert st.count() == 1


def test_recent_order(tmp_path):
    with Storage(tmp_path / "t.db") as st:
        st.insert(_rec(developer="a"))
        st.insert(_rec(developer="b"))
        rows = st.recent()
        assert rows[0]["developer"] == "b"


def test_token_summary(tmp_path):
    with Storage(tmp_path / "t.db") as st:
        st.insert(_rec(developer="alice", total_tokens=15, request_tokens=10, response_tokens=5))
        st.insert(_rec(developer="alice", total_tokens=20, request_tokens=12, response_tokens=8))
        summary = st.token_summary()
        assert len(summary) == 1
        assert summary[0]["total_tokens"] == 35
        assert summary[0]["calls"] == 2


def test_token_summary_excludes_non_inference(tmp_path):
    with Storage(tmp_path / "t.db") as st:
        st.insert(_rec(model="gpt-4o", total_tokens=15))
        st.insert(_rec(model="unknown", total_tokens=0, request_tokens=0, response_tokens=0))
        # 기본: 비추론(unknown) 제외
        summary = st.token_summary()
        models = {r["model"] for r in summary}
        assert models == {"gpt-4o"}
        # --all 상응: 포함
        all_models = {r["model"] for r in st.token_summary(inference_only=False)}
        assert all_models == {"gpt-4o", "unknown"}


def test_project_summary_excludes_non_inference(tmp_path):
    with Storage(tmp_path / "t.db") as st:
        st.insert(_rec(model="gpt-4o", project_dir="/repo/a", total_tokens=15))
        st.insert(_rec(model="unknown", project_dir="/repo/a", total_tokens=0))
        assert sum(r["calls"] for r in st.project_summary()) == 1
        assert sum(r["calls"] for r in st.project_summary(inference_only=False)) == 2


def test_token_summary_aggregates_cache(tmp_path):
    with Storage(tmp_path / "t.db") as st:
        st.insert(_rec(model="claude-opus-4.8", request_tokens=54088,
                       response_tokens=588, total_tokens=54676,
                       cache_read_tokens=52308, cache_write_tokens=1778))
        st.insert(_rec(model="claude-opus-4.8", request_tokens=40411,
                       response_tokens=277, total_tokens=40688,
                       cache_read_tokens=40221, cache_write_tokens=6442))
        summary = st.token_summary()
        assert len(summary) == 1
        assert summary[0]["cache_read_tokens"] == 92529
        assert summary[0]["cache_write_tokens"] == 8220


def test_purge_old(tmp_path):
    old_ts = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
    with Storage(tmp_path / "t.db") as st:
        st.insert(_rec(ts=old_ts))
        st.insert(_rec())  # fresh
        deleted = st.purge(retention_days=30)
        assert deleted == 1
        assert st.count() == 1


def test_purge_disabled(tmp_path):
    with Storage(tmp_path / "t.db") as st:
        st.insert(_rec())
        assert st.purge(retention_days=0) == 0
        assert st.count() == 1
