"""실시간 대시보드 서버 (stdlib 전용).

mitmproxy 애드온 프로세스 안에서 백그라운드 스레드로 HTTP 서버를 띄운다.
- GET /            대시보드 HTML
- GET /events      SSE 스트림 (캡처 발생 시 실시간 push)
- GET /api/recent  최근 캡처 JSON
- GET /api/tokens  개발자·모델별 토큰 집계 JSON

캡처가 저장되면 애드온이 broadcast() 를 호출해 모든 SSE 클라이언트로 push 한다.
추가 의존성 없이 동작하도록 표준 라이브러리만 사용한다.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .storage import Storage

logger = logging.getLogger("ghcp_dashboard")

_PAGE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Copilot 캡처 실시간 모니터</title>
<style>
  :root{--bg:#0d1117;--surface:#161b22;--border:#2d333b;--text:#e6edf3;--muted:#9da7b3;--accent:#2f81f7;--green:#3fb950;--amber:#d29922;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);font-family:-apple-system,"Segoe UI","Noto Sans KR",sans-serif;line-height:1.5}
  header{padding:18px 24px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:14px;flex-wrap:wrap}
  header h1{font-size:18px;margin:0}
  .dot{width:10px;height:10px;border-radius:50%;background:var(--muted);display:inline-block}
  .dot.on{background:var(--green);box-shadow:0 0 8px var(--green)}
  .wrap{padding:20px 24px;max-width:1200px;margin:0 auto}
  .cards{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:20px}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 18px;min-width:140px}
  .card .label{font-size:12px;color:var(--muted)}
  .card .val{font-size:24px;font-weight:700;margin-top:4px}
  h2{font-size:14px;color:var(--muted);margin:24px 0 10px;text-transform:uppercase;letter-spacing:.04em}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{border-bottom:1px solid var(--border);padding:8px 10px;text-align:left;vertical-align:top}
  th{color:var(--muted);font-weight:600}
  td.num{text-align:right;font-variant-numeric:tabular-nums}
  tr.flash{animation:flash 1.2s ease-out}
  @keyframes flash{from{background:rgba(47,129,247,.25)}to{background:transparent}}
  .pill{font-size:11px;padding:2px 8px;border-radius:999px;border:1px solid var(--border);color:var(--muted)}
  .pill.mask{color:var(--amber);border-color:#5a4413}
  code{background:#0b0f14;border:1px solid var(--border);border-radius:4px;padding:1px 5px;font-size:12px}
  .muted{color:var(--muted)}
</style>
</head>
<body>
<header>
  <h1>GitHub Copilot 캡처 · 실시간 모니터</h1>
  <span><span id="dot" class="dot"></span> <span id="status" class="muted">연결 중…</span></span>
</header>
<div class="wrap">
  <div class="cards">
    <div class="card"><div class="label">총 캡처</div><div id="c-count" class="val">0</div></div>
    <div class="card"><div class="label">총 토큰</div><div id="c-tokens" class="val">0</div></div>
    <div class="card"><div class="label">마스킹 히트</div><div id="c-mask" class="val">0</div></div>
    <div class="card"><div class="label">개발자 수</div><div id="c-devs" class="val">0</div></div>
  </div>

  <h2>실시간 캡처 (최신 200건)</h2>
  <table>
    <thead><tr><th>시각</th><th>개발자</th><th>프로세스</th><th>프로젝트</th><th>모델</th>
      <th class="num">req</th><th class="num">resp</th><th class="num">total</th><th>마스킹</th></tr></thead>
    <tbody id="rows"></tbody>
  </table>

  <h2>프로젝트·프로세스별 집계</h2>
  <table>
    <thead><tr><th>프로젝트</th><th>프로세스</th><th class="num">호출</th><th class="num">total 토큰</th></tr></thead>
    <tbody id="proj"></tbody>
  </table>

  <h2>개발자·모델별 토큰 집계</h2>
  <table>
    <thead><tr><th>개발자</th><th>모델</th><th class="num">호출</th>
      <th class="num">req</th><th class="num">resp</th><th class="num">total</th></tr></thead>
    <tbody id="agg"></tbody>
  </table>
</div>
<script>
const $=s=>document.querySelector(s);
const fmt=n=>(n==null?'-':Number(n).toLocaleString());
const esc=s=>String(s==null?'':s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
let totalCount=0,totalTokens=0,totalMask=0;
const devs=new Set();

function addRow(r,flash){
  const tb=$('#rows');
  const tr=document.createElement('tr');
  if(flash)tr.className='flash';
  const t=(r.ts||'').replace('T',' ').slice(0,19);
  const proj=r.project_dir?String(r.project_dir).split(' | ').map(p=>p.split('/').pop()).join(' | '):'<span class="muted">-</span>';
  const ptitle=r.project_dir?` title="${esc(r.project_dir)} (${esc(r.project_source)})"`:'';
  tr.innerHTML=`<td><code>${esc(t)}</code></td><td>${esc(r.developer)}</td>`+
    `<td>${esc(r.client_process)}</td><td${ptitle}>${proj}</td>`+
    `<td>${esc(r.model)}</td>`+
    `<td class="num">${fmt(r.request_tokens)}</td><td class="num">${fmt(r.response_tokens)}</td>`+
    `<td class="num">${fmt(r.total_tokens)}</td>`+
    `<td>${r.mask_hits>0?`<span class="pill mask">${r.mask_hits}</span>`:'<span class="muted">-</span>'}</td>`;
  tb.prepend(tr);
  while(tb.children.length>200)tb.removeChild(tb.lastChild);
}
function bumpCards(r){
  totalCount++;totalTokens+=(r.total_tokens||0);totalMask+=(r.mask_hits||0);
  if(r.developer)devs.add(r.developer);
  $('#c-count').textContent=fmt(totalCount);
  $('#c-tokens').textContent=fmt(totalTokens);
  $('#c-mask').textContent=fmt(totalMask);
  $('#c-devs').textContent=fmt(devs.size);
}
async function loadAgg(){
  const a=await (await fetch('/api/tokens')).json();
  $('#agg').innerHTML=a.map(r=>`<tr><td>${esc(r.developer)}</td><td>${esc(r.model)}</td>`+
    `<td class="num">${fmt(r.calls)}</td><td class="num">${fmt(r.req_tokens)}</td>`+
    `<td class="num">${fmt(r.resp_tokens)}</td><td class="num">${fmt(r.total_tokens)}</td></tr>`).join('');
  const p=await (await fetch('/api/projects')).json();
  $('#proj').innerHTML=p.map(r=>{const short=r.project==='(unknown)'?r.project:String(r.project).split(' | ').map(x=>x.split('/').pop()).join(' | ');
    return `<tr><td title="${esc(r.project)}">${esc(short)}</td><td>${esc(r.process)}</td>`+
    `<td class="num">${fmt(r.calls)}</td><td class="num">${fmt(r.total_tokens)}</td></tr>`;}).join('');
}
async function init(){
  const rows=await (await fetch('/api/recent?limit=200')).json();
  rows.slice().reverse().forEach(r=>{addRow(r,false);bumpCards(r);});
  await loadAgg();
  const es=new EventSource('/events');
  es.onopen=()=>{$('#dot').className='dot on';$('#status').textContent='실시간 연결됨';};
  es.onerror=()=>{$('#dot').className='dot';$('#status').textContent='재연결 중…';};
  es.onmessage=e=>{const r=JSON.parse(e.data);addRow(r,true);bumpCards(r);loadAgg();};
}
init();
</script>
</body>
</html>"""


