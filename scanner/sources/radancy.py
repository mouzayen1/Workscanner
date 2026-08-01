"""Radancy career sites (kaiserpermanentejobs.org, providence.jobs, careers.hoag.org,
cityofhopejobs.org, ...) plus a generic sitemap + JSON-LD fallback that works on
almost any custom careers site.

Strategy 1 — Radancy AJAX search:
  GET {base}/search-jobs/results?Keywords=...&CurrentPage=1&RecordsPerPage=50&...
  -> {"results": "<html for the result list>", "totalRecords": N}
  We parse the /job/... anchors out of the embedded HTML.

Strategy 2 — sitemap + JSON-LD:
  Fetch {base}/sitemap.xml (following one level of sitemap-index nesting),
  keep job URLs whose slug mentions our keywords, fetch each page (capped),
  and read the schema.org JobPosting JSON-LD block that career pages embed
  for Google for Jobs.
"""
from __future__ import annotations

import json
import re
from typing import List, Optional

from bs4 import BeautifulSoup

from ..models import Job
from ..geo import normalize_state
from .base import Source, session, polite_pause

_SLUG_KEYWORDS = ["nuclear", "pet-ct", "petct", "pet_ct", "molecular-imaging", "nuc-med"]
_DETAIL_CAP = 60          # max job pages fetched per source per scan
_LOC_RE = re.compile(r"([A-Za-z .'-]+,\s*(?:CA|California|[A-Z]{2}))\b")


