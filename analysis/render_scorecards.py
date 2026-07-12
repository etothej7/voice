"""Render analysis/scorecards/*.json + ledger/*.json into a manager-facing page.

Three views in one static HTML file (hash routing):
  #/                    team roster - one card per rep, high-level metrics
  #/rep/<slug>          rep detail - criterion pass rates + their meetings
  #/call/<slug>         meeting detail - verdicts w/ evidence, coaching, buyers

Usage: python render_scorecards.py [output.html]   (default: scorecards.html here)
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "scorecards.html"

CRITERIA = [
    ("delivery_engagement", "Delivery & engagement"),
    ("value_prop_clarity", "Value prop clarity"),
    ("relevance", "Relevance"),
    ("discovery_progression", "Discovery & progression"),
]
config = json.loads((HERE / "sellers.json").read_text())
BASELINE_N = config.get("min_calls_for_baseline", 5)


def rep_slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def call_title(slug):
    m = re.match(r"(.+?)-(\d{4})-(\d{2})-(\d{2})", slug)
    if not m:
        return slug, ""
    name = m.group(1).replace("-", " ").title().replace(" Io", ".io").replace("Mode ", "MODE ")
    return name, f"{m.group(2)}-{m.group(3)}-{m.group(4)}"


calls = {}
for p in sorted(HERE.glob("scorecards/*.json")):
    sc = json.loads(p.read_text())
    title, date = call_title(sc["call"])
    calls[sc["call"]] = {**sc, "title": title, "date": date}

ledgers = {}
for p in HERE.glob("ledger/*.json"):
    led = json.loads(p.read_text())
    ledgers[led["rep"]] = led

reps = {}
for slug, sc in calls.items():
    for name, seller in sc.get("sellers", {}).items():
        r = reps.setdefault(name, {
            "name": name, "slug": rep_slug(name), "calls": [],
            "crit": {k: [0, 0] for k, _ in CRITERIA},
            "talk": [], "questions": [], "coaching": None, "coaching_call": None,
        })
        verdicts = {}
        for k, _ in CRITERIA:
            v = seller.get("criteria", {}).get(k, {}).get("verdict")
            verdicts[k] = v
            if v:
                r["crit"][k][1] += 1
                r["crit"][k][0] += (v == "pass")
        ac = sc.get("acoustics", {}).get(name, {})
        r["calls"].append({
            "call": slug, "title": sc["title"], "date": sc["date"],
            "verdicts": verdicts,
            "talk_share": ac.get("talk_share_pct"),
            "questions": ac.get("questions"),
            "buyers": {b: v.get("interest") for b, v in sc.get("buyers", {}).items()},
        })
        if ac.get("talk_share_pct") is not None:
            r["talk"].append(ac["talk_share_pct"])
        if ac.get("questions") is not None:
            r["questions"].append(ac["questions"])
        if sc["date"] >= (r["coaching_call"] or ""):
            r["coaching"] = seller.get("coaching_action")
            r["coaching_call"] = sc["date"]

for r in reps.values():
    r["calls"].sort(key=lambda c: c["date"], reverse=True)
    total = [sum(v[0] for v in r["crit"].values()), sum(v[1] for v in r["crit"].values())]
    r["pass_total"] = total
    r["avg_talk"] = round(sum(r["talk"]) / len(r["talk"]), 1) if r["talk"] else None
    r["avg_questions"] = round(sum(r["questions"]) / len(r["questions"]), 1) if r["questions"] else None
    base = ledgers.get(r["name"], {}).get("baseline", {})
    r["baseline_n"] = base.get("n_calls", len(r["calls"]))
    r["baseline_active"] = bool(base.get("active"))

# team insight: weakest criterion if <=50% pass
team_insight = None
rates = {k: [0, 0] for k, _ in CRITERIA}
for r in reps.values():
    for k, _ in CRITERIA:
        rates[k][0] += r["crit"][k][0]
        rates[k][1] += r["crit"][k][1]
worst_k, (wp, wt) = min(rates.items(), key=lambda kv: (kv[1][0] / kv[1][1]) if kv[1][1] else 1)
if wt and wp / wt <= 0.5:
    team_insight = f"{wp} of {wt} gradings passed {dict(CRITERIA)[worst_k]} — the team's biggest open coaching area."

DATA = {
    "criteria": CRITERIA,
    "baselineN": BASELINE_N,
    "reps": {r["slug"]: r for r in reps.values()},
    "calls": calls,
    "teamInsight": team_insight,
}

page = """<title>Rep Performance</title>
<style>
  :root {
    --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
    --grid:#e1e0d9; --border:rgba(11,11,11,.10);
    --good:#006300; --good-bg:#e9f3e9; --warn:#8a4a00; --warn-bg:#fdf3e2;
    --accent:#2a78d6; --accent-bg:#e9f1fb;
  }
  @media (prefers-color-scheme: dark) { :root {
    --page:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --border:rgba(255,255,255,.10);
    --good:#7fce7f; --good-bg:#12290f; --warn:#f0b064; --warn-bg:#2b2010;
    --accent:#3987e5; --accent-bg:#12233a;
  } }
  :root[data-theme="dark"] {
    --page:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --border:rgba(255,255,255,.10);
    --good:#7fce7f; --good-bg:#12290f; --warn:#f0b064; --warn-bg:#2b2010;
    --accent:#3987e5; --accent-bg:#12233a;
  }
  :root[data-theme="light"] {
    --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
    --grid:#e1e0d9; --border:rgba(11,11,11,.10);
    --good:#006300; --good-bg:#e9f3e9; --warn:#8a4a00; --warn-bg:#fdf3e2;
    --accent:#2a78d6; --accent-bg:#e9f1fb;
  }
  * { box-sizing:border-box; }
  html { background:var(--page); }
  body { margin:0; background:var(--page); color:var(--ink);
         font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif; }
  .wrap { max-width:1040px; margin:0 auto; padding:34px 22px 72px; }
  a { color:inherit; text-decoration:none; }
  .crumb { font-size:13px; color:var(--muted); margin-bottom:14px; }
  .crumb a { color:var(--accent); }
  .crumb a:hover { text-decoration:underline; }
  h1 { font-size:26px; margin:0 0 4px; letter-spacing:-.015em; }
  .subline { color:var(--muted); font-size:13.5px; margin:0 0 22px; }
  .insight { border:1px solid var(--border); border-left:3px solid var(--accent);
             background:var(--surface); border-radius:6px; padding:11px 16px;
             font-size:14px; color:var(--ink2); margin-bottom:22px; }
  .tablewrap { background:var(--surface); border:1px solid var(--border); border-radius:10px;
               overflow-x:auto; }
  table { border-collapse:collapse; width:100%; font-size:13.5px; }
  th, td { padding:10px 14px; text-align:right; white-space:nowrap; }
  th:first-child, td:first-child { text-align:left; }
  thead th { font-family:ui-monospace,Menlo,monospace; font-size:10.5px; letter-spacing:.08em;
             text-transform:uppercase; font-weight:500; color:var(--muted);
             border-bottom:1px solid var(--grid); cursor:pointer; user-select:none; }
  thead th:hover { color:var(--ink); }
  thead th .arrow { font-size:9px; margin-left:3px; }
  tbody tr { cursor:pointer; }
  tbody tr:hover { background:var(--page); }
  tbody tr + tr td { border-top:1px solid var(--grid); }
  td.num { font-family:ui-monospace,Menlo,monospace; font-variant-numeric:tabular-nums; }
  td .repname { font-weight:600; font-size:14px; color:var(--ink); }
  .scorecell { display:inline-flex; align-items:center; gap:8px; }
  .crfrac { font-family:ui-monospace,Menlo,monospace; font-variant-numeric:tabular-nums; }
  .cr-good { color:var(--good); }
  .cr-bad { color:var(--warn); }
  .critrows { display:flex; flex-direction:column; gap:7px; }
  .critrow { display:grid; grid-template-columns:1fr 84px 34px; align-items:center; gap:10px;
             font-size:12.5px; color:var(--ink2); }
  .bar { height:5px; border-radius:3px; background:var(--grid); overflow:hidden; }
  .bar i { display:block; height:100%; background:var(--good); border-radius:3px; }
  .bar i.low { background:var(--warn); }
  .fract { font-family:ui-monospace,Menlo,monospace; font-size:11px; color:var(--muted);
           text-align:right; }
  .focus { margin-top:14px; padding-top:12px; border-top:1px solid var(--grid);
           font-size:12.5px; color:var(--ink2); }
  .focus b { display:block; font-size:10.5px; letter-spacing:.1em; text-transform:uppercase;
             color:var(--accent); font-weight:600; margin-bottom:2px; }
  .chip { display:inline-block; font-size:11.5px; font-weight:600; border-radius:99px;
          padding:2px 10px; white-space:nowrap; }
  .chip.pass { color:var(--good); background:var(--good-bg); }
  .chip.needs { color:var(--warn); background:var(--warn-bg); }
  .chip.int-strong { color:var(--good); background:var(--good-bg); }
  .chip.int-moderate { color:var(--warn); background:var(--warn-bg); }
  .chip.int-weak { color:var(--muted); background:var(--page); border:1px solid var(--grid); }
  .chip.base { color:var(--muted); background:var(--page); border:1px solid var(--grid);
               font-weight:500; }
  .tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:12px;
           margin-bottom:22px; }
  .tile { background:var(--surface); border:1px solid var(--border); border-radius:8px;
          padding:12px 14px; }
  .tile .v { font-size:22px; font-weight:650; }
  .tile .v small { font-size:12px; font-weight:400; color:var(--muted); }
  .tile .l { font-size:11.5px; color:var(--muted); margin-top:1px; }
  .panel { background:var(--surface); border:1px solid var(--border); border-radius:10px;
           padding:18px 20px; margin-bottom:16px; }
  .panel h3 { font-size:13px; letter-spacing:.1em; text-transform:uppercase;
              color:var(--muted); font-weight:600; margin:0 0 12px; }
  .meeting { display:flex; flex-wrap:wrap; align-items:center; gap:8px 14px;
             padding:12px 4px; border-top:1px solid var(--grid); }
  .meeting:first-of-type { border-top:none; }
  .meeting:hover .mtitle { color:var(--accent); }
  .mtitle { font-weight:600; font-size:14.5px; }
  .mdate { font-family:ui-monospace,Menlo,monospace; font-size:11.5px; color:var(--muted); }
  .mchips { display:flex; gap:5px; flex-wrap:wrap; margin-left:auto; }
  .dot { width:9px; height:9px; border-radius:3px; display:inline-block; }
  .dot.pass { background:var(--good); }
  .dot.needs { background:var(--warn); }
  .summary { color:var(--ink2); font-size:14px; margin:8px 0 18px; }
  .seller { border-top:1px solid var(--grid); padding-top:16px; margin-top:14px; }
  .seller h3 { font-size:15px; margin:0 0 12px; letter-spacing:0; text-transform:none;
               color:var(--ink); }
  .stats { font-family:ui-monospace,Menlo,monospace; font-size:11px; color:var(--muted);
           font-weight:400; margin-left:8px; }
  .crits { display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:14px; }
  .crit { border:1px solid var(--grid); border-radius:8px; padding:12px 14px; }
  .crithead { display:flex; justify-content:space-between; align-items:center; gap:8px;
              margin-bottom:6px; }
  .critname { font-weight:600; font-size:13.5px; }
  .crit p { margin:0 0 8px; font-size:13px; color:var(--ink2); }
  blockquote { margin:6px 0 0; font-size:12.5px; color:var(--ink2);
               border-left:2px solid var(--grid); padding:2px 0 2px 10px; font-style:italic; }
  .ts { font-family:ui-monospace,Menlo,monospace; font-style:normal; font-size:10.5px;
        color:var(--muted); margin-right:7px; }
  .coach { margin-top:14px; background:var(--page); border:1px solid var(--border);
           border-left:3px solid var(--accent); border-radius:6px; padding:10px 14px;
           font-size:13.5px; }
  .coach b { display:block; font-family:ui-monospace,Menlo,monospace; font-size:10px;
             letter-spacing:.12em; text-transform:uppercase; color:var(--accent);
             margin-bottom:3px; font-weight:600; }
  .buyerpanel ul { margin:0; padding:0; list-style:none; display:grid;
                   grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:10px 14px; }
  .buyerpanel li { font-size:13px; color:var(--ink2); }
  .buyerpanel li b { color:var(--ink); font-weight:600; }
