"""Specialty job boards and classic-iCIMS portals (HTML parsing).

- YM Careers boards: SNMMI Career Center (careercenter.snmmi.org) and ASRT
  JobBank (careers.asrt.org). Server-rendered; job links match /job/<slug>/<id>/.
- Classic iCIMS portals: careers-{company}.icims.com — HTML only; job links
  match /jobs/<numeric-id>/<slug>/job.
"""
from __future__ import annotations

import re
from typing import List

from bs4 import BeautifulSoup

from ..models import Job
from .base import Source, session, polite_pause

_WS = re.compile(r"\s+")
_LOC = re.compile(r"([A-Za-z .'-]+,\s*(?:California|CA|[A-Z][a-z]+ ?[A-Za-z]*|[A-Z]{2}))\b")


def _clean(s) -> str:
    return _WS.sub(" ", s or "").strip()


class YMCareersSource(Source):
    kind = "ymcareers"

    def fetch(self) -> List[Job]:
        base = self.cfg["base"].rstrip("/")           # e.g. https://careercenter.snmmi.org
        paths = self.cfg.get("paths") or [
            "/jobs/?keywords=nuclear+medicine&location=California",
            "/jobs/?keywords=PET+CT&location=California",
        ]
        jobs: List[Job] = []
        for path in paths:
            r = session().get(base + path, timeout=30)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")
            for a in soup.find_all("a", href=re.compile(r"/job/[^/]+/\d+/?$")):
                href = a["href"]
                url = href if href.startswith("http") else base + href
                m_id = re.search(r"/(\d+)/?$", href)
                title = _clean(a.get_text(" "))
                if not title or len(title) < 4:
                    continue
                card = a.find_parent("li") or a.find_parent("div") or a
                card_text = _clean(card.get_text(" "))[:400]
                m_loc = _LOC.search(card_text.replace(title, "", 1))
                jobs.append(Job(
                    source=self.id,
                    source_job_id=m_id.group(1) if m_id else href,
                    title=title[:160],
                    company=self.cfg.get("company_from_card", True) and
                    _guess_company(card_text, title) or self.name,
                    url=url,
                    location_raw=m_loc.group(1) if m_loc else "",
                ))
            polite_pause(0.8)
        return self.dedupe(jobs)


def _guess_company(card_text: str, title: str) -> str:
    """Best-effort employer name from a listing card; falls back to ''."""
    rest = card_text.replace(title, "", 1).strip()
    words = rest.split(" ")
    guess = " ".join(words[:6])
    return guess[:80] if 3 < len(guess) < 80 else ""


class ICIMSClassicSource(Source):
    kind = "icims-classic"

    def fetch(self) -> List[Job]:
        base = self.cfg["base"].rstrip("/")           # e.g. https://careers-primehealthcare.icims.com
        jobs: List[Job] = []
        for q in self.queries:
            for page in range(0, 3):                  # pr= is 0-based, ~20-30 rows/page
                r = session().get(
                    f"{base}/jobs/search",
                    params={"ss": 1, "searchKeyword": q, "pr": page, "in_iframe": 1},
                    timeout=30,
                )
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "lxml")
                anchors = soup.find_all("a", href=re.compile(r"/jobs/\d+/[^/]+/job"))
                if not anchors:
                    break
                for a in anchors:
                    href = a["href"].split("?")[0]
                    url = href if href.startswith("http") else base + href
                    m_id = re.search(r"/jobs/(\d+)/", href)
                    title = _clean(a.get_text(" "))
                    if not title:
                        continue
                    card = a.find_parent("div", class_=re.compile("row|iCIMS")) \
                        or a.find_parent("li") or a.parent
                    m_loc = _LOC.search(_clean(card.get_text(" ")))
                    jobs.append(Job(
                        source=self.id,
                        source_job_id=m_id.group(1) if m_id else href,
                        title=title[:160],
                        company=self.name,
                        url=url,
                        location_raw=m_loc.group(1) if m_loc else "",
                    ))
                polite_pause(0.8)
        return self.dedupe(jobs)
