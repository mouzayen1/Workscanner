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


_ICIMS_LOC = re.compile(r"\bUS-([A-Z]{2})-([A-Za-z .'-]+)")


class ICIMSClassicSource(Source):
    kind = "icims-classic"
    # List rows label fields ("Title Nuclear Medicine Tech", "US-CA-Chino"), and
    # locations are often only on the detail page — so for rows that look like
    # our role, we fetch the detail page and read its JSON-LD JobPosting block.

    _DETAIL_CAP = 25

    def fetch(self) -> List[Job]:
        from ..scoring import is_role_match
        from .radancy import _jsonld_jobposting

        base = self.cfg["base"].rstrip("/")           # e.g. https://careers-primehealthcare.icims.com
        jobs: List[Job] = []
        seen_ids = set()
        search_broken = False
        for q in self.queries:
            if search_broken:
                break
            for page in range(0, 3):                  # pr= is 0-based, ~20-30 rows/page
                try:
                    r = session().get(
                        f"{base}/jobs/search",
                        params={"ss": 1, "searchKeyword": q, "pr": page,
                                "in_iframe": 1},
                        headers={"Referer": f"{base}/jobs/search?ss=1"},
                        timeout=30,
                    )
                    r.raise_for_status()
                except Exception as e:
                    # Portal WAFs intermittently 405 the search page; the
                    # sitemap lists every job URL and rarely gets blocked.
                    print(f"[{self.id}] search page failed ({type(e).__name__}); "
                          f"falling back to sitemap")
                    search_broken = True
                    break
                soup = BeautifulSoup(r.text, "lxml")
                anchors = soup.find_all("a", href=re.compile(r"/jobs/\d+/[^/]+/job"))
                if not anchors:
                    break
                for a in anchors:
                    href = a["href"].split("?")[0]
                    url = href if href.startswith("http") else base + href
                    m_id = re.search(r"/jobs/(\d+)/", href)
                    jid = m_id.group(1) if m_id else href
                    if jid in seen_ids:
                        continue
                    seen_ids.add(jid)
                    title = re.sub(r"^(Job\s+)?Title\s+", "", _clean(a.get_text(" ")),
                                   flags=re.IGNORECASE)
                    if not title:
                        continue
                    card = a.find_parent("div", class_=re.compile("row|iCIMS")) \
                        or a.find_parent("li") or a.parent
                    card_text = _clean(card.get_text(" "))
                    m_loc = _ICIMS_LOC.search(card_text)
                    loc_raw, city, state = "", None, None
                    if m_loc:
                        state, city = m_loc.group(1), _clean(m_loc.group(2))
                        loc_raw = f"{city}, {state}"
                    jobs.append(Job(
                        source=self.id,
                        source_job_id=jid,
                        title=title[:160],
                        company=self.name,
                        url=url,
                        location_raw=loc_raw,
                        city=city, state=state,
                    ))
                polite_pause(0.8)

        if search_broken and not jobs:
            from .radancy import fetch_sitemap_jsonld
            jobs = fetch_sitemap_jsonld(
                base, self.queries, self.id, self.name,
                url_include=r"/jobs/\d+/",
            )
            for j in jobs:  # sitemap paths carry no city; JSON-LD filled what it could
                j.city = j.city if j.city and j.state else None

        # enrich locations from detail-page JSON-LD for our role matches
        fetched = 0
        for job in jobs:
            if job.location_raw or fetched >= self._DETAIL_CAP:
                continue
            if not is_role_match(job.title):
                continue
            try:
                rd = session().get(job.url, timeout=30)
                rd.raise_for_status()
                fetched += 1
                jp = _jsonld_jobposting(rd.text)
            except Exception:
                continue
            if not jp:
                m = _ICIMS_LOC.search(rd.text)
                if m:
                    job.state, job.city = m.group(1), _clean(m.group(2))
                    job.location_raw = f"{job.city}, {job.state}"
                continue
            loc = jp.get("jobLocation") or {}
            if isinstance(loc, list):
                loc = loc[0] if loc else {}
            addr = loc.get("address") or {} if isinstance(loc, dict) else {}
            if isinstance(addr, dict):
                job.city = addr.get("addressLocality") or job.city
                job.state = addr.get("addressRegion") or job.state
                if job.city:
                    job.location_raw = ", ".join(
                        x for x in [job.city, job.state] if x)
            job.description = re.sub(
                r"<[^>]+>", " ", str(jp.get("description") or ""))[:2000]
            job.posted_at = str(jp.get("datePosted") or "")
            polite_pause(0.5)
        return self.dedupe(jobs)