</style>
<div class="wrap"><div id="app"></div></div>
<script>
const DATA = __DATA__;
const CRIT = DATA.criteria;
const el = (s) => { const d = document.createElement("div"); d.textContent = s ?? ""; return d.innerHTML; };
const INT = {strong: "Strong interest", moderate: "Moderate interest", weak: "Weak interest"};

function chip(verdict) {
  return verdict === "pass"
    ? '<span class="chip pass">✓ Pass</span>'
    : '<span class="chip needs">△ Needs improvement</span>';
}
function intChip(level) {
  return `<span class="chip int-${el(level)}">${el(INT[level] || level)}</span>`;
}
function bar(p, t) {
  const pct = t ? Math.round(100 * p / t) : 0;
  return `<span class="bar"><i class="${pct < 60 ? "low" : ""}" style="width:${pct}%"></i></span>
          <span class="fract">${p}/${t}</span>`;
}
function evidence(items) {
  return (items || []).slice(0, 2).map(e =>
    `<blockquote><span class="ts">${el(e.timestamp)}</span>&ldquo;${el(e.quote)}&rdquo;</blockquote>`).join("");
}

let sortKey = "score", sortDir = -1;

const COLS = [
  { key: "name",  label: "Rep",        get: r => r.name },
  { key: "calls", label: "Calls",      get: r => r.calls.length },
  { key: "score", label: "Score",      get: r => r.pass_total[1] ? r.pass_total[0] / r.pass_total[1] : -1 },
  ...CRIT.map(([k, label]) => ({
    key: k, full: label,
    label: ({delivery_engagement: "Delivery", value_prop_clarity: "Value prop",
             relevance: "Relevance", discovery_progression: "Discovery"})[k] || label,
    get: r => r.crit[k][1] ? r.crit[k][0] / r.crit[k][1] : -1,
  })),
  { key: "talk",  label: "Talk %",     get: r => r.avg_talk ?? -1 },
  { key: "quest", label: "Questions",  get: r => r.avg_questions ?? -1 },
  { key: "base",  label: "Baseline",   get: r => r.baseline_active ? 999 : r.baseline_n },
];

