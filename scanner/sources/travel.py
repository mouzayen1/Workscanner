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
        title_key = keys & {"title", "jobTitle", "name", "positionTitle"}
        signal_keys = keys & {
            "payRate", "weeklyPay", "weeklyPayCents", "payAmountMax", "maxPay",
            "facility", "facilityName", "specialty", "jobUrl", "vivReqId",
            "shift", "duration", "durationWeeks", "employmentType", "agency",
            "agencyName", "startDate", "payDisplay",
        }
        if title_key and len(signal_keys) >= 2:
            out.append(node)
        for v in node.values():
            _walk(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk(v, out)


def _debug_tree(tree: dict) -> str:
    """One line describing where the data likely lives, for remote debugging."""
    try:
        props = tree.get("props", {}).get("pageProps", {})
        parts = []
        for k, v in list(props.items())[:12]:
            if isinstance(v, list):
                parts.append(f"{k}[{len(v)}]")
            elif isinstance(v, dict):
                parts.append(f"{k}{{{','.join(list(v.keys())[:6])}}}")
            else:
                parts.append(k)
        return "; ".join(parts)[:400]
    except Exception:
        return "unreadable"


def _str(v) -> Optional[str]:
    return v if isinstance(v, str) and v else None


def _city_from_blob(candidate: str) -> Optional[str]:
    """'...Nuclear Medicine Technologist Los Alamitos' -> 'Los Alamitos'.

    Card text runs the title straight into the city; drop everything through
    the last role word, then keep at most the trailing three words.
    """
    cleaned = re.sub(
        r".*\b(?:Technologist|Technician|Tech|Nurse|RN|II|I)\b", "", candidate
    ).strip(" -–·|")
    words = (cleaned or candidate).strip().split()
    return " ".join(words[-3:]).title() if words else None


class VivianSource(Source):
    kind = "vivian"

    def fetch(self) -> List[Job]:
        urls = self.cfg.get("urls", [
            "https://www.vivian.com/allied-health/nuclear-medicine-tech/travel/california/",
        ])
        jobs: List[Job] = []
        for url in urls:
            try:
                r = session().get(url, timeout=30)
                r.raise_for_status()
            except Exception as e:  # one bad URL must not sink the others
                print(f"[vivian] {url} failed: {type(e).__name__}: {e}")
                continue
            # Strategy 1: server-rendered job cards in the listing HTML.
            # (Vivian's __NEXT_DATA__ only carries SEO page config; the list
            # itself is rendered into the HTML for crawlers.)
            soup = BeautifulSoup(r.text, "lxml")
            card_links = [a for a in soup.find_all("a", href=True)
                          if re.search(r"/job/", a["href"])]
            for a in card_links:
                card = a.find_parent("li") or a.find_parent("article") \
                    or a.find_parent("div") or a
                text = re.sub(r"\s+", " ", card.get_text(" ")).strip()
                title_el = a.select_one("h1,h2,h3,h4,[class*='title']") or a
                title = re.sub(r"\s+", " ", title_el.get_text(" ")).strip()
                title = re.sub(r"^View job details for\s+", "", title, flags=re.I)
                if not title or not re.search(r"nuclear|pet", title + " " + text[:120], re.I):
                    continue
                href = a["href"]
                jurl = href if href.startswith("http") else "https://www.vivian.com" + href
                m_id = re.search(r"/job/(?:v/)?([A-Za-z0-9-]+)", href)
                m_city = re.search(r"([A-Za-z .'-]{3,40}),\s*(?:CA|California)\b", text)
                m_pay = re.search(r"\$[\d,]+(?:\.\d+)?\s*/(?:wk|week|hr|hour)", text)
                city = _city_from_blob(m_city.group(1)) if m_city else None
                jobs.append(Job(
                    source=self.id,
                    source_job_id=m_id.group(1) if m_id else jurl,
                    title=title[:160],
                    company="via Vivian",
                    url=jurl,
                    location_raw=f"{city}, CA" if city else "California",
                    city=city,
                    state=self.cfg.get("default_state"),
                    salary_raw=m_pay.group(0) if m_pay else "",
                ))
            print(f"[vivian] html cards: {len(card_links)} job links, "
                  f"{len(jobs)} parsed at {url[:80]}")

            # Strategy 2: any job objects that do ship in __NEXT_DATA__.
            m = _NEXT_DATA.search(r.text)
            if not m:
                print(f"[vivian] no __NEXT_DATA__ blob at {url}")
                continue
            tree = json.loads(m.group(1))
            found: List[dict] = []
            _walk(tree, found)
            if not found and not jobs:
                print(f"[vivian] 0 job-shaped dicts at {url}; "
                      f"pageProps: {_debug_tree(tree)}")
            for d in found:
                jid = str(d.get("id") or d.get("vivReqId") or "")
                title = _str(d.get("title")) or _str(d.get("jobTitle")) \
                    or _str(d.get("name")) or ""
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
                    state=(state if state and len(state) == 2
                           else self.cfg.get("default_state")),
                    salary_raw=pay_txt,
                ))
            polite_pause(1.0)
        return self.dedupe(jobs)


