"""Regression tests for review findings (run: python tests/test_scoring_regressions.py)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml
import requests

from scanner.scoring import is_role_match, classify, _PET
from scanner.geo import Region
from scanner.models import Job
from scanner.main import _safe_error

region = Region(yaml.safe_load(open("config/search.yml")))


def mk(title, loc, desc="", source="adzuna", lat=None, lon=None):
    j = Job(source=source, source_job_id=title + loc + desc[:20], title=title,
            company="X", url="u", location_raw=loc, description=desc,
            latitude=lat, longitude=lon)
    return classify(j, region, {})


# "no call / no weekends" perks must not count as inpatient signals
j = mk("PET/CT Technologist", "Irvine, CA",
       "Join our imaging center. No weekend rotation, no on-call.")
assert j.category == "outpatient-pet" and j.score >= 95, (j.category, j.score)

# "pet insurance" benefits boilerplate must not trigger the PET bonus
j2 = mk("Nuclear Medicine Technologist", "Irvine, CA",
        "outpatient clinic. Benefits: 401k, pet insurance, pet-friendly office")
assert j2.category == "outpatient-nm" and "PET" not in j2.tags
assert _PET.search("PET/CT scanner") and _PET.search("PET Technologist duties")
assert not _PET.search("pet insurance")

# city-rescue guard rails
jx = mk("Nuclear Medicine Technologist", "Orange County Global Health, Nowhere, TX")
assert jx.location_tier == 0
jc = mk("Nuclear Medicine Technologist", "1200 Corona Pointe Ct, Riverside, CA")
assert jc.city and jc.city != "Corona Pointe"
assert region.find_city_in_text("Orange County Medical Plaza") is None
assert region.find_city_in_text("WaveImaging Orange, CA") == "Orange"

# role filter: real titles in, non-tech roles out
for t, want in [
    ("Nuclear Medicine Technologist - Physician Office", True),
    ("Nuclear Cardiology Technologist", True),
    ("Cardiac Nuclear Technologist", True),
    ("NM Tech", True),
    ("NM/PET Technologist", True),
    ("PET/CT Scheduler", False),
    ("Nuclear Medicine Receptionist", False),
    ("Radiologist - Nuclear Medicine", False),
    ("Patient Transporter - Nuclear Medicine", False),
    ("Nuclear Medicine Program Instructor", False),
    ("Nuclear Medicine Physician", False),
    ("Nuclear Medicine/PET Technologist", True),
]:
    assert is_role_match(t) == want, t

# cert laundry lists in non-NM ads must not pass; real requirements must
assert not is_role_match(
    "Imaging Technologist",
    "We accept ARRT, NMTCB, or RDMS credentials in our multi-modality department roster listing")
assert is_role_match("Imaging Technologist", "NMTCB certification required")

# travel contracts detected from description; "no travel required" is not travel
assert mk("Nuclear Medicine Technologist", "Bakersfield, CA",
          "13-week contract assignment, weekly gross $3,100").category == "travel"
assert mk("Nuclear Medicine Technologist", "Irvine, CA",
          "outpatient center, no travel required").category != "travel"

# API keys must never survive into published error strings
try:
    raise requests.exceptions.HTTPError(
        "401 Client Error: Unauthorized for url: https://api.adzuna.com/v1/api/"
        "jobs/us/search/1?app_id=abc123&app_key=SECRETKEY0123456789&what=nuclear")
except Exception as e:
    s = _safe_error(e)
    assert "SECRETKEY" not in s and "app_key" not in s, s
try:
    raise requests.exceptions.HTTPError("404 for url: https://jooble.org/api/MYSECRETJOOBLEKEY")
except Exception as e:
    assert "MYSECRETJOOBLEKEY" not in _safe_error(e)

print("ALL SCORING REGRESSION TESTS PASSED")
