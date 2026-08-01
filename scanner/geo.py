"""Location parsing and target-region matching."""
from __future__ import annotations

import math
import re
from typing import Optional, Tuple

_CITY_STATE = re.compile(r"([A-Za-z .'-]+?)\s*,\s*(CA|California)\b", re.IGNORECASE)
_STATE_ONLY = re.compile(r"\b(CA|California)\b", re.IGNORECASE)

_STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC",
}
_STATE_ABBRS = set(_STATE_NAMES.values())


def normalize_state(val) -> Optional[str]:
    """'California'/'CA'/'ca' -> 'CA'; anything unrecognized -> None."""
    if not val:
        return None
    v = str(val).strip()
    if len(v) == 2 and v.upper() in _STATE_ABBRS:
        return v.upper()
    return _STATE_NAMES.get(v.lower())


def parse_city_state(location_raw: str) -> Tuple[Optional[str], Optional[str]]:
    """Best-effort parse of 'City, CA'-style location text."""
    if not location_raw:
        return None, None
    m = _CITY_STATE.search(location_raw)
    if m:
        city = m.group(1).strip().title()
        # "Los Angeles Metropolitan Area" style noise
        city = re.sub(r"\b(Greater|Metropolitan|Metro|Area)\b", "", city).strip()
        return (city or None), "CA"
    # try "City, ST" for any state
    m2 = re.search(r"([A-Za-z .'-]+?)\s*,\s*([A-Z]{2})\b", location_raw)
    if m2:
        return m2.group(1).strip().title(), m2.group(2).upper()
    if _STATE_ONLY.search(location_raw):
        return None, "CA"
    return None, None


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.8  # earth radius, miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class Region:
    """Answers: is this job inside the user's target area, and how central is it?"""

    def __init__(self, cfg: dict):
        target = cfg.get("target", {})
        self.tier1 = {c.strip().lower() for c in target.get("tier1_cities", [])}
        self.tier2 = {c.strip().lower() for c in target.get("tier2_cities", [])}
        self.anchors = [
            (a["lat"], a["lon"]) for a in target.get("anchors", [])
        ]
        self.max_miles = float(target.get("max_miles", 40))
        self.travel_states = {s.upper() for s in cfg.get("travel", {}).get("states", ["CA"])}
        # For messy location text ("...Orange Coast Medical Center Fountain
        # Valley, California"): scan for any known target city, longest last
        # occurrence wins ("Orange Coast ... Fountain Valley" -> Fountain Valley).
        all_cities = sorted(self.tier1 | self.tier2, key=len, reverse=True)
        self._city_rx = re.compile(
            r"\b(" + "|".join(re.escape(c) for c in all_cities) + r")\b",
            re.IGNORECASE,
        ) if all_cities else None

    # A "city" immediately followed by one of these is a street/place name
    # ("Orange County", "Orange Grove Ave", "Corona Pointe Ct"), not a city.
    _NOT_CITY_SUFFIX = re.compile(
        r"^\s+(county|coast|grove|crest|pointe?|plaza|hills? (?:pkwy|parkway|rd|road))\b"
        r"|^\s+(ave|avenue|blvd|boulevard|st|street|rd|road|dr|drive|ln|lane"
        r"|hwy|highway|fwy|freeway|pkwy|parkway|cir|circle|ct|court|way)\b\.?",
        re.IGNORECASE,
    )

    def find_city_in_text(self, text: str) -> Optional[str]:
        if not self._city_rx or not text:
            return None
        good = [m for m in self._city_rx.finditer(text)
                if not self._NOT_CITY_SUFFIX.match(text[m.end():m.end() + 24])]
        if not good:
            return None
        return good[-1].group(1).title()

    def tier_for(self, city: Optional[str], state: Optional[str],
                 lat: Optional[float] = None, lon: Optional[float] = None) -> int:
        """1 = core target city, 2 = nearby/in-radius, 0 = outside or unknown."""
        # State first: "Westminster, Maryland" must not match Westminster (OC).
        if state and state.upper() != "CA":
            return 0
        if city:
            c = city.strip().lower()
            if c in self.tier1:
                return 1
            if c in self.tier2:
                return 2
        if lat is not None and lon is not None and self.anchors:
            dist = min(haversine_miles(lat, lon, a[0], a[1]) for a in self.anchors)
            if dist <= self.max_miles * 0.5:
                return 1 if not city else 2  # in tight radius but not a listed city
            if dist <= self.max_miles:
                return 2
        return 0

    def in_scope_perm(self, city, state, lat=None, lon=None) -> bool:
        """Permanent jobs must be in the target area (or unlocatable-but-CA, kept for review)."""
        tier = self.tier_for(city, state, lat, lon)
        if tier > 0:
            return True
        # Unknown city but California and no coordinates: keep for human review
        # rather than silently dropping a possible match.
        if city is None and (state is None or state.upper() == "CA") and lat is None:
            return True
        return False

    def in_scope_travel(self, city, state) -> bool:
        """Travel contracts: anywhere in the configured states (default: CA only)."""
        if state:
            return state.upper() in self.travel_states
        return True  # unknown state: keep for review
