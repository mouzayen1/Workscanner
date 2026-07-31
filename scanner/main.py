"""CLI entry point.

  python -m scanner.main scan            # full scan: fetch, score, merge, report
  python -m scanner.main scan --dry-run  # fetch + score, but write nothing
  python -m scanner.main probe           # fetch each source, print health + counts only
  python -m scanner.main render          # re-render dashboard/digest from saved state
"""
from __future__ import annotations

import argparse
import sys
import traceback
from typing import Dict, List

import yaml

from .models import Job
from .geo import Region
from .scoring import classify, is_role_match, in_scope
from .state import load_state, merge, save_state
from .report import write_digest, write_dashboard, write_ci_summary
from .sources import build_source

SEARCH_CFG = "config/search.yml"
SOURCES_CFG = "config/sources.yml"


def load_cfg():
    with open(SEARCH_CFG, "r", encoding="utf-8") as f:
        search = yaml.safe_load(f)
    with open(SOURCES_CFG, "r", encoding="utf-8") as f:
        sources = yaml.safe_load(f)["sources"]
    return search, sources


def scan_sources(sources_cfg: List[dict], only: set | None = None):
    """Fetch every enabled source. Returns (jobs, health)."""
    all_jobs: List[Job] = []
    health: Dict[str, str] = {}
    for cfg in sources_cfg:
        sid = cfg["id"]
        if only and sid not in only:
            continue
        if cfg.get("disabled"):
            health[sid] = "skipped (disabled in config)"
            continue
        try:
            src = build_source(cfg)
            if hasattr(src, "enabled") and not src.enabled():
                health[sid] = "skipped (no API key configured)"
                continue
            jobs = src.fetch()
            health[sid] = f"ok ({len(jobs)} raw)"
            all_jobs.extend(jobs)
        except Exception as e:  # a broken source must never sink the scan
            health[sid] = f"error: {type(e).__name__}: {e}"[:200]
            print(f"[{sid}] FAILED: {e}", file=sys.stderr)
            traceback.print_exc()
    return all_jobs, health


def run_scan(dry_run: bool = False, only: set | None = None, verbose: bool = False) -> int:
    search_cfg, sources_cfg = load_cfg()
    region = Region(search_cfg)
    src_by_id = {c["id"]: c for c in sources_cfg}

    raw, health = scan_sources(sources_cfg, only)
    print(f"fetched {len(raw)} raw postings from "
          f"{sum(1 for v in health.values() if v.startswith('ok'))} sources")

    kept: List[Job] = []
    for job in raw:
        if not is_role_match(job.title, job.description):
            continue
        job = classify(job, region, src_by_id.get(job.source, {}))
        if not in_scope(job, region):
            continue
        kept.append(job)

    # cross-source dedup: aggregators often re-list an employer's own posting.
    # Prefer the direct-employer copy (richer, canonical apply link).
    kept = _cross_source_dedupe(kept, src_by_id)

    print(f"kept {len(kept)} in-scope role matches")
    if verbose:
        for j in sorted(kept, key=lambda x: -x.score):
            print(f"  [{j.score:3d}] {j.category:15s} {j.title} — {j.company} — {j.location_raw}")

    if dry_run:
        return 0

    state = load_state()
    healthy = {sid for sid, v in health.items() if v.startswith("ok")}
    state, new_jobs = merge(state, kept, healthy)
    save_state(state)
    n_new = write_digest(new_jobs)
    write_dashboard(state, health)
    write_ci_summary(state, new_jobs, health)
    print(f"state saved: {sum(1 for d in state['jobs'].values() if d.get('active'))} active, "
          f"{n_new} new this run")
    return 0


def _norm_title(t: str) -> str:
    return "".join(ch for ch in t.lower() if ch.isalnum())


def _cross_source_dedupe(jobs: List[Job], src_by_id: dict) -> List[Job]:
    """Drop aggregator copies when a direct source has the same title+city."""
    direct_keys = set()
    for j in jobs:
        if not src_by_id.get(j.source, {}).get("aggregator"):
            direct_keys.add((_norm_title(j.title), (j.city or "").lower(), j.company.lower()))
    out = []
    for j in jobs:
        if src_by_id.get(j.source, {}).get("aggregator"):
            k = (_norm_title(j.title), (j.city or "").lower(), j.company.lower())
            if k in direct_keys:
                continue
        out.append(j)
    return out


def run_probe() -> int:
    _, sources_cfg = load_cfg()
    _, health = scan_sources(sources_cfg)
    print("\n=== SOURCE HEALTH ===")
    ok = True
    for sid, status in sorted(health.items()):
        print(f"  {sid:20s} {status}")
        if status.startswith("error"):
            ok = False
    return 0 if ok else 1


def run_render() -> int:
    state = load_state()
    write_dashboard(state, {})
    print("dashboard re-rendered from saved state")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="workscanner")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_scan = sub.add_parser("scan")
    p_scan.add_argument("--dry-run", action="store_true")
    p_scan.add_argument("--verbose", "-v", action="store_true")
    p_scan.add_argument("--sources", help="comma-separated source ids to scan")
    sub.add_parser("probe")
    sub.add_parser("render")
    args = ap.parse_args()
    if args.cmd == "scan":
        only = set(args.sources.split(",")) if getattr(args, "sources", None) else None
        return run_scan(dry_run=args.dry_run, only=only, verbose=args.verbose)
    if args.cmd == "probe":
        return run_probe()
    return run_render()


if __name__ == "__main__":
    sys.exit(main())
