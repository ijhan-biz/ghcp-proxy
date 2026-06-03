"""호출 프로세스/프로젝트 귀속(attribution).

모든 트래픽이 127.0.0.1 이므로 클라이언트 소스 포트로 발신 프로세스를 역추적한다.
  소스포트 → PID(소켓 소유자) → 프로세스명 + cwd
프로젝트 폴더 결정 우선순위:
  1) 소켓 PID 의 cwd 가 실제 프로젝트 폴더면 그대로 (터미널/CLI 발신 → 정확)
  2) VS Code 등 공유 헬퍼면, 열려 있는 워크스페이스(확장호스트 cwd)로 추론
  3) 요청 본문에 든 파일 경로에서 추론
lsof 호출 비용을 줄이기 위해 짧은 TTL 캐시를 사용한다(mitmproxy 이벤트 루프 블로킹 최소화).
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from typing import Optional

_SELF_PID = os.getpid()
_HOME = os.path.expanduser("~")

# 프로젝트로 보지 않는 경로 조각
_NON_PROJECT = (
    "/Library/", "/Application Support/", "/.Trash", "/System/", "/usr/",
    "/private/", "/Applications/",
)

_PATH_RE = re.compile(r"(?:file://)?(" + re.escape(_HOME) + r"/[^\s\"'`,;:?*]+)")


def _run(cmd: list[str], timeout: float = 1.5) -> str:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        ).stdout
    except Exception:
        return ""


def is_project_dir(path: Optional[str]) -> bool:
    if not path or path == "/":
        return False
    if not path.startswith(_HOME + "/"):
        return False
    if any(seg in path for seg in _NON_PROJECT):
        return False
    # 홈 바로 아래(깊이 1)는 보통 프로젝트 루트가 아님 → 깊이 2 이상 요구
    rel = path[len(_HOME) + 1:]
    return rel.count("/") >= 1


class Attributor:
    def __init__(self, port_ttl: float = 2.0, pid_ttl: float = 5.0, ws_ttl: float = 5.0,
                 poll_interval: float = 1.0, snap_evict: float = 4.0, poll: bool = True):
        self.port_ttl = port_ttl
        self.pid_ttl = pid_ttl
        self.ws_ttl = ws_ttl
        self.poll_interval = poll_interval
        self.snap_evict = snap_evict
        self._port_cache: dict[int, tuple[float, tuple[int, str] | None]] = {}
        self._cwd_cache: dict[int, tuple[float, Optional[str]]] = {}
        self._ws_cache: tuple[float, list[str]] | None = None
        # 백그라운드 폴러가 채우는 스냅샷: sport -> (ts, pid, proc)
        self._snap: dict[int, tuple[float, int, str]] = {}
        self._snap_lock = threading.Lock()
        self._stop = threading.Event()
        self._poller: threading.Thread | None = None
        if poll:
            self._poller = threading.Thread(target=self._poll_loop, daemon=True)
            self._poller.start()

    def stop(self) -> None:
        self._stop.set()

    # established localhost 연결을 주기적으로 스냅샷 → sport→(pid,proc)
    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._snapshot_once()
            except Exception:
                pass
            self._stop.wait(self.poll_interval)

    def _snapshot_once(self) -> None:
        out = _run(["lsof", "-nP", "-iTCP", "-sTCP:ESTABLISHED"], timeout=3.0)
        now = time.time()
        with self._snap_lock:
            for line in out.splitlines()[1:]:
                parts = line.split()
                if len(parts) < 9:
                    continue
                try:
                    pid = int(parts[1])
                except ValueError:
                    continue
                if pid == _SELF_PID:
                    continue
                # NAME 필드 탐색 (-sTCP:ESTABLISHED 사용 시 끝에 '(ESTABLISHED)' 상태가 붙음)
                name = next((f for f in parts if "->" in f), "")
                if "->127.0.0.1:" not in name or not name.startswith("127.0.0.1:"):
                    continue
                try:
                    sport = int(name.split("->", 1)[0].split(":")[1])
                except (IndexError, ValueError):
                    continue
                self._snap[sport] = (now, pid, os.path.basename(parts[0]))
            # 오래된 항목 제거
            stale = [p for p, v in self._snap.items() if now - v[0] > self.snap_evict]
            for p in stale:
                del self._snap[p]

    # 소스포트 → (pid, 프로세스명): 스냅샷 우선, 없으면 단발 lsof
    def _pid_for_port(self, sport: int) -> tuple[int, str] | None:
        with self._snap_lock:
            snap = self._snap.get(sport)
        if snap:
            return (snap[1], self._proc_name(snap[1]))
        now = time.time()
        hit = self._port_cache.get(sport)
        if hit and now - hit[0] < self.port_ttl:
            return hit[1]
        out = _run(["lsof", "-nP", f"-iTCP:{sport}"])
        result: tuple[int, str] | None = None
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 9:
                continue
            try:
                pid = int(parts[1])
            except ValueError:
                continue
            if pid == _SELF_PID:
                continue
            name = next((f for f in parts if "->" in f), parts[-1])
            if f":{sport}->" in name:
                result = (pid, self._proc_name(pid))
                break
        self._port_cache[sport] = (now, result)
        return result

    def _proc_name(self, pid: int) -> str:
        out = _run(["ps", "-p", str(pid), "-o", "comm="]).strip()
        return os.path.basename(out) if out else "unknown"

    def _cwd_for_pid(self, pid: int) -> Optional[str]:
        now = time.time()
        hit = self._cwd_cache.get(pid)
        if hit and now - hit[0] < self.pid_ttl:
            return hit[1]
        out = _run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"])
        cwd = None
        for line in out.splitlines():
            if line.startswith("n"):
                cwd = line[1:]
                break
        self._cwd_cache[pid] = (now, cwd)
        return cwd

    def _vscode_workspaces(self) -> list[str]:
        now = time.time()
        if self._ws_cache and now - self._ws_cache[0] < self.ws_ttl:
            return self._ws_cache[1]
        pids = _run(["pgrep", "-f", "Code Helper"]).split()
        found: list[str] = []
        for p in pids:
            try:
                pid = int(p)
            except ValueError:
                continue
            cwd = self._cwd_for_pid(pid)
            if is_project_dir(cwd) and cwd not in found:
                found.append(cwd)
        self._ws_cache = (now, found)
        return found

    @staticmethod
    def _path_from_body(body: str) -> Optional[str]:
        if not body:
            return None
        m = _PATH_RE.search(body)
        return m.group(1) if m else None

    def attribute(self, source_port: Optional[int], request_body: str = "") -> dict:
        result = {
            "client_pid": None,
            "client_process": None,
            "project_dir": None,
            "project_source": None,
        }
        if not source_port:
            return result

        info = self._pid_for_port(source_port)
        if info:
            result["client_pid"], result["client_process"] = info
            cwd = self._cwd_for_pid(info[0])
            if is_project_dir(cwd):
                result["project_dir"] = cwd
                result["project_source"] = "cwd"
                return result

        # VS Code 등 공유 헬퍼: 열린 워크스페이스로 추론
        proc = (result["client_process"] or "").lower()
        if "code" in proc or "electron" in proc or result["project_dir"] is None:
            ws = self._vscode_workspaces()
            if len(ws) == 1:
                result["project_dir"] = ws[0]
                result["project_source"] = "vscode-workspace"
                return result
            elif len(ws) > 1:
                result["project_dir"] = " | ".join(ws)
                result["project_source"] = "vscode-workspace?"
                # 본문 경로로 좁힐 수 있으면 덮어쓰기
                bp = self._path_from_body(request_body)
                if bp:
                    for w in ws:
                        if bp.startswith(w):
                            result["project_dir"] = w
                            result["project_source"] = "body-path"
                            break
                return result

        bp = self._path_from_body(request_body)
        if bp:
            result["project_dir"] = bp
            result["project_source"] = "body-path"
        return result
