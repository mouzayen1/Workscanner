# ☢️ Workscanner — Nuclear Medicine / PET-CT Job Scanner

A robot that checks **dozens of job sources twice a day** for Nuclear Medicine
Technologist and PET/CT Technologist openings in your target area (Orange
County + Chino/Chino Hills/Corona), ranks them by how well they match what you
want (**outpatient · PET/CT · close to home**), and tells you the moment
something new appears.

You don't run anything by hand. GitHub runs it for you, for free, on a schedule.

## How you use it (the short version)

1. **Watch this repo** (button top-right on GitHub → Watch → *All activity*).
   Every time the scanner finds new jobs it opens an Issue titled
   "🆕 N new NM/PET job(s) found" — GitHub emails it to you automatically.
2. **Open the dashboard** — the file `docs/index.html` in this repo, updated
   after every scan. Enable GitHub Pages (repo **Settings → Pages → Deploy from
   branch → `/docs` folder**) and it becomes a website you can bookmark on your
   phone. Tabs: **Outpatient PET/CT** (your target), Outpatient Nuclear Med,
   Hospital/Other, and **Travel/Contract** (kept separate, as requested).
3. That's it. Check the issue emails over coffee; open the dashboard when you
   want the full picture.

## What it scans

**Direct employer career sites** (checked every run, no keys needed — all
verified live and returning real postings):

| Employer | Why it matters |
|---|---|
| RadNet / WaveImaging | Biggest outpatient imaging chain in SoCal; PET/CT in Orange, Santa Ana, Newport Beach. Live "Nuclear Medicine/PET Technologist" postings found on the first scan. |
| SimonMed Imaging | Pure outpatient chain — Irvine & Santa Ana centers with NM + PET/CT |
| City of Hope Orange County | Outpatient cancer center in Irvine — heavy PET/molecular imaging, "new grads welcome," sign-on bonuses |
| MemorialCare | Orange Coast (Fountain Valley) + Saddleback (Laguna Hills) + Long Beach + imaging centers |
| Providence | Mission Viejo, Orange, Fullerton hospitals + Heritage medical-group nuclear cardiology |
| Kaiser Permanente | Many NM roles sit in outpatient medical office buildings (Anaheim, Irvine, Ontario, Riverside) |
| PIH Health | Whittier/Downey — commutable from Chino Hills/Brea |
| UHS | Corona Regional Medical Center (found its live Corona NM openings on the first scan) |

**Travel/contract** (separate category): Vivian Health — which aggregates
LanceSoft, Host Healthcare, Cross Country, TotalMed, Triage, Stability and
more — plus Aya's own board. The first live scans already surfaced contracts
in **Orange, Irvine, Los Alamitos, and Upland** at travel rates.

**Aggregator APIs** (optional, free keys — see below): cover everything else —
cardiology offices doing nuclear stress tests (e.g. Pacific Cardiovascular
Associates), mobile PET companies (Akumin, Shared Imaging, Digirad), Hoag,
UCI, Prime/Chino Valley, Loma Linda, San Antonio Regional (Upland), Pomona
Valley, and brand-new postings anywhere.

**Four sites block automated readers** (their career portals reject
non-browser traffic). Their postings still reach you through the aggregator
APIs above, but they're worth a quick manual look every week or two:

- Hoag: <https://careers.hoag.org/search-jobs/> (search "nuclear")
- UCI Health: <https://careersucirvine.ttcportals.com/search/jobs>
- Prime Healthcare (Chino Valley MC): <https://careers-primehealthcare.icims.com/jobs/search?ss=1&searchKeyword=nuclear>
- SNMMI Career Center: <https://careercenter.snmmi.org/jobs/> · ASRT: <https://careers.asrt.org/jobs/>

## Optional but recommended: add 2 free API keys (10 minutes)

The scanner works without any keys, but two free signups widen the net a lot:

1. **Adzuna** (best free job API): sign up at
   <https://developer.adzuna.com/signup> → you get an *App ID* and *App Key*.
2. **JSearch** (Google's job index — legitimately sees Indeed/LinkedIn
   postings): sign up at <https://rapidapi.com>, subscribe to the free plan of
   "JSearch", copy your RapidAPI key.

Then in this repo: **Settings → Secrets and variables → Actions → New
repository secret**, and add:

| Secret name | Value |
|---|---|
| `ADZUNA_APP_ID` | from Adzuna dashboard |
| `ADZUNA_APP_KEY` | from Adzuna dashboard |
| `RAPIDAPI_KEY` | from RapidAPI |
| `JOOBLE_KEY` | (optional) free key from <https://jooble.org/api/about> |
| `USAJOBS_KEY` / `USAJOBS_EMAIL` | (optional) from <https://developer.usajobs.gov> — VA outpatient clinics |

The next scheduled run picks them up automatically.

## Why this design (and not "just scrape Indeed")

- Indeed shut down its public API in 2023; LinkedIn and ZipRecruiter have no
  public job-search APIs and aggressively block scrapers. Chasing them with a
  scraper breaks weekly. The **compliant workaround** is Google's job index
  (JSearch) — employers push their postings there on purpose.
- **Direct employer career sites are the freshest, most reliable source** —
  a posting appears there first, before any job board, and the sites serve
  clean JSON your scanner reads politely (a handful of requests, twice a day).
- The couple of manual alerts worth setting anyway: an Indeed email alert for
  `"nuclear medicine" OR "PET/CT"` near Corona + one near Costa Mesa, and a
  Vivian account with alerts on. Belt and suspenders.

## How it decides what's a match

Each posting is scored 0–100 and categorized:

- **+25** PET/CT mentioned · **+20** outpatient signals ("outpatient",
  "imaging center", "clinic", "physician office", "no call/no weekends")
- **−points** for inpatient signals (on-call, weekend rotation, trauma, nights)
- **+15** in a target city (all of OC + Chino/Chino Hills/Corona/Eastvale/
  Norco) · **+8** nearby (Ontario, Upland, Riverside, Long Beach, …)
- Travel/contract postings are detected (travel agency source, "13 weeks",
  "contract", agency names) and routed to their own category — never mixed
  in with permanent jobs.

Tune anything in `config/search.yml` (cities, radius) and
`config/sources.yml` (employers, search terms).

## Schedule

Twice a day — ~6:30 AM and ~3:30 PM Pacific (`.github/workflows/scan.yml`).
Jobs that disappear from an employer's site for 2 consecutive scans are marked
filled and drop off the dashboard.

You can also trigger a scan any time: **Actions → Scan for jobs → Run
workflow**.

## Running locally (optional)

```bash
pip install -r requirements.txt
python -m scanner.main scan --verbose   # full scan, writes data/ + docs/
python -m scanner.main probe            # just check each source works
python -m scanner.main render           # rebuild dashboard from saved data
```

## Repo map

```
config/search.yml        your cities, radius, travel-state filter
config/sources.yml       every source the scanner checks
scanner/                 the Python package (sources/, scoring, state, reports)
data/jobs.json           current known listings (committed by the bot)
data/new_jobs.md         digest of the latest batch of new listings
docs/index.html          the dashboard (GitHub Pages-ready)
.github/workflows/scan.yml   the twice-daily schedule
```
