"""Workday CxS career-site API (myworkdayjobs.com) — used by many hospital systems.

Endpoint: POST https://{host}/wday/cxs/{tenant}/{site}/jobs
Body:     {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "..."}
Response: {"total": N, "jobPostings": [{"title", "externalPath", "locationsText",
           "postedOn", "bulletFields": [...]}]}
Job URL:  https://{host}/en-US/{site}{externalPath}
"""
from __future__ import annotations

from typing import List

from ..models import Job
from .base import Source, post_json, polite_pause

PAGE = 20  # Workday CxS caps limit at 20


class WorkdaySource(Source):
    kind = "workday"

    def fetch(self) -> List[Job]:
        host = self.cfg["host"]                      # e.g. hoag.wd1.myworkdayjobs.com
        tenant = self.cfg["tenant"]                  # e.g. hoag
        site = self.cfg["site"]                      # e.g. Hoag_External_Careers
        url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
        jobs: List[Job] = []
        for q in self.queries:
            offset = 0
            while offset < 100:  # a search term should never legitimately exceed this
                body = {"appliedFacets": {}, "limit": PAGE, "offset": offset, "searchText": q}
                data = post_json(url, json_body=body)
                postings = data.get("jobPostings") or []
                for p in postings:
                    path = p.get("externalPath") or ""
                    jobs.append(Job(
                        source=self.id,
                        source_job_id=path or p.get("title", ""),
                        title=p.get("title", ""),
                        company=self.name,
                        url=f"https://{host}/en-US/{site}{path}",
                        location_raw=p.get("locationsText", ""),
                        posted_at=p.get("postedOn", ""),
                    ))
                total = int(data.get("total") or 0)
                offset += PAGE
                if offset >= total or not postings:
                    break
                polite_pause(0.5)
            polite_pause(0.5)
        return self.dedupe(jobs)