def _clean(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


# ---------------------------------------------------------------- strategy 1

def fetch_radancy_ajax(base: str, queries: List[str], source_id: str, name: str) -> List[Job]:
    base = base.rstrip("/")
    jobs: List[Job] = []
    for q in queries:
        params = {
            "ActiveFacetID": 0, "CurrentPage": 1, "RecordsPerPage": 100,
            "Distance": "", "RadiusUnitType": 0, "Keywords": q, "Location": "",
            "ShowRadius": "False", "IsPagination": "False",
            "SearchResultsModuleName": "Search Results",
            "SearchFiltersModuleName": "Search Filters",
            "SortCriteria": 0, "SortDirection": 0, "SearchType": 5,
        }
        r = session().get(
            f"{base}/search-jobs/results", params=params, timeout=30,
            headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"},
        )
        r.raise_for_status()
        data = r.json()
        html_blob = data.get("results") or ""
        if not isinstance(html_blob, str) or "/job/" not in html_blob:
            continue
        soup = BeautifulSoup(html_blob, "lxml")
        for a in soup.select("a[href*='/job/']"):
            href = a.get("href") or ""
            if not re.search(r"/job/", href):
                continue
            url = href if href.startswith("http") else base + href
            title = _clean(a.get_text(" ")) or _clean(a.get("title"))
            # Radancy cards put title in a heading and location in a sibling span
            card = a.find_parent("li") or a.find_parent("div") or a
            loc_m = _LOC_RE.search(_clean(card.get_text(" ")))
            if not title:
                continue
            jobs.append(Job(
                source=source_id, source_job_id=href,
                title=title[:160], company=name, url=url,
                location_raw=loc_m.group(1) if loc_m else "",
            ))
        polite_pause(0.8)
    return jobs


# ---------------------------------------------------------------- strategy 2

def _sitemap_urls(base: str) -> List[str]:
    """All <loc> URLs from sitemap.xml, following one level of index nesting."""
    out: List[str] = []
    try:
        r = session().get(f"{base}/sitemap.xml", timeout=30)
        r.raise_for_status()
    except Exception:
        return out
    locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", r.text)
    child_maps = [u for u in locs if u.endswith(".xml")]
    if child_maps:
        # prefer child sitemaps that look job-related; else take the first few
        picks = [u for u in child_maps if "job" in u.lower()] or child_maps[:5]
        for cm in picks[:8]:
            try:
                rc = session().get(cm, timeout=30)
                rc.raise_for_status()
                out.extend(re.findall(r"<loc>\s*(.*?)\s*</loc>", rc.text))
            except Exception:
                continue
            polite_pause(0.4)
    else:
        out = locs
    return out


def _jsonld_jobposting(html: str) -> Optional[dict]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = data if isinstance(data, list) else data.get("@graph", [data]) \
            if isinstance(data, dict) else []
        for c in candidates:
            if isinstance(c, dict) and c.get("@type") in ("JobPosting", ["JobPosting"]):
                return c
    return None


def fetch_sitemap_jsonld(base: str, queries: List[str], source_id: str, name: str,
                         url_include: str = r"/job") -> List[Job]:
    base = base.rstrip("/")
    urls = _sitemap_urls(base)
    inc = re.compile(url_include)
    kws = _SLUG_KEYWORDS + [q.lower().replace(" ", "-") for q in queries]
    picked = [u for u in urls
              if inc.search(u) and any(k in u.lower() for k in kws)]
    jobs: List[Job] = []
    for u in picked[:_DETAIL_CAP]:
        try:
            r = session().get(u, timeout=30)
            r.raise_for_status()
        except Exception:
            continue
        jp = _jsonld_jobposting(r.text)
        if jp:
            org = jp.get("hiringOrganization") or {}
            org_name = org.get("name") if isinstance(org, dict) else str(org)
            loc = jp.get("jobLocation") or {}
            if isinstance(loc, list):
                loc = loc[0] if loc else {}
            addr = loc.get("address") or {} if isinstance(loc, dict) else {}
            city = addr.get("addressLocality") if isinstance(addr, dict) else None
            region = addr.get("addressRegion") if isinstance(addr, dict) else None
            desc = re.sub(r"<[^>]+>", " ", str(jp.get("description") or ""))[:2000]
            jobs.append(Job(
                source=source_id, source_job_id=u,
                title=_clean(str(jp.get("title", ""))), company=org_name or name,
                url=jp.get("url") or u,
                location_raw=", ".join(x for x in [city, region] if x),
                city=city or None, state=normalize_state(region),
                description=desc, posted_at=str(jp.get("datePosted") or ""),
            ))
        else:
            # No JSON-LD: fall back to <title> + location regex on the page
            soup = BeautifulSoup(r.text, "lxml")
            t = _clean(soup.title.get_text()) if soup.title else ""
            m = _LOC_RE.search(soup.get_text(" ")[:4000])
            if t:
                jobs.append(Job(
                    source=source_id, source_job_id=u, title=t[:160],
                    company=name, url=u,
                    location_raw=m.group(1) if m else "",
                ))
        polite_pause(0.5)
    return jobs


# ---------------------------------------------------------------- sources

class RadancySource(Source):
    kind = "radancy"

    def fetch(self) -> List[Job]:
        base = self.cfg["base"]
        jobs = fetch_radancy_ajax(base, self.queries, self.id, self.name)
        if not jobs:
            jobs = fetch_sitemap_jsonld(base, self.queries, self.id, self.name)
        return self.dedupe(jobs)


class SitemapSource(Source):
    kind = "sitemap"

    def fetch(self) -> List[Job]:
        return self.dedupe(fetch_sitemap_jsonld(
            self.cfg["base"], self.queries, self.id, self.name,
            url_include=self.cfg.get("url_include", r"/job"),
        ))


class AutoSource(Source):
    """Cascade: Jibe API -> Radancy AJAX -> sitemap+JSON-LD. First hit wins.

    Lets us point the scanner at any employer careers site without knowing
    (or hard-coding a guess about) which platform runs it.
    """
    kind = "auto"

    def fetch(self) -> List[Job]:
        from .jibe import fetch_jibe  # local import to avoid a cycle
        base = self.cfg["base"]
        errors = []
        for label, fn in [
            ("jibe", lambda: fetch_jibe(base, self.queries, self.id, self.name)),
            ("radancy", lambda: fetch_radancy_ajax(base, self.queries, self.id, self.name)),
            ("sitemap", lambda: fetch_sitemap_jsonld(base, self.queries, self.id, self.name)),
        ]:
            try:
                jobs = fn()
                if jobs:
                    print(f"[{self.id}] strategy '{label}' -> {len(jobs)} postings")
                    return self.dedupe(jobs)
            except Exception as e:
                errors.append(f"{label}: {type(e).__name__}")
                continue
        print(f"[{self.id}] all strategies empty ({'; '.join(errors) or 'no errors, no jobs'})")
        return []
