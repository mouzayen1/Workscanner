"""Simple keyless ATS APIs: Greenhouse, Lever, SmartRecruiters.

Less common among big health systems, but common at imaging startups,
theranostics clinics, and staffing companies — cheap to support.
"""
from __future__ import annotations

from typing import List

from ..models import Job
from ..geo import normalize_state
from .base import Source, get_json


class GreenhouseSource(Source):
    kind = "greenhouse"
    # GET https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true

    def fetch(self) -> List[Job]:
        board = self.cfg["board"]
        data = get_json(
            f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs",
            params={"content": "true"},
        )
        jobs = []
        for j in data.get("jobs", []):
            jobs.append(Job(
                source=self.id,
                source_job_id=str(j.get("id", "")),
                title=j.get("title", ""),
                company=self.name,
                url=j.get("absolute_url", ""),
                location_raw=(j.get("location") or {}).get("name", ""),
                description=(j.get("content") or "")[:2000],
                posted_at=j.get("updated_at", ""),
            ))
        return self.dedupe(jobs)


class LeverSource(Source):
    kind = "lever"
    # GET https://api.lever.co/v0/postings/{company}?mode=json

    def fetch(self) -> List[Job]:
        company = self.cfg["company"]
        data = get_json(f"https://api.lever.co/v0/postings/{company}", params={"mode": "json"})
        jobs = []
        for j in data if isinstance(data, list) else []:
            cats = j.get("categories") or {}
            created = j.get("createdAt")  # epoch milliseconds
            posted = ""
            if isinstance(created, (int, float)) and created > 0:
                from datetime import datetime, timezone
                posted = datetime.fromtimestamp(created / 1000, tz=timezone.utc) \
                    .strftime("%Y-%m-%d")
            jobs.append(Job(
                source=self.id,
                source_job_id=str(j.get("id", "")),
                title=j.get("text", ""),
                company=self.name,
                url=j.get("hostedUrl", ""),
                location_raw=cats.get("location", "") or ", ".join(
                    (cats.get("allLocations") or [])[:3]
                ),
                description=(j.get("descriptionPlain") or "")[:2000],
                posted_at=posted,
            ))
        return self.dedupe(jobs)


class SmartRecruitersSource(Source):
    kind = "smartrecruiters"
    # GET https://api.smartrecruiters.com/v1/companies/{company}/postings?q=...

    def fetch(self) -> List[Job]:
        company = self.cfg["company"]
        jobs = []
        for q in self.queries:
            data = get_json(
                f"https://api.smartrecruiters.com/v1/companies/{company}/postings",
                params={"q": q, "limit": 100},
            )
            for j in data.get("content", []):
                loc = j.get("location") or {}
                city = loc.get("city", "")
                region = loc.get("region", "")
                jobs.append(Job(
                    source=self.id,
                    source_job_id=str(j.get("id", "")),
                    title=j.get("name", ""),
                    company=self.name,
                    url=f"https://jobs.smartrecruiters.com/{company}/{j.get('id', '')}",
                    location_raw=", ".join(x for x in [city, region] if x),
                    city=city or None,
                    state=normalize_state(region),
                    posted_at=j.get("releasedDate", ""),
                ))
        return self.dedupe(jobs)
