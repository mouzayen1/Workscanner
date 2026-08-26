"""Role filtering, category classification, and preference scoring.

The user's priorities, encoded:
  1. PET/CT strongly preferred (plain nuclear medicine acceptable)
  2. Outpatient-only settings: imaging centers, doctor offices, clinics;
     hospitals only if the role itself is outpatient-only
  3. Target cities in Orange County + Chino/Chino Hills/Corona corridor
  4. Travel/contract positions tracked separately
"""
from __future__ import annotations

import re
from .models import (
    Job, CAT_OUTPATIENT_PET, CAT_OUTPATIENT_NM, CAT_HOSPITAL_OTHER, CAT_TRAVEL,
)
from .geo import Region, parse_city_state, normalize_state

# ---- role filter -----------------------------------------------------------

# A job is "ours" if the title clearly names the role...
_TITLE_ROLE = re.compile(
    r"nuclear\s*med|nuc\s*med\b|\bnmt\b|\bcnmt\b"
    r"|pet[\s/\-]*ct|\bpet\b.{0,20}(tech|imaging|scan)|positron|molecular imaging"
    r"|nuclear\s*(cardiology|stress)|cardiac\s*nuclear|\bnm\b[\s/,-]*(pet|tech)",
    re.IGNORECASE,
)
# ...and is NOT one of the classic "PET" false positives or a non-tech role.
# "physician office" stays allowed (that's the user's target setting); a
# physician *role* is vetoed.
_TITLE_VETO = re.compile(
    r"veterinar|\bpet\s*(care|groom|sitt|hotel|resort|food|insurance|stylist)"
    r"|petroleum|carpet|animal|\bvet\b|pharmacist|physician(?![’']?s?\s+(office|practice))"
    r"|nurse\b|\brn\b|sales|recruiter|radiopharmac(?!.*tech)|courier|driver"
    r"|scheduler|receptionist|front\s*desk|radiologist|transport(er|ation)"
    r"|\baide\b|instructor|professor|faculty|billing|\bcoder\b"
    r"|ultrasound|sonograph|\bmri\b|mammograph",  # other-modality titles whose
    re.IGNORECASE,                                # ads mention NM in passing
)
# Description-level match as a fallback when the title is generic
# (e.g. "Imaging Technologist" that turns out to be NM). Bare cert acronyms
# need a "required/certified" context so multi-cert laundry lists in x-ray or
# ultrasound ads don't sneak in.
_DESC_ROLE = re.compile(
    r"nuclear medicine technologist|pet[\s/\-]*ct technologist"
    r"|\b(cnmt|nmtcb)\b[\s\w()]{0,25}(required|preferred|certified)"
    r"|(required|preferred|certified)[\s\w:,()]{0,25}\b(cnmt|nmtcb)\b",
    re.IGNORECASE,
)

# ---- setting / modality / schedule signals --------------------------------

# No bare \bpet\b: "pet insurance" / "pet-friendly" benefits boilerplate must
# not promote a plain-NM job into the PET category.
_PET = re.compile(
    r"\bpet[\s/\-]*ct\b|\bpet\s+(scan|imaging|tech)|positron"
    r"|theranostic|pluvicto|lutetium|\bpsma\b|\bfdg\b",
    re.IGNORECASE,
)
_SPECT = re.compile(r"\bspect\b|gamma camera|cardiac stress|myocardial|cardiolite|lexiscan", re.IGNORECASE)

_OUTPATIENT = re.compile(
    r"outpatient|out-patient|imaging center|imaging centre|freestanding|free-standing"
    r"|ambulatory|clinic\b|physician[’']?s? office|doctor[’']?s? office|medical office"
    r"|medical group|office[\s-]based|diagnostic center",
    re.IGNORECASE,
)
_INPATIENT = re.compile(
    r"inpatient|in-patient|on[\s-]?call|call\s+(required|rotation|schedule)|take call"
    r"|weekend rotation|holiday rotation|trauma center|emergency department|\bER\b"
    r"|night shift|overnight|24/7|acute care|bedside",
    re.IGNORECASE,
)
_NICE_SCHEDULE = re.compile(
    r"no\s+(on[\s-]?call|call|weekends?|nights?)"
    r"|monday\s*(-|through|thru|to)\s*(friday|thursday)"
    r"|m\s*-\s*f\b|weekdays only|day shift|4[\s-]?(day|/)\s*(work)?\s*week|4x10|4\s*x\s*10",
    re.IGNORECASE,
)
# Negated schedule perks ("no call required", "no weekend rotation") must be
# removed before counting inpatient signals — they mean the opposite.
_NEGATED_SCHED = re.compile(
    r"\bno\s+(?:on[\s-]?call|call|weekends?|nights?|holidays?)"
    r"(?:\s+(?:required|rotation|shifts?|coverage|duty))?",
    re.IGNORECASE,
)

