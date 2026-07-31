"""Core data model for job listings."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from typing import Optional

# Category identifiers, in display-priority order.
CAT_OUTPATIENT_PET = "outpatient-pet"      # outpatient + PET/CT — the target
CAT_OUTPATIENT_NM = "outpatient-nm"        # outpatient nuclear medicine (non-PET or general)
CAT_HOSPITAL_OTHER = "hospital-other"      # hospital-based / inpatient-likely / unclear setting
CAT_TRAVEL = "travel"                      # travel / contract assignments (separate track)

CATEGORIES = [CAT_OUTPATIENT_PET, CAT_OUTPATIENT_NM, CAT_HOSPITAL_OTHER, CAT_TRAVEL]

CATEGORY_LABELS = {
    CAT_OUTPATIENT_PET: "Outpatient PET/CT",
    CAT_OUTPATIENT_NM: "Outpatient Nuclear Med",
    CAT_HOSPITAL_OTHER: "Hospital / Other",
    CAT_TRAVEL: "Travel / Contract",
}


@dataclass
class Job:
    """A normalized job listing from any source."""

    source: str                      # source id from sources.yml
    source_job_id: str               # the source's own id for the posting (or the URL)
    title: str
    company: str
    url: str
    location_raw: str = ""           # location text as the source gave it
    city: Optional[str] = None       # parsed city, if determinable
    state: Optional[str] = None      # parsed 2-letter state, if determinable
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    description: str = ""            # snippet/description text (truncated on save)
    salary_raw: str = ""
    posted_at: str = ""              # ISO date or the source's raw text
    # -- computed by scoring --
    category: str = CAT_HOSPITAL_OTHER
    score: int = 0
    tags: list = field(default_factory=list)
    location_tier: int = 0           # 1 = core target cities, 2 = nearby, 0 = other/unknown
    # -- lifecycle, managed by state --
    first_seen: str = ""
    last_seen: str = ""
    active: bool = True

    @property
    def key(self) -> str:
        """Stable identity for dedup across scans."""
        raw = f"{self.source}|{self.source_job_id or self.url}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["key"] = self.key
        # Keep the state file small: descriptions are only needed for scoring.
        if len(d.get("description") or "") > 700:
            d["description"] = d["description"][:700] + "…"
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        d = dict(d)
        d.pop("key", None)
        known = {f for f in cls.__dataclass_fields__}  # tolerate schema evolution
        return cls(**{k: v for k, v in d.items() if k in known})
