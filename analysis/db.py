"""SQLite store for every raw data point the pipeline produces.

One row per fact, so patterns can be found with plain SQL instead of
re-parsing JSON: per-speaker acoustics + emotion, all 88 eGeMAPS
functionals (long format), criterion verdicts keyed by rubric version
(so v2 and v3 scores of the same call can sit side by side), evidence
quotes, buyer interest + signals, and coaching actions.

The JSON files in scorecards/ and features/ remain the source of truth;
the DB is derived and can always be rebuilt from them.

Usage:
  python db.py rebuild            # wipe + reload from scorecards/ + features/
  python db.py query "SELECT ..." # run ad-hoc SQL, prints rows
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).parent
DB_PATH = HERE / "voice.db"

_cfg = json.loads((HERE / "sellers.json").read_text())
SELLERS = set(_cfg["sellers"])
TEAM = set(_cfg.get("team", []))

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
  slug TEXT PRIMARY KEY,
  title TEXT,
  date TEXT,
  summary TEXT,
  rubric_version TEXT,
  recording TEXT,
  notes TEXT
);
CREATE TABLE IF NOT EXISTS speakers (
  call_slug TEXT NOT NULL,
  name TEXT NOT NULL,
  role TEXT NOT NULL,              -- seller | buyer | team
  words INTEGER, questions INTEGER, speech_min REAL, talk_share_pct REAL,
  loudness_mean REAL, loudness_cv REAL, f0_std_semitones REAL,
  pace_peaks_per_sec REAL,
  arousal REAL, valence REAL, dominance REAL, seconds_analyzed REAL,
  arousal_third1 REAL, arousal_third2 REAL, arousal_third3 REAL,
  PRIMARY KEY (call_slug, name)
);
CREATE TABLE IF NOT EXISTS functionals (
  call_slug TEXT NOT NULL,
  speaker TEXT NOT NULL,
  feature TEXT NOT NULL,
  value REAL,
  PRIMARY KEY (call_slug, speaker, feature)
);
CREATE TABLE IF NOT EXISTS gradings (
  call_slug TEXT NOT NULL,
  seller TEXT NOT NULL,
  criterion TEXT NOT NULL,
  rubric_version TEXT NOT NULL,
  verdict TEXT,
  explanation TEXT,
  PRIMARY KEY (call_slug, seller, criterion, rubric_version)
);
CREATE TABLE IF NOT EXISTS evidence (
  call_slug TEXT NOT NULL,
  seller TEXT NOT NULL,
  criterion TEXT NOT NULL,
  rubric_version TEXT NOT NULL,
  ts TEXT,
  quote TEXT
);
CREATE TABLE IF NOT EXISTS buyers (
  call_slug TEXT NOT NULL,
  name TEXT NOT NULL,
  interest TEXT,
  PRIMARY KEY (call_slug, name)
);
CREATE TABLE IF NOT EXISTS buyer_signals (
  call_slug TEXT NOT NULL,
  buyer TEXT NOT NULL,
  signal TEXT,
  ts TEXT,
  quote TEXT
);
CREATE TABLE IF NOT EXISTS coaching (
  call_slug TEXT NOT NULL,
  seller TEXT NOT NULL,
  rubric_version TEXT NOT NULL,
  action TEXT,
  PRIMARY KEY (call_slug, seller, rubric_version)
);
CREATE TABLE IF NOT EXISTS turns (
  call_slug TEXT NOT NULL,
  idx INTEGER NOT NULL,
  speaker TEXT NOT NULL,
  t0 REAL,                         -- estimated seconds from call start
  t1 REAL,
  text TEXT,
  PRIMARY KEY (call_slug, idx)
);
CREATE TABLE IF NOT EXISTS hs_calls (
  call_id INTEGER PRIMARY KEY,     -- HubSpot engagement id
  title TEXT,
  ts TEXT,                         -- when the call happened
  duration_ms INTEGER,
  direction TEXT,
  disposition TEXT,
  disposition_label TEXT,
  status TEXT,
  recording_url TEXT,
  recording_path TEXT,             -- set once the wav is downloaded locally
  body TEXT,                       -- notes logged on the call
  owner_id INTEGER,
  owner_name TEXT
);
CREATE TABLE IF NOT EXISTS hs_meetings (
  meeting_id INTEGER PRIMARY KEY,
  title TEXT,
  start_time TEXT,
  outcome TEXT,
  body TEXT,
  owner_id INTEGER,
  owner_name TEXT
);
CREATE TABLE IF NOT EXISTS ext_calls (
  org_id INTEGER NOT NULL,         -- customer org (multi-tenant samples)
  org_name TEXT,
  call_id TEXT NOT NULL,           -- customer-portal engagement id
  title TEXT, ts TEXT, duration_ms INTEGER, direction TEXT,
  disposition TEXT, status TEXT,
  from_number TEXT, to_number TEXT,
  recording_path TEXT,
  PRIMARY KEY (org_id, call_id)
);
CREATE TABLE IF NOT EXISTS ext_turns (
  org_id INTEGER NOT NULL,
  call_id TEXT NOT NULL,
  idx INTEGER NOT NULL,
  role TEXT,                       -- rep | counterpart (from stereo channel)
  t0 REAL, t1 REAL,
  text TEXT,
  PRIMARY KEY (org_id, call_id, idx)
);
CREATE TABLE IF NOT EXISTS cold_engagement (
  call_id INTEGER PRIMARY KEY,     -- hs_calls.call_id
  arousal REAL, valence REAL, dominance REAL,
  f0_std_semitones REAL, pace_peaks_per_sec REAL, loudness_cv REAL,
  rep_share REAL,                  -- fraction of segments attributed to the rep
  rep_seconds REAL,
  rep_similarity REAL              -- mean cosine vs rep voice-print (confidence)
);
CREATE TABLE IF NOT EXISTS cold_scorecards (
  call_id INTEGER PRIMARY KEY,     -- hs_calls.call_id
  rubric_version TEXT,
  receptivity TEXT,                -- prospect: warm | neutral | hostile
  coaching TEXT,
  json TEXT                        -- full judge output (criteria, evidence)
);
CREATE TABLE IF NOT EXISTS cold_transcripts (
  call_id INTEGER PRIMARY KEY,     -- hs_calls.call_id
  model TEXT,                      -- whisper model used
  text TEXT,                       -- full transcript
  segments TEXT                    -- JSON [{start, end, text}, ...]
);
CREATE TABLE IF NOT EXISTS deals (
  deal_id INTEGER PRIMARY KEY,     -- HubSpot deal id
  name TEXT,
  stage TEXT,                      -- HubSpot internal stage value
  stage_label TEXT,
  stage_rank INTEGER,              -- 0=lost .. 6=won (Trial=3, Paying=6)
  pipeline TEXT,
  created TEXT,
  closed TEXT
);
CREATE TABLE IF NOT EXISTS call_deals (
  call_slug TEXT NOT NULL,
  deal_id INTEGER NOT NULL,
  method TEXT,                     -- how the match was made (title-token | manual)
  PRIMARY KEY (call_slug, deal_id)
);
CREATE VIEW IF NOT EXISTS pass_rates AS
  SELECT seller, criterion, rubric_version,
         SUM(verdict = 'pass') AS passed, COUNT(*) AS total,
         ROUND(1.0 * SUM(verdict = 'pass') / COUNT(*), 3) AS rate
  FROM gradings GROUP BY seller, criterion, rubric_version;
"""


