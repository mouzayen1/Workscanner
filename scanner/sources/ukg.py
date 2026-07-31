"""UKG Pro Recruiting (recruiting.ultipro.com) — used by some medical groups.

Endpoint: POST https://recruiting.ultipro.com/{TENANT}/JobBoard/{board}/JobBoardView/LoadSearchResults
Body (minimal working shape):
  {"opportunitySearch": {"Top": 50, "Skip": 0,
     "QueryString": "...",
     "OrderBy": [{"Value": "postedDateDesc", "PropertyName": "PostedDate", "Ascending": false}],
     "Filters": []},
   "matchCriteria": {"PreferredJobs": [], "Educations": [], "LicenseAndCertifications": [],
     "Skills": [], "hasNoLicenses": false, "SkippedSkills": []}}
Response: {"opportunities": [{"Id", "Title", "Locations": [{"LocalizedName" or "Address": ...}],
           "PostedDate", ...}], "totalCount": N}
Job URL:  https://recruiting.ultipro.com/{TENANT}/JobBoard/{board}/OpportunityDetail?opportunityId={Id}
"""
from __future__ import annotations

from typing import List

from ..models import Job
from .base import Source, post_json, polite_pause


class UKGSource(Source):
    kind = "ukg"

    def fetch(self) -> List[Job]:
        tenant = self.cfg["tenant"]
        board = self.cfg["board"]
        base = f"https://recruiting.ultipro.com/{tenant}/JobBoard/{board}"
        jobs: List[Job] = []
        for q in self.queries:
            body = {
                "opportunitySearch": {
                    "Top": 50, "Skip": 0, "QueryString": q,
                    "OrderBy": [{"Value": "postedDateDesc",
                                 "PropertyName": "PostedDate", "Ascending": False}],
                    "Filters": [],
                },
                "matchCriteria": {
                    "PreferredJobs": [], "Educations": [], "LicenseAndCertifications": [],
                    "Skills": [], "hasNoLicenses": False, "SkippedSkills": [],
                },
            }
            data = post_json(f"{base}/JobBoardView/LoadSearchResults", json_body=body)
            for o in data.get("opportunities", []):
                locs = o.get("Locations") or []
                loc_texts = []
                for l in locs:
                    if isinstance(l, dict):
                        addr = l.get("Address") or {}
                        city = (addr.get("City") or "").strip()
                        st = ((addr.get("State") or {}).get("Code")
                              if isinstance(addr.get("State"), dict)
                              else addr.get("State")) or ""
                        txt = l.get("LocalizedName") or ", ".join(x for x in [city, st] if x)
                        if txt:
                            loc_texts.append(txt)
                jobs.append(Job(
                    source=self.id,
                    source_job_id=str(o.get("Id", "")),
                    title=o.get("Title", ""),
                    company=self.name,
                    url=f"{base}/OpportunityDetail?opportunityId={o.get('Id', '')}",
                    location_raw="; ".join(loc_texts),
                    posted_at=str(o.get("PostedDate", "")),
                ))
            polite_pause(0.5)
        return self.dedupe(jobs)
