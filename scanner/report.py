"""Outputs: new-jobs digest (markdown), dashboard (docs/index.html), CI summary."""
from __future__ import annotations

import html
import json
import os
from datetime import datetime, timezone
from typing import Dict, List

from .models import Job, CATEGORIES, CATEGORY_LABELS

DASH_PATH = os.path.join("docs", "index.html")
DIGEST_PATH = os.path.join("data", "new_jobs.md")


def _fmt_job_md(d: dict) -> str:
    bits = [f"**[{d['title']}]({d['url']})** — {d['company']}"]
    loc = d.get("location_raw") or "location unknown"
    line2 = [loc]
    if d.get("salary_raw"):
        line2.append(d["salary_raw"])
    if d.get("tags"):
        line2.append(" ".join(f"`{t}`" for t in d["tags"]))
    line2.append(f"score {d.get('score', 0)}")
    bits.append("  \n  " + " · ".join(line2))
    return "- " + "".join(bits)


def write_digest(new_jobs: List[Job], state: dict | None = None,
                 health: Dict[str, str] | None = None,
                 path: str = DIGEST_PATH) -> int:
    """Markdown digest of newly-seen jobs, grouped by category. Returns count."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not new_jobs:
        if os.path.exists(path):
            os.remove(path)
        return 0
    by_cat: Dict[str, List[dict]] = {c: [] for c in CATEGORIES}
    for j in new_jobs:
        by_cat.setdefault(j.category, []).append(j.to_dict())
    lines = []
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines.append(f"### {len(new_jobs)} new position(s) found — {date}\n")
    for cat in CATEGORIES:
        items = sorted(by_cat.get(cat, []), key=lambda d: -d.get("score", 0))
        if not items:
            continue
        lines.append(f"\n#### {CATEGORY_LABELS[cat]} ({len(items)})\n")
        lines.extend(_fmt_job_md(d) for d in items)
    # "New" is not "all": remind the reader what is still open, so a
    # travel-only alert never reads like the permanent market went dark.
    if state:
        active = [d for d in state["jobs"].values() if d.get("active")]
        perm = [d for d in active if d.get("category") != "travel"]
        n_pet = sum(1 for d in perm if d.get("category") == "outpatient-pet")
        lines.append(f"\n**Still open (not new, still apply-able):** "
                     f"{len(perm)} permanent ({n_pet} outpatient PET/CT) · "
                     f"{len(active) - len(perm)} travel — see the dashboard.")
    lines.extend(_key_warnings(health))
    lines.append("\n\n---\n_Open the dashboard (docs/index.html) for the full live list._\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return len(new_jobs)


def _key_warnings(health: Dict[str, str] | None) -> List[str]:
    if not health:
        return []
    missing = sorted(k for k, v in health.items() if "no API key" in v)
    if not missing:
        return []
    return [f"\n> ⚠️ **Coverage gap:** {', '.join(missing)} are switched off "
            f"(no API key configured), so postings that only appear on "
            f"Indeed/Google Jobs — e.g. small doctor-office jobs — are NOT "
            f"being scanned. Fix: README → 'add 2 free API keys'."]


def write_ci_summary(state: dict, new_jobs: List[Job], health: Dict[str, str]) -> None:
    """GitHub Actions step summary, if running in CI."""
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_file:
        return
    active = [d for d in state["jobs"].values() if d.get("active")]
    lines = ["## Workscanner run\n"]
    lines.extend(_key_warnings(health))
    lines.append(f"**Active listings:** {len(active)} · **New this run:** {len(new_jobs)}\n")
    lines.append("| Category | Active |")
    lines.append("|---|---|")
    for cat in CATEGORIES:
        n = sum(1 for d in active if d.get("category") == cat)
        lines.append(f"| {CATEGORY_LABELS[cat]} | {n} |")
    lines.append("\n### Source health\n")
    lines.append("| Source | Status |")
    lines.append("|---|---|")
    for sid, status in sorted(health.items()):
        emoji = "✅" if status.startswith("ok") else "❌"
        lines.append(f"| {sid} | {emoji} {status} |")
    if new_jobs:
        lines.append("\n### New jobs\n")
        for j in sorted(new_jobs, key=lambda x: -x.score):
            lines.append(_fmt_job_md(j.to_dict()))
    with open(summary_file, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def write_dashboard(state: dict, health: Dict[str, str], path: str = DASH_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    active = [d for d in state["jobs"].values() if d.get("active")]
    payload = {
        "updated": state.get("updated"),
        "jobs": sorted(active, key=lambda d: -d.get("score", 0)),
        "health": health,
        "categories": CATEGORIES,
        "labels": CATEGORY_LABELS,
    }
    doc = _TEMPLATE.replace("__DATA__", html.escape(json.dumps(payload), quote=False)
                            .replace("</", "<\\/"))
    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)


# The dashboard is a single self-contained page: works on GitHub Pages, or just
# opened locally. No external assets (loads fast on a phone).
_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NM/PET Job Scanner</title>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --text:#1a202c; --muted:#64748b; --accent:#0e7490;
          --new:#059669; --border:#e2e8f0; --chip:#eef2f7; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#0f141a; --card:#1a222c; --text:#e6edf3; --muted:#8b98a5; --accent:#22d3ee;
            --new:#34d399; --border:#2d3a48; --chip:#243040; }
  }
  * { box-sizing: border-box; }
  body { margin:0; font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
         background:var(--bg); color:var(--text); }
  header { padding:16px 16px 8px; max-width:900px; margin:0 auto; }
  h1 { font-size:1.25rem; margin:0 0 2px; }
  .sub { color:var(--muted); font-size:.85rem; }
  main { max-width:900px; margin:0 auto; padding:0 12px 60px; }
  .tabs { display:flex; gap:6px; flex-wrap:wrap; margin:12px 0; }
  .tabs button { border:1px solid var(--border); background:var(--card); color:var(--text);
    border-radius:999px; padding:7px 14px; font-size:.85rem; cursor:pointer; }
  .tabs button.on { background:var(--accent); border-color:var(--accent); color:#fff; }
  .filters { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; }
  .filters input, .filters select { border:1px solid var(--border); background:var(--card);
    color:var(--text); border-radius:8px; padding:8px 10px; font-size:.9rem; }
  .filters input { flex:1; min-width:160px; }
  .card { background:var(--card); border:1px solid var(--border); border-radius:12px;
          padding:12px 14px; margin-bottom:10px; }
  .card a.title { color:var(--accent); text-decoration:none; font-weight:600; font-size:1rem; }
  .card a.title:hover { text-decoration:underline; }
  .meta { color:var(--muted); font-size:.85rem; margin-top:3px; }
  .chips { margin-top:6px; display:flex; gap:6px; flex-wrap:wrap; }
  .chip { background:var(--chip); border-radius:6px; font-size:.72rem; padding:2px 8px; }
  .chip.new { background:var(--new); color:#fff; font-weight:700; }
  .chip.score { border:1px solid var(--border); background:transparent; }
  .empty { color:var(--muted); text-align:center; padding:40px 0; }
  .warnbar { background:#b45309; color:#fff; border-radius:10px; padding:10px 14px;
             font-size:.85rem; margin:4px 0 12px; display:none; }
  .warnbar a { color:#fff; }
  details.health { margin-top:24px; color:var(--muted); font-size:.85rem; }
  details.health td { padding:2px 10px 2px 0; }
</style>
</head>
<body>
<header>
  <h1>☢️ Nuclear Med / PET Job Scanner</h1>
  <div class="sub" id="updated"></div>
</header>
<main>
  <div class="warnbar" id="warnbar"></div>
  <div class="tabs" id="tabs"></div>
  <div class="filters">
    <input id="q" type="search" placeholder="Filter by city, employer, keyword…">
    <select id="sort">
      <option value="score">Best match first</option>
      <option value="new">Newest first</option>
    </select>
  </div>
  <div id="list"></div>
  <details class="health"><summary>Source health</summary><table id="health"></table></details>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const state = { cat: 'outpatient-pet', q: '', sort: 'score' };
const NEW_MS = 1000 * 60 * 60 * 48;

function isNew(j) {
  const t = Date.parse(j.first_seen || 0);
  return t && (Date.now() - t) < NEW_MS;
}
function counts() {
  const c = {};
  for (const j of DATA.jobs) c[j.category] = (c[j.category] || 0) + 1;
  return c;
}
function renderTabs() {
  const c = counts();
  const el = document.getElementById('tabs');
  el.innerHTML = '';
  const cats = ['outpatient-pet','outpatient-nm','hospital-other','travel'];
  for (const cat of cats) {
    const b = document.createElement('button');
    b.textContent = `${DATA.labels[cat]} (${c[cat] || 0})`;
    b.className = state.cat === cat ? 'on' : '';
    b.onclick = () => { state.cat = cat; render(); };
    el.appendChild(b);
  }
  const all = document.createElement('button');
  all.textContent = `All (${DATA.jobs.length})`;
  all.className = state.cat === 'all' ? 'on' : '';
  all.onclick = () => { state.cat = 'all'; render(); };
  el.appendChild(all);
}
function render() {
  renderTabs();
  const q = state.q.toLowerCase();
  let jobs = DATA.jobs.filter(j => state.cat === 'all' || j.category === state.cat);
  if (q) jobs = jobs.filter(j =>
    (j.title + ' ' + j.company + ' ' + (j.location_raw||'') + ' ' + (j.tags||[]).join(' '))
      .toLowerCase().includes(q));
  jobs.sort((a, b) => state.sort === 'new'
    ? (Date.parse(b.first_seen||0)||0) - (Date.parse(a.first_seen||0)||0)
    : (b.score||0) - (a.score||0));
  const list = document.getElementById('list');
  list.innerHTML = '';
  if (!jobs.length) {
    list.innerHTML = '<div class="empty">No listings in this category right now.</div>';
    return;
  }
  for (const j of jobs) {
    const card = document.createElement('div');
    card.className = 'card';
    const chips = [];
    if (isNew(j)) chips.push('<span class="chip new">NEW</span>');
    for (const t of (j.tags || [])) chips.push(`<span class="chip">${esc(t)}</span>`);
    chips.push(`<span class="chip score">score ${j.score||0}</span>`);
    const first = (j.first_seen || '').slice(0, 10);
    card.innerHTML = `
      <a class="title" href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a>
      <div class="meta">${esc(j.company)} · ${esc(j.location_raw || 'location unknown')}
        ${j.salary_raw ? ' · ' + esc(j.salary_raw) : ''}${first ? ' · first seen ' + first : ''}</div>
      <div class="chips">${chips.join('')}</div>`;
    list.appendChild(card);
  }
}
function esc(s) { return String(s ?? '').replace(/[&<>"']/g,
  m => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m])); }
document.getElementById('q').addEventListener('input', e => { state.q = e.target.value; render(); });
document.getElementById('sort').addEventListener('change', e => { state.sort = e.target.value; render(); });
document.getElementById('updated').textContent =
  'Updated ' + (DATA.updated ? new Date(DATA.updated).toLocaleString() : 'never') +
  ' · ' + DATA.jobs.length + ' active listings';
const ht = document.getElementById('health');
for (const [src, st] of Object.entries(DATA.health || {})) {
  ht.innerHTML += `<tr><td>${esc(src)}</td><td>${esc(st)}</td></tr>`;
}
const noKey = Object.entries(DATA.health || {})
  .filter(([, st]) => st.includes('no API key')).map(([src]) => src);
if (noKey.length) {
  const wb = document.getElementById('warnbar');
  wb.style.display = 'block';
  wb.textContent = '⚠️ ' + noKey.join(', ') + ' switched off (no API key) — '
    + 'Indeed/Google-only postings such as small doctor-office jobs are NOT '
    + 'being scanned. Fix: README → "add 2 free API keys".';
}
render();
</script>
</body>
</html>
"""