class DashboardServer:
    def __init__(self, db_path: str | Path, host: str = "127.0.0.1", port: int = 10802):
        self.db_path = str(db_path)
        self.host = host
        self.port = port
        self._clients: set[queue.Queue] = set()
        self._lock = threading.Lock()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # 조용히
                pass

            def _send(self, code, body: bytes, ctype="application/json"):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path == "/":
                    self._send(200, _PAGE.encode("utf-8"), "text/html; charset=utf-8")
                elif path == "/api/recent":
                    limit = 200
                    if "limit=" in self.path:
                        try:
                            limit = int(self.path.split("limit=", 1)[1].split("&")[0])
                        except Exception:
                            pass
                    with Storage(server.db_path) as st:
                        data = st.recent(limit=limit)
                    self._send(200, json.dumps(data, ensure_ascii=False).encode("utf-8"))
                elif path == "/api/tokens":
                    with Storage(server.db_path) as st:
                        data = st.token_summary()
                    self._send(200, json.dumps(data, ensure_ascii=False).encode("utf-8"))
                elif path == "/api/projects":
                    with Storage(server.db_path) as st:
                        data = st.project_summary()
                    self._send(200, json.dumps(data, ensure_ascii=False).encode("utf-8"))
                elif path == "/events":
                    self._stream()
                else:
                    self._send(404, b'{"error":"not found"}')

            def _stream(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                q: queue.Queue = queue.Queue()
                server._register(q)
                try:
                    self.wfile.write(b": connected\n\n")
                    self.wfile.flush()
                    while True:
                        try:
                            evt = q.get(timeout=15)
                        except queue.Empty:
                            self.wfile.write(b": ping\n\n")
                            self.wfile.flush()
                            continue
                        payload = json.dumps(evt, ensure_ascii=False)
                        self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    server._unregister(q)

        self._handler_cls = Handler

    def _register(self, q: queue.Queue) -> None:
        with self._lock:
            self._clients.add(q)

    def _unregister(self, q: queue.Queue) -> None:
        with self._lock:
            self._clients.discard(q)

    def broadcast(self, event: dict) -> None:
        with self._lock:
            clients = list(self._clients)
        for q in clients:
            try:
                q.put_nowait(event)
            except Exception:
                pass

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def start(self) -> str:
        self._httpd = ThreadingHTTPServer((self.host, self.port), self._handler_cls)
        self._httpd.daemon_threads = True
        # port=0 인 경우 실제 할당된 포트 반영
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        url = f"http://{self.host}:{self.port}/"
        logger.info("대시보드 시작: %s", url)
        return url

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
