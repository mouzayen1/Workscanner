"""Travel/contract job sources.

Vivian Health aggregates allied-travel contracts from dozens of staffing
agencies (LanceSoft, Host Healthcare, Cross Country Allied, TotalMed, Triage,
Stability, ...), which makes it the highest-leverage single scan for the travel
category. Its pages are Next.js: the full search payload is embedded in a
<script id="__NEXT_DATA__"> JSON blob, which we parse without executing JS.
Note: Vivian files PET/CT under the "nuclear-medicine-tech" specialty slug.

Aya Healthcare is the biggest agency with direct-apply inventory (and showed
Orange, CA contracts in research), so we scan its server-rendered SEO pages too.
"""
from __future__ import annotations

import json
import re
from typing import Any, List, Optional

from bs4 import BeautifulSoup

from ..models import Job
from .base import Source, session, polite_pause

_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>',
    re.DOTALL,
)


def _walk(node: Any, out: List[dict]) -> None:
    """Collect dicts that look like job postings from an arbitrary JSON tree."""
    if isinstance(node, dict):
        keys = set(node.keys())
        looks_like_job = ("title" in keys or "jobTitle" in keys) and (
            "payRate" in keys or "weeklyPay" in keys or "facility" in keys
            or "specialty" in keys or "jobUrl" in keys or "vivReqId" in keys
            or "shift" in keys or "duration" in keys
        )
        if looks_like_job:
            out.append(node)
        for v in node.values():
            _walk(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk(v, out)


def _str(v) -> Optional[str]:
    return v if isinstance(v, str) and v else None


class VivianSource(Source):
    kind = "vivian"

    def fetch(self) -> List[Job]:
        urls = self.cfg.get("urls", [
            "https://www.vivian.com/allied-health/nuclear-medicine-tech/travel/california/",
            "https://www.vivian.com/allied-health/nuclear-medicine-tech/staff/california/",
        ])
        jobs: List[Job] = []
        for url in urls:
            r = session().get(url, timeout=30)
            r.raise_for_status()
            m = _NEXT_DATA.search(r.text)
            if not m:
                continue
            tree = json.loads(m.group(1))
            found: List[dict] = []
            _walk(tree, found)
            for d in found:
                jid = str(d.get("id") or d.get("vivReqId") or "")
                title = _str(d.get("title")) or _str(d.get("jobTitle")) or ""
                if not jid or not title:
                    continue
                loc = d.get("location") if isinstance(d.get("location"), dict) else {}
                city = _str(d.get("city")) or _str(loc.get("city"))
                state = _str(d.get("state")) or _str(loc.get("state"))
                agency = d.get("agency") if isinstance(d.get("agency"), dict) else {}
                company = _str(agency.get("name")) or _str(d.get("agencyName")) \
                    or "via Vivian"
                pay_txt = ""
                pay = d.get("payRate") if isinstance(d.get("payRate"), dict) else {}
                lo = pay.get("min") or pay.get("minHourly") or d.get("weeklyPayMin")
                hi = pay.get("max") or pay.get("maxHourly") or d.get("weeklyPayMax")
                if lo or hi:
                    pay_txt = f"${lo or '?'}–${hi or '?'}"
                job_url = _str(d.get("jobUrl")) or _str(d.get("url")) or ""
                if job_url.startswith("/"):
                    job_url = "https://www.vivian.com" + job_url
                jobs.append(Job(
                    source=self.id,
                    source_job_id=jid,
                    title=title[:160],
                    company=company,
                    url=job_url or url,
                    location_raw=", ".join(x for x in [city, state] if x),
                    city=city,
                    state=state if state and len(state) == 2 else None,
                    salary_raw=pay_txt,
                ))
            polite_pause(1.0)
        return self.dedupe(jobs)


class AyaSource(Source):
    kind = "aya"

    def fetch(self) -> List[Job]:
        urls = self.cfg.get("urls", [
            "https://www.ayahealthcare.com/healthcare-jobs/allied/radiology-cardiology/nuclear-medicine-tech/state/california/",
        ])
        jobs: List[Job] = []
        for url in urls:
            r = session().get(url, timeout=30)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")
            # Aya SEO pages list jobs as cards with links into the job flow and
            # "City, CA" + "$N,NNN/week" strings; structure shifts, so anchor on text.
            for a in soup.find_all("a", href=re.compile(r"/(healthcare-jobs|job)/", re.I)):
                card = a.find_parent("li") or a.find_parent("article") or a.find_parent("div")
                if card is None:
                    continue
                text = re.sub(r"\s+", " ", card.get_text(" ")).strip()
                if not re.search(r"nuclear|pet", text, re.I):
                    continue
                m_loc = re.search(r"([A-Za-z .'-]+,\s*CA)\b", text)
                m_pay = re.search(r"\$[\d,]+(?:\.\d+)?\s*/\s*(?:week|wk|hour|hr)", text)
                title = re.sub(r"\s+", " ", a.get_text(" ")).strip()
                if not title or len(title) < 8 or not m_loc:
                    continue
                href = a["href"]
                jurl = href if href.startswith("http") else "https://www.ayahealthcare.com" + href
                jobs.append(Job(
                    source=self.id,
                    source_job_id=jurl,
                    title=title[:160],
                    company="Aya Healthcare",
                    url=jurl,
                    location_raw=m_loc.group(1),
                    salary_raw=m_pay.group(0) if m_pay else "",
                ))
            polite_pause(1.0)
        return self.dedupe(jobs)