_AYA_ROLE = re.compile(r"nuclear|pet[\s/-]?ct", re.I)
_AYA_SKIP = re.compile(r"register|login|sign-?in|/state/|/type/|/search", re.I)
_CITY_CA = re.compile(r"([A-Za-z .'-]{3,30}),\s*(?:CA|California)\b")
_JOB_IN = re.compile(r"\bjob in ([A-Z][A-Za-z .'-]{2,28}?)(?:,|\s*$|\s+\$)", re.I)
_PAY = re.compile(r"\$[\d,]+(?:\.\d+)?\s*(?:/|per\s*)(?:week|wk|hour|hr)", re.I)


class AyaSource(Source):
    kind = "aya"
    # Aya's SEO listing pages are server-rendered job cards. Markup shifts, so
    # we anchor on headings/cards whose text names the role, then find the
    # card's job link.

    def fetch(self) -> List[Job]:
        urls = self.cfg.get("urls", [
            "https://www.ayahealthcare.com/healthcare-jobs/allied/radiology-cardiology/nuclear-medicine-tech/state/california/",
        ])
        jobs: List[Job] = []
        for url in urls:
            r = session().get(url, timeout=30)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")
            cards = []
            for h in soup.select("h1, h2, h3, h4, [class*='title'], [class*='card']"):
                if _AYA_ROLE.search(h.get_text(" ")):
                    cards.append(h.find_parent("li") or h.find_parent("article")
                                 or h.find_parent("div") or h)
            n_kept = 0
            for card in cards:
                text = re.sub(r"\s+", " ", card.get_text(" ")).strip()
                if re.search(r"FAQ|General|Overview|Why Aya|Related", text[:60], re.I):
                    continue
                # only real job cards link to a numbered job page
                a = None
                for cand in card.find_all("a", href=True):
                    if _AYA_SKIP.search(cand["href"]):
                        continue
                    if re.search(r"/\d{5,}", cand["href"]):
                        a = cand
                        break
                if a is None:
                    continue
                m_in = _JOB_IN.search(text)
                m_ca = _CITY_CA.search(text)
                city = None
                if m_in:
                    city = m_in.group(1).strip().title()
                elif m_ca:
                    # keep only the trailing words that look like a city name
                    words = m_ca.group(1).strip().split()
                    city = " ".join(words[-3:]).title()
                m_pay = _PAY.search(text)
                m_title = re.search(
                    r"((?:Travel|Local|Locum)\s+(?:Senior )?"
                    r"(?:Nuclear Med(?:icine)?( Tech(nologist)?)?|PET[/ -]?CT( Tech(nologist)?)?))",
                    text, re.I)
                title = m_title.group(1) if m_title else "Travel Nuclear Medicine Tech"
                href = a["href"]
                jurl = href if href.startswith("http") \
                    else "https://www.ayahealthcare.com" + href
                m_id = re.search(r"/(\d{5,})", jurl)
                n_kept += 1
                jobs.append(Job(
                    source=self.id,
                    source_job_id=m_id.group(1) if m_id else jurl,
                    title=re.sub(r"\s+", " ", title).strip().title()[:160],
                    company="Aya Healthcare",
                    url=jurl,
                    location_raw=f"{city}, CA" if city else "California",
                    city=city,
                    state="CA",
                    salary_raw=m_pay.group(0) if m_pay else "",
                ))
            print(f"[aya] {len(cards)} role cards -> {n_kept} job links at {url[:80]}")
            polite_pause(1.0)
        return self.dedupe(jobs)