def connect():
    con = sqlite3.connect(DB_PATH, timeout=60)
    con.execute("PRAGMA journal_mode=WAL")  # safe concurrent readers + writer
    con.executescript(SCHEMA)
    return con


def call_meta(slug):
    m = re.match(r"(.+?)-(\d{4}-\d{2}-\d{2})", slug)
    if not m:
        return slug, None
    title = m.group(1).replace("-", " ").title()
    return title, m.group(2)


def role_of(name):
    if name in SELLERS:
        return "seller"
    if name in TEAM:
        return "team"
    return "buyer"


def upsert_call(scorecard, functionals=None, con=None):
    """Insert/replace every fact from one scorecard (+ optional 88-functional
    capture). Gradings are keyed by rubric_version, so re-scoring under a new
    rubric adds rows instead of overwriting the old ones."""
    own = con is None
    if own:
        con = connect()
    slug = scorecard["call"]
    rv = scorecard.get("rubric_version", "?")
    title, date = call_meta(slug)
    src = scorecard.get("source", {})

    con.execute(
        "INSERT OR REPLACE INTO calls VALUES (?,?,?,?,?,?,?)",
        (slug, title, date, scorecard.get("call_summary"), rv,
         src.get("recording"), src.get("notes")))

    for name, a in (scorecard.get("acoustics") or {}).items():
        thirds = (a.get("arousal_thirds") or [None, None, None]) + [None] * 3
        con.execute(
            "INSERT OR REPLACE INTO speakers VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (slug, name, role_of(name), a.get("words"), a.get("questions"),
             a.get("speech_min"), a.get("talk_share_pct"),
             a.get("loudness_mean"), a.get("loudness_cv"),
             a.get("f0_std_semitones"), a.get("pace_peaks_per_sec"),
             a.get("arousal"), a.get("valence"), a.get("dominance"),
             a.get("seconds_analyzed"), thirds[0], thirds[1], thirds[2]))

    con.execute("DELETE FROM evidence WHERE call_slug=? AND rubric_version=?",
                (slug, rv))
    for seller, s in (scorecard.get("sellers") or {}).items():
        for crit, r in (s.get("criteria") or {}).items():
            con.execute(
                "INSERT OR REPLACE INTO gradings VALUES (?,?,?,?,?,?)",
                (slug, seller, crit, rv, r.get("verdict"), r.get("explanation")))
            for ev in r.get("evidence") or []:
                con.execute("INSERT INTO evidence VALUES (?,?,?,?,?,?)",
                            (slug, seller, crit, rv,
                             ev.get("timestamp"), ev.get("quote")))
        if s.get("coaching_action"):
            con.execute("INSERT OR REPLACE INTO coaching VALUES (?,?,?,?)",
                        (slug, seller, rv, s["coaching_action"]))

    con.execute("DELETE FROM buyer_signals WHERE call_slug=?", (slug,))
    for buyer, b in (scorecard.get("buyers") or {}).items():
        con.execute("INSERT OR REPLACE INTO buyers VALUES (?,?,?)",
                    (slug, buyer, b.get("interest")))
        for sig in b.get("signals") or []:
            con.execute("INSERT INTO buyer_signals VALUES (?,?,?,?,?)",
                        (slug, buyer, sig.get("signal"),
                         sig.get("timestamp"), sig.get("quote")))

    if functionals:
        for speaker, feats in functionals.items():
            for feature, value in feats.items():
                con.execute(
                    "INSERT OR REPLACE INTO functionals VALUES (?,?,?,?)",
                    (slug, speaker, feature, value))

    con.commit()
    if own:
        con.close()