function critCell(p, t) {
  if (!t) return '<span class="crfrac">–</span>';
  const cls = p === t ? "cr-good" : (p / t < 0.5 ? "cr-bad" : "");
  return `<span class="crfrac ${cls}">${p}/${t}</span>`;
}

function teamView() {
  const col = COLS.find(c => c.key === sortKey) || COLS[2];
  const reps = Object.values(DATA.reps).sort((a, b) => {
    const va = col.get(a), vb = col.get(b);
    return (typeof va === "string" ? va.localeCompare(vb) : va - vb) * sortDir;
  });
  let h = `<h1>Team</h1>
    <p class="subline">${reps.length} reps · ${Object.keys(DATA.calls).length} scored calls</p>`;
  if (DATA.teamInsight) h += `<div class="insight">${el(DATA.teamInsight)}</div>`;
  h += `<div class="tablewrap"><table><thead><tr>` +
    COLS.map(c => `<th data-sort="${c.key}" title="${el(c.full || c.label)}">${el(c.label)}` +
      (c.key === sortKey ? `<span class="arrow">${sortDir < 0 ? "▼" : "▲"}</span>` : "") +
      `</th>`).join("") +
    `</tr></thead><tbody>`;
  for (const r of reps) {
    const [p, t] = r.pass_total;
    const base = r.baseline_active
      ? '<span class="chip base">active</span>'
      : `<span class="chip base">${r.baseline_n}/${DATA.baselineN}</span>`;
    h += `<tr data-rep="${r.slug}">
      <td><span class="repname">${el(r.name)}</span></td>
      <td class="num">${r.calls.length}</td>
      <td class="num"><span class="scorecell">${t ? Math.round(100 * p / t) + "%" : "–"}<span class="bar" style="width:56px"><i class="${t && p / t < 0.6 ? "low" : ""}" style="width:${t ? Math.round(100 * p / t) : 0}%"></i></span></span></td>` +
      CRIT.map(([k]) => `<td class="num">${critCell(r.crit[k][0], r.crit[k][1])}</td>`).join("") +
      `<td class="num">${r.avg_talk ?? "–"}</td>
      <td class="num">${r.avg_questions ?? "–"}</td>
      <td>${base}</td></tr>`;
  }
  h += "</tbody></table></div>";
  setTimeout(() => {
    document.querySelectorAll("tbody tr[data-rep]").forEach(tr =>
      tr.addEventListener("click", () => { location.hash = `#/rep/${tr.dataset.rep}`; }));
    document.querySelectorAll("thead th[data-sort]").forEach(th =>
      th.addEventListener("click", () => {
        const k = th.dataset.sort;
        if (sortKey === k) sortDir = -sortDir; else { sortKey = k; sortDir = -1; }
        route();
      }));
  }, 0);
  return h;
}

