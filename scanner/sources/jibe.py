"""iCIMS "Attract" (formerly Jibe) career sites — e.g. careers.radnet.com.

These sites (recognizable by /careers-home/jobs/12345?lang=en-us URLs) serve
their own listings from a public JSON API:

  GET {base}/api/jobs?keywords=nuclear&page=1
  -> {"jobs": [{"data": {...}}, ...], "totalCount": N}

Fields inside each item's "data" vary a little by site; we read defensively.
Page size is fixed by the site (commonly 10) and cannot be raised.
"""
from __future__ import annotations

from typing import List, Optional

from ..models import Job
from ..geo import normalize_state
from .base import Source, get_json, polite_pause

_MAX_PAGES = 8


def fetch_jibe(base: str, queries: List[str], source_id: str, name: str) -> List[Job]:
    base = base.rstrip("/")
    jobs: List[Job] = []
    for q in queries:
        page = 1
        while page <= _MAX_PAGES:
            data = get_json(f"{base}/api/jobs", params={"keywords": q, "page": page})
            items = data.get("jobs") or []
            if not items:
                break
            for item in items:
                d = item.get("data") or item
                slug = d.get("slug") or ""
                req_id = str(d.get("req_id") or d.get("requisition_id")
                             or slug or d.get("title", ""))
                url = d.get("apply_url") or d.get("canonical_url") or ""
                if not url and slug:
                    url = f"{base}/careers-home/jobs/{slug}"
                loc = d.get("full_location") or ", ".join(
                    x for x in [d.get("city"), d.get("state")] if x
                )
                jobs.append(Job(
                    source=source_id,
                    source_job_id=req_id,
                    title=d.get("title", ""),
                    company=name,
                    url=url,
                    location_raw=loc or "",
                    city=d.get("city") or None,
                    state=normalize_state(d.get("state")),
                    description=(d.get("description") or "")[:2000],
                    posted_at=d.get("posted_date") or d.get("create_date") or "",
                ))
            total = int(data.get("totalCount") or 0)
            if total and page * max(len(items), 1) >= total:
                break
            page += 1
            polite_pause(0.5)
        polite_pause(0.5)
    return jobs


class JibeSource(Source):
    kind = "jibe"

    def fetch(self) -> List[Job]:
        return self.dedupe(fetch_jibe(self.cfg["base"], self.queries, self.id, self.name))
