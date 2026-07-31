"""Aggregator APIs. All are optional: each activates only when its key is present
in the environment, so the scanner degrades gracefully with zero secrets.

These cover the long tail our direct employer scans miss — small cardiology
offices, one-off clinic postings, hospital systems we didn't enumerate.
"""
from __future__ import annotations

import os
from typing import List

from ..models import Job
from .base import Source, get_json, post_json, polite_pause


class AdzunaSource(Source):
    kind = "adzuna"
    # GET https://api.adzuna.com/v1/api/jobs/us/search/{page}
    #   ?app_id=..&app_key=..&what=..&where=..&distance=..&max_days_old=..
    # Free tier: 250 calls/day — far more than we need.

    def enabled(self) -> bool:
        return bool(os.environ.get("ADZUNA_APP_ID") and os.environ.get("ADZUNA_APP_KEY"))

    def fetch(self) -> List[Job]:
        app_id = os.environ["ADZUNA_APP_ID"]
        app_key = os.environ["ADZUNA_APP_KEY"]
        wheres = self.cfg.get("wheres", ["Costa Mesa, CA", "Chino Hills, CA"])
        jobs: List[Job] = []
        for q in self.queries:
            for where in wheres:
                data = get_json(
                    "https://api.adzuna.com/v1/api/jobs/us/search/1",
                    params={
                        "app_id": app_id, "app_key": app_key,
                        "what": q, "where": where,
                        "distance": self.cfg.get("distance_km", 60),
                        "max_days_old": self.cfg.get("max_days_old", 45),
                        "results_per_page": 50, "sort_by": "date",
                        "content-type": "application/json",
                    },
                )
                for j in data.get("results", []):
                    loc = j.get("location") or {}
                    jobs.append(Job(
                        source=self.id,
                        source_job_id=str(j.get("id", "")),
                        title=j.get("title", "").replace("<strong>", "").replace("</strong>", ""),
                        company=(j.get("company") or {}).get("display_name", ""),
                        url=j.get("redirect_url", ""),
                        location_raw=loc.get("display_name", ""),
                        latitude=j.get("latitude"),
                        longitude=j.get("longitude"),
                        description=(j.get("description") or "")[:2000],
                        salary_raw=_salary(j.get("salary_min"), j.get("salary_max")),
                        posted_at=j.get("created", ""),
                    ))
                polite_pause(0.6)
        return self.dedupe(jobs)


class JSearchSource(Source):
    kind = "jsearch"
    # RapidAPI "JSearch" — indexes Google for Jobs (which sees Indeed/LinkedIn/etc.
    # postings employers publish as structured data). Free tier ~200 req/month,
    # so we use a handful of focused queries.

    def enabled(self) -> bool:
        return bool(os.environ.get("RAPIDAPI_KEY"))

    def fetch(self) -> List[Job]:
        headers = {
            "X-RapidAPI-Key": os.environ["RAPIDAPI_KEY"],
            "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
        }
        searches = self.cfg.get("searches", [
            "nuclear medicine technologist in Orange County, CA",
            "PET CT technologist in Orange County, CA",
            "nuclear medicine technologist in Corona, CA",
        ])
        jobs: List[Job] = []
        for q in searches:
            data = get_json(
                "https://jsearch.p.rapidapi.com/search",
                params={"query": q, "num_pages": 1, "date_posted": "month"},
                headers=headers,
            )
            for j in data.get("data", []):
                jobs.append(Job(
                    source=self.id,
                    source_job_id=str(j.get("job_id", "")),
                    title=j.get("job_title", ""),
                    company=j.get("employer_name", ""),
                    url=j.get("job_apply_link", ""),
                    location_raw=", ".join(
                        x for x in [j.get("job_city"), j.get("job_state")] if x
                    ),
                    city=j.get("job_city") or None,
                    state=j.get("job_state") or None,
                    latitude=j.get("job_latitude"),
                    longitude=j.get("job_longitude"),
                    description=(j.get("job_description") or "")[:2000],
                    posted_at=j.get("job_posted_at_datetime_utc") or "",
                ))
            polite_pause(1.0)
        return self.dedupe(jobs)


class JoobleSource(Source):
    kind = "jooble"
    # POST https://jooble.org/api/{key}  {"keywords": ..., "location": ...}

    def enabled(self) -> bool:
        return bool(os.environ.get("JOOBLE_KEY"))

    def fetch(self) -> List[Job]:
        key = os.environ["JOOBLE_KEY"]
        locations = self.cfg.get("locations", ["Orange County, CA", "Corona, CA"])
        jobs: List[Job] = []
        for q in self.queries:
            for loc in locations:
                data = post_json(
                    f"https://jooble.org/api/{key}",
                    json_body={"keywords": q, "location": loc, "radius": "40"},
                )
                for j in data.get("jobs", []):
                    jobs.append(Job(
                        source=self.id,
                        source_job_id=str(j.get("id", "")),
                        title=j.get("title", ""),
                        company=j.get("company", ""),
                        url=j.get("link", ""),
                        location_raw=j.get("location", ""),
                        description=(j.get("snippet") or "")[:2000],
                        salary_raw=j.get("salary", ""),
                        posted_at=j.get("updated", ""),
                    ))
                polite_pause(0.6)
        return self.dedupe(jobs)


class USAJobsSource(Source):
    kind = "usajobs"
    # VA outpatient clinics hire NM techs; federal jobs never hit commercial boards.
    # GET https://data.usajobs.gov/api/search  (free key: developer.usajobs.gov)

    def enabled(self) -> bool:
        return bool(os.environ.get("USAJOBS_KEY") and os.environ.get("USAJOBS_EMAIL"))

    def fetch(self) -> List[Job]:
        headers = {
            "Authorization-Key": os.environ["USAJOBS_KEY"],
            "User-Agent": os.environ["USAJOBS_EMAIL"],
        }
        data = get_json(
            "https://data.usajobs.gov/api/search",
            params={
                "Keyword": "nuclear medicine technologist",
                "LocationName": "California",
                "ResultsPerPage": 100,
            },
            headers=headers,
        )
        jobs = []
        items = ((data.get("SearchResult") or {}).get("SearchResultItems")) or []
        for it in items:
            d = it.get("MatchedObjectDescriptor") or {}
            locs = d.get("PositionLocation") or []
            loc0 = locs[0] if locs else {}
            pay = (d.get("PositionRemuneration") or [{}])[0]
            jobs.append(Job(
                source=self.id,
                source_job_id=str(d.get("PositionID", "")),
                title=d.get("PositionTitle", ""),
                company=d.get("OrganizationName", ""),
                url=d.get("PositionURI", ""),
                location_raw=loc0.get("LocationName", ""),
                latitude=loc0.get("Latitude"),
                longitude=loc0.get("Longitude"),
                salary_raw=f"{pay.get('MinimumRange', '')}-{pay.get('MaximumRange', '')} {pay.get('RateIntervalCode', '')}".strip("- "),
                posted_at=d.get("PublicationStartDate", ""),
            ))
        return self.dedupe(jobs)


def _salary(lo, hi) -> str:
    if not lo and not hi:
        return ""
    fmt = lambda v: f"${int(v):,}" if v else "?"
    return f"{fmt(lo)}–{fmt(hi)}/yr"
