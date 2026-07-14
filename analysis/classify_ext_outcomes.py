"""Label each transcribed customer call with a call outcome via the local
`claude` CLI (same headless pattern as pipeline.judge, but batched and on
haiku — the taxonomy is simple enough not to need opus).

Outcomes (freight brokerage taxonomy):
  no_conversation - voicemail, dead air, wrong number, <2 counterpart turns
  gatekeeper      - never reached the decision maker
  brush_off       - reached a person; they declined / not interested
  info_exchange   - real conversation, no concrete next step
  follow_up       - explicit next step agreed (callback, send info, quote to come)
  rate_quote      - a rate/lane was quoted or requested on the call
  load_booked     - a load was booked / covered on the call

Writes ext_outcomes. Resumable. Run inside the analysis venv:
  python classify_ext_outcomes.py
"""
import json
import re
import sqlite3
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
DB = HERE / "voice.db"
BATCH = 8
OUTCOMES = ["no_conversation", "gatekeeper", "brush_off", "info_exchange",
            "follow_up", "rate_quote", "load_booked"]

PROMPT = """You are labeling freight-brokerage sales/ops call transcripts.
For EACH call below, pick exactly one outcome:
- no_conversation: voicemail, dead air, wrong number, or the counterpart never really engages
- gatekeeper: rep never gets past a gatekeeper/receptionist to the decision maker
- brush_off: counterpart engages but declines or shuts the pitch down
- info_exchange: genuine two-way conversation but no concrete next step
- follow_up: an explicit next step is agreed (callback time, send info, quote to follow)
- rate_quote: a specific rate or lane pricing is quoted or requested during the call
- load_booked: a load is booked/covered/confirmed on this call

Also rate counterpart_engagement 0-2 (0=none/hostile, 1=polite, 2=actively interested).

Reply with ONLY a JSON array, one object per call, in the same order:
[{"call_id": "...", "outcome": "...", "counterpart_engagement": 0}]

CALLS:
"""


def transcript_text(con, org_id, call_id, max_chars=4000):
    rows = con.execute(
        """SELECT role, text FROM ext_turns
           WHERE org_id=? AND call_id=? ORDER BY idx""",
        (org_id, call_id)).fetchall()
    lines = [f"{r}: {t}" for r, t in rows]
    return "\n".join(lines)[:max_chars]


def classify_batch(batch):
    payload = "\n\n".join(
        f"--- call_id {cid} ---\n{text}" for cid, text in batch)
    r = subprocess.run(
        ["claude", "-p", "--output-format", "json", "--model", "haiku"],
        input=PROMPT + payload, capture_output=True, text=True, timeout=600)
    body = json.loads(r.stdout)["result"]
    m = re.search(r"\[.*\]", body, re.S)
    return json.loads(m.group(0))


def main():
    con = sqlite3.connect(DB, timeout=60)
    con.execute("""CREATE TABLE IF NOT EXISTS ext_outcomes (
        org_id INTEGER NOT NULL,
        call_id TEXT NOT NULL,
        outcome TEXT,
        counterpart_engagement INTEGER,
        model TEXT,
        PRIMARY KEY (org_id, call_id))""")
    todo = con.execute(
        """SELECT DISTINCT t.org_id, t.call_id FROM ext_turns t
           WHERE NOT EXISTS (SELECT 1 FROM ext_outcomes o
                             WHERE o.org_id=t.org_id AND o.call_id=t.call_id)
           ORDER BY t.org_id, t.call_id""").fetchall()
    print(f"classifying {len(todo)} calls in batches of {BATCH}", flush=True)
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        batch = [(cid, transcript_text(con, oid, cid)) for oid, cid in chunk]
        try:
            results = classify_batch(batch)
            by_id = {str(r["call_id"]): r for r in results}
            for oid, cid in chunk:
                r = by_id.get(str(cid))
                if not r or r.get("outcome") not in OUTCOMES:
                    print(f"  {cid}: bad/missing label, skipped", flush=True)
                    continue
                con.execute(
                    "INSERT OR REPLACE INTO ext_outcomes VALUES (?,?,?,?,?)",
                    (oid, cid, r["outcome"],
                     int(r.get("counterpart_engagement", 0)), "haiku"))
            con.commit()
            print(f"[{min(i + BATCH, len(todo))}/{len(todo)}]", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"batch at {i} FAILED: {e}", flush=True)
    con.close()


if __name__ == "__main__":
    main()
