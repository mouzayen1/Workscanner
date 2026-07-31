"""Shared HTTP plumbing for all sources: polite, retried, timeboxed."""
from __future__ import annotations

import time
from typing import List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..models import Job

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36 Workscanner/1.0 (personal job-search tool; low volume)"
)

# One shared session: connection pooling + a conservative retry policy.
_session: Optional[requests.Session] = None


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        retry = Retry(
            total=3, backoff_factor=1.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        s.mount("https://", HTTPAdapter(max_retries=retry))
        s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
        _session = s
    return _session


def get_json(url: str, *, params=None, headers=None, timeout=30):
    r = session().get(url, params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()


def post_json(url: str, *, json_body=None, headers=None, timeout=30):
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        h.update(headers)
    r = session().post(url, json=json_body, headers=h, timeout=timeout)
    r.raise_for_status()
    return r.json()


def polite_pause(seconds: float = 1.0) -> None:
    time.sleep(seconds)


class Source:
    """Base class. Subclasses implement fetch() -> List[Job]."""

    kind = "base"

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.id = cfg["id"]
        self.name = cfg.get("name", self.id)
        self.queries = cfg.get("queries", ["nuclear medicine", "PET"])

    def fetch(self) -> List[Job]:  # pragma: no cover - abstract
        raise NotImplementedError

    def dedupe(self, jobs: List[Job]) -> List[Job]:
        """Multiple query terms often return the same posting; keep one."""
        seen, out = set(), []
        for j in jobs:
            if j.key not in seen:
                seen.add(j.key)
                out.append(j)
        return out
