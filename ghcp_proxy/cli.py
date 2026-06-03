"""캡처 데이터 조회 CLI.

예시:
    python -m ghcp_proxy.cli recent --limit 10
    python -m ghcp_proxy.cli tokens
    python -m ghcp_proxy.cli show 3
    python -m ghcp_proxy.cli purge
"""
from __future__ import annotations

import argparse
import json
import sys

from .config import load_config
from .storage import Storage


def _storage() -> Storage:
    cfg = load_config()
    return Storage(cfg.resolved_db_path())


def cmd_recent(args: argparse.Namespace) -> int:
    with _storage() as st:
        rows = st.recent(limit=args.limit)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("(캡처 없음)")
        return 0
    print(f"{'ID':>4}  {'TS':<20} {'DEV':<12} {'PROCESS':<14} {'PROJECT':<22} {'MODEL':<18} {'TOT':>6}")
    for r in rows:
        proj = r.get("project_dir") or "-"
        proj = proj.split("/")[-1] if proj != "-" else "-"
        print(
            f"{r['id']:>4}  {r['ts'][:20]:<20} {str(r['developer'])[:12]:<12} "
            f"{str(r.get('client_process'))[:14]:<14} {proj[:22]:<22} "
            f"{str(r['model'])[:18]:<18} {str(r['total_tokens']):>6}"
        )
    return 0


def cmd_projects(args: argparse.Namespace) -> int:
    with _storage() as st:
        rows = st.project_summary(inference_only=not args.all)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("(캡처 없음)")
        return 0
    print(f"{'PROJECT':<48} {'PROCESS':<16} {'CALLS':>6} {'TOTAL':>8}")
    for r in rows:
        print(
            f"{str(r['project'])[:48]:<48} {str(r['process'])[:16]:<16} "
            f"{r['calls']:>6} {r['total_tokens']:>8}"
        )
    return 0


def cmd_tokens(args: argparse.Namespace) -> int:
    with _storage() as st:
        rows = st.token_summary(inference_only=not args.all)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("(캡처 없음)")
        return 0
    print(f"{'DEV':<18} {'MODEL':<22} {'CALLS':>6} {'REQ':>8} {'RESP':>8} {'TOTAL':>8}")
    for r in rows:
        print(
            f"{str(r['developer'])[:18]:<18} {str(r['model'])[:22]:<22} "
            f"{r['calls']:>6} {r['req_tokens']:>8} {r['resp_tokens']:>8} {r['total_tokens']:>8}"
        )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    with _storage() as st:
        row = st.get(args.id)
    if not row:
        print(f"id={args.id} 캡처를 찾을 수 없습니다.", file=sys.stderr)
        return 1
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return 0


def cmd_purge(args: argparse.Namespace) -> int:
    cfg = load_config()
    days = args.days if args.days is not None else cfg.storage.retention_days
    with Storage(cfg.resolved_db_path()) as st:
        before = st.count()
        deleted = st.purge(days)
        after = st.count()
    print(f"purge: retention={days}일 | 삭제 {deleted}건 | {before} → {after}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ghcp", description="Copilot 캡처 조회 CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("recent", help="최근 캡처 목록")
    pr.add_argument("--limit", type=int, default=20)
    pr.add_argument("--json", action="store_true")
    pr.set_defaults(func=cmd_recent)

    pt = sub.add_parser("tokens", help="개발자·모델별 토큰 집계")
    pt.add_argument("--json", action="store_true")
    pt.add_argument("--all", action="store_true",
                    help="비추론(model=unknown) 보조 트래픽도 포함")
    pt.set_defaults(func=cmd_tokens)

    pj = sub.add_parser("projects", help="프로젝트·프로세스별 집계")
    pj.add_argument("--json", action="store_true")
    pj.add_argument("--all", action="store_true",
                    help="비추론(model=unknown) 보조 트래픽도 포함")
    pj.set_defaults(func=cmd_projects)

    ps = sub.add_parser("show", help="단일 캡처 상세(payload 포함)")
    ps.add_argument("id", type=int)
    ps.set_defaults(func=cmd_show)

    pp = sub.add_parser("purge", help="보존기간 지난 캡처 삭제")
    pp.add_argument("--days", type=int, default=None, help="미지정 시 config 값 사용")
    pp.set_defaults(func=cmd_purge)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