def store_turns(slug, timed_turns, con=None):
    """Store the full transcript as one row per turn (times are the
    word-count estimates used everywhere else in the pipeline)."""
    own = con is None
    if own:
        con = connect()
    con.execute("DELETE FROM turns WHERE call_slug=?", (slug,))
    con.executemany(
        "INSERT INTO turns VALUES (?,?,?,?,?,?)",
        [(slug, i, spk, round(t0, 2), round(t1, 2), txt)
         for i, (t0, t1, spk, txt) in enumerate(timed_turns)])
    con.commit()
    if own:
        con.close()


def load_transcripts():
    """Backfill turns for every already-scored call from the Gemini docx
    files (requires the pipeline's deps, so run inside the analysis venv)."""
    from pipeline import estimate_turn_times, find_pairs, parse_gemini, slugify
    con = connect()
    scored = {r[0] for r in con.execute("SELECT slug FROM calls")}
    n = 0
    for prefix, _rec, notes in find_pairs():
        slug = slugify(prefix)
        if slug not in scored:
            continue
        _meta, turns, _text = parse_gemini(notes)
        store_turns(slug, estimate_turn_times(turns), con=con)
        n += 1
    total = con.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
    con.close()
    print(f"stored transcripts for {n} calls ({total} turns)")


OWNERS = {
    5025014: "Kelsey Galarza", 87208914: "Brett Corcoran",
    160340942: "Ed Stockman", 160341263: "Brandon Bay",
    160593386: "Max Riemer", 161219851: "Mark Curatolo",
    162069650: "Optimus Prime", 162341289: "Jonathan Salama",
    162372101: "Jonathan Salama", 164569270: "Toby Pasquale",
}

