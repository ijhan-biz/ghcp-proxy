"""SQLite 저장소.

캡처된 요청/응답 payload 와 메타데이터(개발자·시간·모델·토큰)를 저장하고
조회·집계·보존정리(purge) 기능을 제공한다.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS captures (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ts               TEXT    NOT NULL,
    developer        TEXT,
    client_ip        TEXT,
    host             TEXT,
    method           TEXT,
    path             TEXT,
    status_code      INTEGER,
    model            TEXT,
    request_tokens   INTEGER,
    response_tokens  INTEGER,
    total_tokens     INTEGER,
    token_source     TEXT,
    masked           INTEGER DEFAULT 0,
    mask_hits        INTEGER DEFAULT 0,
    client_pid       INTEGER,
    client_process   TEXT,
    project_dir      TEXT,
    project_source   TEXT,
    request_body     TEXT,
    response_body    TEXT,
    flow_id          TEXT
);
CREATE INDEX IF NOT EXISTS idx_captures_ts ON captures(ts);
CREATE INDEX IF NOT EXISTS idx_captures_developer ON captures(developer);
CREATE INDEX IF NOT EXISTS idx_captures_model ON captures(model);
"""

# 기존 DB 호환을 위한 추가 컬럼(없으면 ALTER 로 보강)
_EXTRA_COLUMNS = {
    "client_pid": "INTEGER",
    "client_process": "TEXT",
    "project_dir": "TEXT",
    "project_source": "TEXT",
}


@dataclass
class CaptureRecord:
    ts: str
    developer: Optional[str] = None
    client_ip: Optional[str] = None
    host: Optional[str] = None
    method: Optional[str] = None
    path: Optional[str] = None
    status_code: Optional[int] = None
    model: Optional[str] = None
    request_tokens: Optional[int] = None
    response_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    token_source: Optional[str] = None
    masked: int = 0
    mask_hits: int = 0
    client_pid: Optional[int] = None
    client_process: Optional[str] = None
    project_dir: Optional[str] = None
    project_source: Optional[str] = None
    request_body: Optional[str] = None
    response_body: Optional[str] = None
    flow_id: Optional[str] = None

    @staticmethod
    def now_ts() -> str:
        return datetime.now(timezone.utc).isoformat()


# 모델 필드가 없는(=추론이 아닌) 보조 트래픽 식별자.
# /models, /telemetry, /_ping, /agents/sessions 등은 model 이 없어 'unknown' 으로 저장된다.
NON_INFERENCE_MODEL = "unknown"


def _inference_where(inference_only: bool) -> str:
    """집계에서 비추론(보조) 트래픽을 제외하는 WHERE 절을 만든다."""
    if not inference_only:
        return ""
    return f" WHERE model IS NOT NULL AND model != '{NON_INFERENCE_MODEL}'"


class Storage:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        existing = {
            row[1] for row in self._conn.execute("PRAGMA table_info(captures)").fetchall()
        }
        for col, decl in _EXTRA_COLUMNS.items():
            if col not in existing:
                self._conn.execute(f"ALTER TABLE captures ADD COLUMN {col} {decl}")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_captures_project ON captures(project_dir)"
        )

    def insert(self, record: CaptureRecord) -> int:
        data = asdict(record)
        cols = ", ".join(data.keys())
        placeholders = ", ".join(f":{k}" for k in data.keys())
        cur = self._conn.execute(
            f"INSERT INTO captures ({cols}) VALUES ({placeholders})", data
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, ts, developer, host, model, request_tokens, response_tokens,"
            " total_tokens, status_code, mask_hits, client_process, client_pid,"
            " project_dir, project_source FROM captures ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get(self, capture_id: int) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM captures WHERE id = ?", (capture_id,)
        ).fetchone()
        return dict(row) if row else None

    def token_summary(self, inference_only: bool = True) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT developer, model, COUNT(*) AS calls,"
            " COALESCE(SUM(request_tokens),0) AS req_tokens,"
            " COALESCE(SUM(response_tokens),0) AS resp_tokens,"
            " COALESCE(SUM(total_tokens),0) AS total_tokens"
            " FROM captures" + _inference_where(inference_only) +
            " GROUP BY developer, model ORDER BY total_tokens DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def project_summary(self, inference_only: bool = True) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT COALESCE(project_dir,'(unknown)') AS project,"
            " COALESCE(client_process,'?') AS process,"
            " COUNT(*) AS calls, COALESCE(SUM(total_tokens),0) AS total_tokens"
            " FROM captures" + _inference_where(inference_only) +
            " GROUP BY project, process ORDER BY total_tokens DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def purge(self, retention_days: int) -> int:
        """retention_days 보다 오래된 레코드 삭제. 0 이하면 아무것도 안 함."""
        if retention_days <= 0:
            return 0
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=retention_days)
        ).isoformat()
        cur = self._conn.execute("DELETE FROM captures WHERE ts < ?", (cutoff,))
        self._conn.commit()
        return cur.rowcount

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM captures").fetchone()[0])

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
