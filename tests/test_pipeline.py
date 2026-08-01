"""Offline end-to-end test of the scoring/state/report pipeline with synthetic jobs."""
import os, sys, json, shutil, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scanner.models import Job
from scanner.geo import Region, parse_city_state
from scanner.scoring import classify, is_role_match, in_scope
from scanner.state import merge, save_state, load_state
from scanner.report import write_digest, write_dashboard
from scanner.main import load_cfg, _cross_source_dedupe

search_cfg, sources_cfg = load_cfg()
region = Region(search_cfg)
src = {c["id"]: c for c in sources_cfg}

# ---- role filter ----
cases = [
    ("Nuclear Medicine/PET Technologist", "", True),
    ("PET/CT Technologist", "", True),
    ("Nuclear Med Tech Per Diem", "", True),
    ("CNMT - Molecular Imaging", "", True),
    ("Pet Groomer", "", False),
    ("Veterinary Technician", "", False),
    ("Petroleum Engineer", "", False),
    ("Carpet Cleaner", "", False),
    ("Registered Nurse - Nuclear Medicine", "", False),
    ("Imaging Technologist", "seeking a certified nuclear medicine technologist (CNMT)", True),
    ("Radiologic Technologist", "x-ray duties", False),
    ("Nuclear Medicine Physician", "", False),
]
for title, desc, want in cases:
    got = is_role_match(title, desc)
    status = "OK " if got == want else "FAIL"
    print(f"{status} role_match({title!r}) = {got} (want {want})")
    assert got == want, title

# ---- location parsing ----
loc_cases = [
    ("Newport Beach, CA", ("Newport Beach", "CA")),
    ("Orange, California", ("Orange", "CA")),
    ("Chino Hills, CA 91709", ("Chino Hills", "CA")),
    ("Phoenix, AZ", ("Phoenix", "AZ")),
    ("California", (None, "CA")),
]
for raw, want in loc_cases:
    got = parse_city_state(raw)
    status = "OK " if got == want else "FAIL"
    print(f"{status} parse({raw!r}) = {got}")
    assert got == want, raw

# ---- classification ----
def mk(title, loc, desc="", source="radnet", company="Test Co"):
    j = Job(source=source, source_job_id=title+loc, title=title, company=company,
            url="https://x/y", location_raw=loc, description=desc)
    return classify(j, region, src.get(source, {}))

j1 = mk("Nuclear Medicine/PET Technologist", "Orange, CA",
        "outpatient imaging center, Monday-Thursday, no call")
print(f"\nj1: cat={j1.category} score={j1.score} tier={j1.location_tier} tags={j1.tags}")
assert j1.category == "outpatient-pet" and j1.score >= 90, (j1.category, j1.score)

j2 = mk("Nuclear Medicine Technologist", "Corona, CA",
        "hospital department, on-call required, weekend rotation", source="uhs",
        company="Corona Regional")
print(f"j2: cat={j2.category} score={j2.score} tier={j2.location_tier} tags={j2.tags}")
assert j2.category == "hospital-other", j2.category

j3 = mk("Travel Nuclear Medicine Technologist", "Mission Viejo, CA", "13 week contract",
        source="vivian", company="Host Healthcare")
print(f"j3: cat={j3.category} score={j3.score}")
assert j3.category == "travel", j3.category

j4 = mk("PET/CT Technologist", "Phoenix, AZ", "outpatient center")
print(f"j4: cat={j4.category} in_scope={in_scope(j4, region)}")
assert not in_scope(j4, region), "AZ perm job must be out of scope"

j5 = mk("Travel PET Technologist", "Sacramento, CA", "", source="vivian")
print(f"j5: travel in_scope={in_scope(j5, region)} (CA travel kept)")
assert in_scope(j5, region)

j6 = mk("Nuclear Medicine Technologist", "Riverside, CA", "outpatient imaging center")
print(f"j6: cat={j6.category} score={j6.score} tier={j6.location_tier} (tier2 city)")
assert j6.location_tier == 2

# unlocatable CA job kept for review
j7 = mk("Nuclear Medicine Technologist", "", "")
print(f"j7: in_scope={in_scope(j7, region)} tags={j7.tags} (unlocatable kept)")
assert in_scope(j7, region) and "location-unverified" in j7.tags

# ---- cross-source dedupe ----
d1 = mk("Nuclear Medicine/PET Technologist", "Orange, CA")                      # direct
d2 = mk("Nuclear Medicine / PET Technologist", "Orange, CA", source="adzuna")   # aggregator dup
d2.company = d1.company
deduped = _cross_source_dedupe([d1, d2], src)
print(f"\ndedupe: {len(deduped)} of 2 kept (want 1)")
assert len(deduped) == 1

# ---- state merge + digest + dashboard (in temp dir) ----
tmp = tempfile.mkdtemp()
os.chdir(tmp)
state = {"updated": None, "jobs": {}, "misses": {}}
state, new1 = merge(state, [j1, j2, j3], {"radnet", "uhs", "vivian"})
assert len(new1) == 3
# second scan: j2 missing (healthy source) twice -> inactive
state, new2 = merge(state, [j1, j3], {"radnet", "uhs", "vivian"})
state, new3 = merge(state, [j1, j3], {"radnet", "uhs", "vivian"})
assert len(new2) == 0 and len(new3) == 0
inactive = [d for d in state["jobs"].values() if not d["active"]]
print(f"state: {len(state['jobs'])} known, {len(inactive)} inactive after 2 misses")
assert len(inactive) == 1
# failed source: jobs must NOT be aged out
state2, _ = merge(state, [], set())
assert all(d["active"] for k, d in state2["jobs"].items()
           if d["source"] == "radnet"), "failed source aged out jobs!"
print("state: failed-source protection OK")

save_state(state)
n = write_digest(new1)
write_dashboard(state, {"radnet": "ok (2 raw)", "uhs": "error: HTTPError: 500"})
assert os.path.exists("data/jobs.json") and os.path.exists("docs/index.html")
html = open("docs/index.html").read()
assert "Nuclear Medicine/PET Technologist" in html and "__DATA__" not in html
digest = open("data/new_jobs.md").read()
assert "Outpatient PET/CT" in digest and "Travel / Contract" in digest
print(f"digest: {n} new jobs written; dashboard renders with embedded data")
# JSON in dashboard is parseable
import re
m = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)
payload = json.loads(m.group(1).replace("<\\/", "</"))
assert payload["jobs"], "dashboard payload empty"
print("dashboard payload JSON parses OK")

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
shutil.rmtree(tmp)
print("\nALL OFFLINE TESTS PASSED")
