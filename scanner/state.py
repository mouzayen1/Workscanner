"""Persistence of seen jobs across scans (data/jobs.json, committed by the Action)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Tuple

from .models import Job

STATE_PATH = os.path.join("data", "jobs.json")
# A job silently missing from this many consecutive scans of a *healthy* source
# is marked inactive (filled or pulled).
MISSES_BEFORE_INACTIVE = 2


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_state(path: str = STATE_PATH) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"updated": None, "jobs": {}, "misses": {}}


def merge(state: dict, scanned: List[Job], healthy_sources: set) -> Tuple[dict, List[Job]]:
    """Merge freshly scanned jobs into state.

    Returns (new_state, newly_seen_jobs). Jobs from sources that failed this
    run keep their previous status — a broken scraper doesn't mean the job is gone.
    """
    now = _now()
    jobs: Dict[str, dict] = dict(state.get("jobs", {}))
    misses: Dict[str, int] = dict(state.get("misses", {}))
    seen_now = set()
    new_jobs: List[Job] = []

    for job in scanned:
        k = job.key
        seen_now.add(k)
        misses.pop(k, None)
        if k in jobs:
            prev = jobs[k]
            job.first_seen = prev.get("first_seen") or now
            job.last_seen = now
            job.active = True
            jobs[k] = job.to_dict()
        else:
            job.first_seen = now
            job.last_seen = now
            job.active = True
            jobs[k] = job.to_dict()
            new_jobs.append(job)

    # age out jobs that stopped appearing (only for sources that scanned OK)
    for k, d in jobs.items():
        if k in seen_now or not d.get("active"):
            continue
        if d.get("source") in healthy_sources:
            misses[k] = misses.get(k, 0) + 1
            if misses[k] >= MISSES_BEFORE_INACTIVE:
                d["active"] = False
                misses.pop(k, None)

    return {"updated": now, "jobs": jobs, "misses": misses}, new_jobs


def save_state(state: dict, path: str = STATE_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1, ensure_ascii=False, sort_keys=True)
        f.write("\n")