CALL_DISPOSITIONS = {
    "9d9162e7-6cf3-4944-bf63-4dff82258764": "Busy",
    "f240bbac-87c9-4f6e-bf70-924b57d47db7": "Connected",
    "e048a00f-454d-4679-889a-109df8825857": "Connected - Demo booked",
    "35e82fb4-9921-4e23-a7e9-2a58cd69f2c1": "DNC",
    "99e93762-f02b-42ed-beff-d8ba8f8422b2": "Follow up",
    "603ea01c-52a0-4d39-afe4-801779e43b16": "Interested - gatekeeper",
    "a019543b-363e-4b11-aa05-90ff13875421": "Interested - send info",
    "a4c4c377-d246-4b32-a13b-75a56a4cd0ff": "Left live message",
    "b2cf5968-551e-4856-9783-52b3da59a7d0": "Left voicemail",
    "73a0d17f-1163-4015-bdd5-ec830791da20": "No answer",
    "17b47fee-58de-441e-a44c-c6300d46f273": "Wrong number",
}


def load_hubspot(con=None):
    """Ingest raw HubSpot engagement pages from raw/hubspot/*.json into
    hs_calls / hs_meetings. The page files (verbatim API responses) stay on
    disk as the raw source; this just types them into queryable tables."""
    raw = HERE / "raw" / "hubspot"
    if not raw.exists():
        print("no raw/hubspot pages; skipping engagements")
        return
    own = con is None
    if own:
        con = connect()
    n_calls = n_meet = 0
    for path in sorted(raw.glob("*.json")):
        page = json.loads(path.read_text())
        for rec in page.get("results", []):
            p = rec.get("properties", {})
            if "calls_" in path.name:
                oid = int(p["hubspot_owner_id"]) if p.get("hubspot_owner_id") else None
                con.execute(
                    "INSERT OR REPLACE INTO hs_calls "
                    "(call_id, title, ts, duration_ms, direction, disposition,"
                    " disposition_label, status, recording_url, recording_path,"
                    " body, owner_id, owner_name) VALUES (?,?,?,?,?,?,?,?,?,"
                    " (SELECT recording_path FROM hs_calls WHERE call_id=?),"
                    " ?,?,?)",
                    (rec["id"], p.get("hs_call_title"), p.get("hs_timestamp"),
                     int(p["hs_call_duration"]) if p.get("hs_call_duration") else None,
                     p.get("hs_call_direction"), p.get("hs_call_disposition"),
                     CALL_DISPOSITIONS.get(p.get("hs_call_disposition"), None),
                     p.get("hs_call_status"), p.get("hs_call_recording_url"),
                     rec["id"], p.get("hs_call_body"), oid,
                     OWNERS.get(oid)))
                n_calls += 1
            elif "meetings_" in path.name:
                oid = int(p["hubspot_owner_id"]) if p.get("hubspot_owner_id") else None
                con.execute(
                    "INSERT OR REPLACE INTO hs_meetings VALUES (?,?,?,?,?,?,?)",
                    (rec["id"], p.get("hs_meeting_title"),
                     p.get("hs_meeting_start_time"), p.get("hs_meeting_outcome"),
                     p.get("hs_meeting_body"), oid, OWNERS.get(oid)))
                n_meet += 1
    con.commit()
    print(f"hubspot engagements: {n_calls} calls, {n_meet} meetings ingested")
    if own:
        con.close()


# Generic words that don't identify a company (meeting types, corp suffixes).
MATCH_STOP = {
    "demo", "review", "intro", "follow", "up", "trial", "onboarding", "call",
    "sync", "meeting", "partnership", "details", "proposal", "check", "in",
    "new", "deal", "freemium", "self", "serve", "the", "and", "a", "io",
    "llc", "inc", "co", "company", "group", "services", "solutions",
    "agency", "agent", "started", "kickoff", "connect", "re",
}