function repView(slug) {
  const r = DATA.reps[slug];
  if (!r) return teamView();
  const [p, t] = r.pass_total;
  let h = `<div class="crumb"><a href="#/">Team</a> / ${el(r.name)}</div>
    <h1>${el(r.name)}</h1>
    <p class="subline">${r.calls.length} scored call${r.calls.length !== 1 ? "s" : ""} ·
      baseline ${r.baseline_active ? "active" : `${r.baseline_n} of ${DATA.baselineN} calls`}</p>
    <div class="tiles">
      <div class="tile"><div class="v">${t ? Math.round(100 * p / t) : "–"}<small>%</small></div><div class="l">criteria passed</div></div>
      <div class="tile"><div class="v">${r.avg_talk ?? "–"}<small>%</small></div><div class="l">avg talk share</div></div>
      <div class="tile"><div class="v">${r.avg_questions ?? "–"}</div><div class="l">questions / call</div></div>
      <div class="tile"><div class="v">${r.calls.length}</div><div class="l">calls scored</div></div>
    </div>
    <div class="panel"><h3>Criteria</h3><div class="critrows">` +
    CRIT.map(([k, label]) =>
      `<div class="critrow"><span>${label}</span>${bar(r.crit[k][0], r.crit[k][1])}</div>`).join("") +
    `</div></div>`;
  if (r.coaching) h += `<div class="coach"><b>Current coaching focus</b>${el(r.coaching)}</div><br>`;
  h += `<div class="panel"><h3>Meetings</h3>`;
  for (const c of r.calls) {
    const buyers = Object.entries(c.buyers).map(([n, i]) => `${el(n)} ${intChip(i)}`).join(" ");
    h += `<a class="meeting" href="#/call/${c.call}?rep=${slug}">
      <span class="mdate">${c.date}</span><span class="mtitle">${el(c.title)}</span>
      <span>${buyers}</span>
      <span class="mchips">` +
      CRIT.map(([k]) => `<span class="dot ${c.verdicts[k] === "pass" ? "pass" : "needs"}" title="${dictLabel(k)}"></span>`).join("") +
      `</span></a>`;
  }
  return h + "</div>";
}