_TRAVEL = re.compile(
    r"\btravel\b|\blocum|13[\s-]?week|8[\s-]?week|contract assignment|travel assignment"
    r"|allied travel|interim\b",
    re.IGNORECASE,
)
# Description-level contract markers (narrow on purpose: no bare "travel",
# which would false-positive on "no travel required").
_TRAVEL_DESC = re.compile(
    r"\b(?:8|1[0-9]|2[0-6])[\s-]?week|contract assignment|travel assignment"
    r"|weekly (gross|pay|stipend)",
    re.IGNORECASE,
)
_PER_DIEM = re.compile(r"per[\s-]?diem|\bprn\b|registry\b|on[\s-]?demand", re.IGNORECASE)


def is_role_match(title: str, description: str = "") -> bool:
    if _TITLE_VETO.search(title or ""):
        return False
    if _TITLE_ROLE.search(title or ""):
        return True
    return bool(_DESC_ROLE.search(description or ""))


def classify(job: Job, region: Region, source_cfg: dict) -> Job:
    """Fill in city/state/tier, category, score, and tags. Returns the same Job."""
    text = f"{job.title}\n{job.location_raw}\n{job.description}"
    src_setting = (source_cfg or {}).get("setting", "")          # 'outpatient' | 'hospital' | ''
    src_travel = bool((source_cfg or {}).get("travel", False))   # travel agency/board source

    # location
    job.state = normalize_state(job.state)
    if not job.city or not job.state:
        city, state = parse_city_state(job.location_raw)
        job.city = job.city or city
        job.state = job.state or normalize_state(state)
    job.location_tier = region.tier_for(job.city, job.state, job.latitude, job.longitude)
    # Messy concatenated location text (Radancy cards): rescue by scanning for
    # a known target city. Guard rails: never when coordinates already answered
    # the question, never override a non-CA posting, and a title-only match is
    # trusted only when the state is already known to be CA.
    if job.location_tier == 0 and job.latitude is None and job.state in (None, "CA"):
        found = region.find_city_in_text(job.location_raw)
        if not found and job.state == "CA":
            found = region.find_city_in_text(job.title)
        if found:
            job.city = found
            job.state = job.state or "CA"
            job.location_tier = region.tier_for(job.city, job.state)

    # signals
    pet = bool(_PET.search(text))
    spect = bool(_SPECT.search(text))
    outpatient_hits = len(_OUTPATIENT.findall(text))
    inpatient_hits = len(_INPATIENT.findall(_NEGATED_SCHED.sub("", text)))
    nice_sched = bool(_NICE_SCHEDULE.search(text))
    travel = (src_travel or bool(_TRAVEL.search(job.title))
              or bool(_TRAVEL.search(job.company))
              or bool(_TRAVEL_DESC.search(job.description or "")))
    per_diem = bool(_PER_DIEM.search(job.title)) or bool(_PER_DIEM.search(text[:400]))

    tags = []
    if pet:
        tags.append("PET")
    if spect:
        tags.append("SPECT")
    if re.search(r"theranostic|pluvicto|lutetium|psma", text, re.IGNORECASE):
        tags.append("theranostics")
    if nice_sched:
        tags.append("good-schedule")
    if per_diem and not travel:
        tags.append("per-diem")
    if job.city is None and job.latitude is None:
        tags.append("location-unverified")

    # setting: employer prior + text evidence
    outpatient_like = (
        src_setting == "outpatient"
        or outpatient_hits >= 1 and inpatient_hits == 0
        or outpatient_hits >= 2 and outpatient_hits > inpatient_hits
    )
    hospital_like = src_setting == "hospital" and not outpatient_like

    if travel:
        job.category = CAT_TRAVEL
    elif outpatient_like and pet:
        job.category = CAT_OUTPATIENT_PET
    elif outpatient_like:
        job.category = CAT_OUTPATIENT_NM
    else:
        job.category = CAT_HOSPITAL_OTHER
        if hospital_like:
            tags.append("hospital")

    # score (0–100): what should the user look at first?
    score = 40
    if pet:
        score += 25
    if outpatient_like:
        score += 20
    elif src_setting == "hospital":
        score -= 5
    score -= min(inpatient_hits * 7, 20)
    if nice_sched:
        score += 5
    if job.location_tier == 1:
        score += 15
    elif job.location_tier == 2:
        score += 8
    elif job.location_tier == 0 and "location-unverified" not in tags:
        score -= 15
    if per_diem and not travel:
        score -= 8  # user wants a stable full-time role first
    job.score = max(0, min(100, score))
    job.tags = tags
    return job


def in_scope(job: Job, region: Region) -> bool:
    if job.category == CAT_TRAVEL:
        return region.in_scope_travel(job.city, job.state)
    return region.in_scope_perm(job.city, job.state, job.latitude, job.longitude)