def _tokens(text):
    words = re.sub(r"[^a-z0-9 ]+", " ", text.lower().replace(".", "")).split()
    return {w for w in words if w not in MATCH_STOP}


def load_deals(con=None):
    """Load HubSpot deals from hubspot_deals.json and match them to scored
    calls by company-name tokens (call title tokens ⊆ deal tokens or vice
    versa). Conservative: person-named or generic call titles stay unmatched
    rather than guessing."""
    path = HERE / "hubspot_deals.json"
    if not path.exists():
        print("no hubspot_deals.json; skipping deals")
        return
    data = json.loads(path.read_text())
    labels, ranks = data["stage_labels"], data["stage_rank"]
    own = con is None
    if own:
        con = connect()
    con.execute("DELETE FROM deals")
    con.execute("DELETE FROM call_deals WHERE method != 'manual'")
    for d in data["deals"]:
        con.execute("INSERT INTO deals VALUES (?,?,?,?,?,?,?,?)",
                    (d["id"], d["name"], d["stage"], labels[d["stage"]],
                     ranks[d["stage"]], d["pipeline"], d["created"], d["closed"]))

    deal_tokens = {d["id"]: _tokens(d["name"]) for d in data["deals"]}
    pipe_of = {d["id"]: d["pipeline"] for d in data["deals"]}
    matched = 0
    for slug, title in con.execute("SELECT slug, title FROM calls"):
        ct = _tokens(title)
        if not ct:
            continue
        hits = [did for did, dt in deal_tokens.items()
                if dt and (ct <= dt or dt <= ct)]
        # a call maps to one company: within a pipeline keep only the tightest
        # name match ("Express Logistics" beats "24/7 Express Logistics");
        # cross-pipeline duplicates are the same company (e.g. WSI sales+trial)
        best_per_pipe = {}
        for did in hits:
            cur = best_per_pipe.get(pipe_of[did])
            if cur is None or len(deal_tokens[did]) < len(deal_tokens[cur]):
                best_per_pipe[pipe_of[did]] = did
        for did in best_per_pipe.values():
            con.execute("INSERT OR REPLACE INTO call_deals VALUES (?,?,?)",
                        (slug, did, "title-token"))
        matched += bool(best_per_pipe)
    for slug, did in (data.get("manual_matches") or {}).items():
        con.execute("INSERT OR REPLACE INTO call_deals VALUES (?,?,?)",
                    (slug, did, "manual"))
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
    print(f"deals: {len(data['deals'])} loaded, {matched}/{total} calls matched")
    if own:
        con.close()


def rebuild():
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = connect()
    n = 0
    for path in sorted((HERE / "scorecards").glob("*.json")):
        sc = json.loads(path.read_text())
        fpath = HERE / "features" / path.name
        feats = json.loads(fpath.read_text()) if fpath.exists() else None
        upsert_call(sc, feats, con=con)
        n += 1
    load_deals(con=con)
    load_hubspot(con=con)
    con.close()
    print(f"rebuilt {DB_PATH.name}: {n} calls")
    con = sqlite3.connect(DB_PATH)
    for table in ("calls", "speakers", "functionals", "gradings", "evidence",
                  "buyers", "buyer_signals", "coaching"):
        count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count} rows")


def query(sql):
    con = sqlite3.connect(DB_PATH)
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    print(" | ".join(cols))
    for row in cur.fetchall():
        print(" | ".join("" if v is None else str(v) for v in row))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "rebuild":
        rebuild()
    elif len(sys.argv) > 1 and sys.argv[1] == "transcripts":
        load_transcripts()
    elif len(sys.argv) > 1 and sys.argv[1] == "deals":
        load_deals()
    elif len(sys.argv) > 1 and sys.argv[1] == "hubspot":
        load_hubspot()
    elif len(sys.argv) > 2 and sys.argv[1] == "query":
        query(sys.argv[2])
    else:
        print(__doc__)