function dictLabel(k) { return (CRIT.find(c => c[0] === k) || ["", k])[1]; }

function callView(slug, focusRep) {
  const c = DATA.calls[slug];
  if (!c) return teamView();
  const crumbRep = focusRep && DATA.reps[focusRep]
    ? ` / <a href="#/rep/${focusRep}">${el(DATA.reps[focusRep].name)}</a>` : "";
  let h = `<div class="crumb"><a href="#/">Team</a>${crumbRep} / ${el(c.title)}</div>
    <h1>${el(c.title)}</h1>
    <p class="subline">${c.date} · ${Object.entries(c.buyers || {}).map(([n, b]) =>
      `${el(n)} ${intChip(b.interest)}`).join(" · ")}</p>
    <p class="summary">${el(c.call_summary)}</p>`;
  const names = Object.keys(c.sellers || {});
  if (focusRep) names.sort((a, b) => (DATA.reps[focusRep]?.name === a ? -1 : DATA.reps[focusRep]?.name === b ? 1 : 0));
  for (const name of names) {
    const s = c.sellers[name];
    const ac = (c.acoustics || {})[name] || {};
    h += `<div class="seller"><h3>${el(name)}<span class="stats">${ac.talk_share_pct ?? "–"}% talk share ·
      ${ac.questions ?? "–"} questions · pitch var ${ac.f0_std_semitones ?? "–"} st ·
      pace ${ac.pace_peaks_per_sec ?? "–"}/s</span></h3><div class="crits">` +
      CRIT.map(([k, label]) => {
        const cr = (s.criteria || {})[k] || {};
        return `<div class="crit"><div class="crithead"><span class="critname">${label}</span>${chip(cr.verdict)}</div>
          <p>${el(cr.explanation)}</p>${evidence(cr.evidence)}</div>`;
      }).join("") +
      `</div><div class="coach"><b>Coaching action</b>${el(s.coaching_action)}</div></div>`;
  }
  for (const [bname, b] of Object.entries(c.buyers || {})) {
    h += `<div class="seller buyerpanel"><h3>${el(bname)} — buyer signals</h3><ul>` +
      (b.signals || []).map(s =>
        `<li><b>${el(s.signal)}</b><blockquote><span class="ts">${el(s.timestamp)}</span>&ldquo;${el(s.quote)}&rdquo;</blockquote></li>`).join("") +
      "</ul></div>";
  }
  return h;
}

function route() {
  const hash = location.hash || "#/";
  let m;
  let html;
  if ((m = hash.match(/^#\\/rep\\/([a-z0-9-]+)/))) html = repView(m[1]);
  else if ((m = hash.match(/^#\\/call\\/([a-z0-9-]+?)(?:\\?rep=([a-z0-9-]+))?$/))) html = callView(m[1], m[2]);
  else html = teamView();
  document.getElementById("app").innerHTML = html;
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", route);
route();
</script>
"""

OUT.write_text(page.replace("__DATA__", json.dumps(DATA)))
print(f"wrote {OUT} ({len(reps)} reps, {len(calls)} calls)")
