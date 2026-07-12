"""Score transcribed cold calls against the cold-call rubric.

A different rubric from demo meetings: cold calls are won or lost on the
opener, the hook question, objection handling, and whether the rep actually
asks for the meeting. The disposition (demo booked or not) is ground truth
from the dialer, NOT judged — the judge grades process, the dialer records
outcome, and mining compares the two.

Judge backend follows pipeline.py conventions (claude CLI by default,
JUDGE_BACKEND=<openai-compatible url> + JUDGE_MODEL for e.g. a Qwen box).

Resumable: scored call_ids are skipped. Demo-booked calls score first.

Usage:
  python score_cold_calls.py [--limit N]
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
DB = HERE / "voice.db"
RUBRIC_VERSION = "cold-v1-2026-07-11"

CONNECT_LABELS = ("Connected", "Connected - Demo booked",
                  "Interested - gatekeeper", "Interested - send info")

PROMPT = """You are grading a single COLD CALL by an Optimus sales rep (Optimus \
is freight sales-intelligence software for brokers). The transcript below has \
no speaker labels — infer them: the caller who introduces themselves as being \
with Optimus is the REP; the other party is the PROSPECT.

Call title: {title}
Duration: {minutes} minutes

Grade the REP on exactly these four criteria, each verdict "pass" or \
"needs_improvement":
1. opener — clear self-intro and a specific, relevant reason for the call \
within the first ~20 seconds; earns the next 30 seconds rather than sounding \
like a generic pitch.
2. discovery_hook — asks at least one question about the prospect's freight \
operation (lanes, shippers, spot vs contract, tools) instead of monologuing.
3. objection_handling — when the prospect pushes back or deflects, the rep \
acknowledges and reframes with value instead of folding or arguing. If no \
objection occurs, grade "pass" and say no objection arose.
4. booking_ask — the rep explicitly asks for a meeting/demo and tries to pin \
a concrete time. A vague "I'll send you some info" is needs_improvement.

Also classify the PROSPECT's receptivity: "warm", "neutral", or "hostile".

Every evidence quote must be VERBATIM from the transcript with its [m:ss] \
timestamp. Give exactly one coaching_action for the rep — the single highest \
leverage change, phrased as an instruction, citing what actually happened on \
this call.

Return ONLY JSON:
{{"criteria": {{"opener": {{"verdict": "...", "explanation": "...", \
"evidence": [{{"timestamp": "m:ss", "quote": "..."}}]}}, "discovery_hook": \
{{...}}, "objection_handling": {{...}}, "booking_ask": {{...}}}}, \
"receptivity": "...", "coaching_action": "..."}}

TRANSCRIPT:
{transcript}
"""


def judge(prompt):
    backend = os.environ.get("JUDGE_BACKEND", "claude")
    for attempt in range(2):
        try:
            if backend == "claude":
                r = subprocess.run(
                    ["claude", "-p", "--output-format", "json", "--model", "opus"],
                    input=prompt, capture_output=True, text=True, timeout=900)
                if r.returncode != 0:
                    print(f"   judge attempt {attempt+1} failed: {r.stderr[:300]}", flush=True)
                    continue
                text = json.loads(r.stdout)["result"]
            else:
                import requests
                resp = requests.post(
                    f"{backend.rstrip('/')}/v1/chat/completions",
                    json={"model": os.environ.get("JUDGE_MODEL", ""),
                          "messages": [{"role": "user", "content": prompt}],
                          "temperature": 0, "max_tokens": 4096,
                          "response_format": {"type": "json_object"}},
                    timeout=900)
                resp.raise_for_status()
                text = resp.json()["choices"][0]["message"]["content"]
            m = re.search(r"\{.*\}", text, re.DOTALL)
            return json.loads(m.group(0))
        except Exception as e:  # noqa: BLE001
            print(f"   judge attempt {attempt+1} error: {e}", flush=True)
    raise RuntimeError("judge failed twice")


def fmt_transcript(segments_json):
    lines = []
    for s in json.loads(segments_json):
        t = int(s["start"])
        lines.append(f"[{t//60}:{t%60:02d}] {s['text']}")
    return "\n".join(lines)


def main():
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    con = sqlite3.connect(DB, timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    placeholders = ",".join("?" * len(CONNECT_LABELS))
    rows = con.execute(
        f"""SELECT t.call_id, h.title, h.duration_ms, t.segments
            FROM cold_transcripts t JOIN hs_calls h USING(call_id)
            WHERE h.disposition_label IN ({placeholders})
              AND t.call_id NOT IN (SELECT call_id FROM cold_scorecards)
              AND length(t.text) > 200
            ORDER BY h.disposition_label = 'Connected - Demo booked' DESC, h.ts DESC""",
        CONNECT_LABELS).fetchall()
    if limit:
        rows = rows[:limit]
    print(f"scoring {len(rows)} cold calls, rubric {RUBRIC_VERSION}", flush=True)

    for i, (call_id, title, dur, segments) in enumerate(rows, 1):
        prompt = PROMPT.format(title=title or "cold call",
                               minutes=round((dur or 0) / 60000, 1),
                               transcript=fmt_transcript(segments))
        try:
            verdict = judge(prompt)
        except RuntimeError as e:
            print(f"[{i}/{len(rows)}] {call_id} FAILED: {e}", flush=True)
            continue
        con.execute(
            "INSERT OR REPLACE INTO cold_scorecards VALUES (?,?,?,?,?)",
            (call_id, RUBRIC_VERSION, verdict.get("receptivity"),
             verdict.get("coaching_action"), json.dumps(verdict)))
        con.commit()
        print(f"[{i}/{len(rows)}] {call_id} scored", flush=True)
    total = con.execute("SELECT COUNT(*) FROM cold_scorecards").fetchone()[0]
    print(f"done: {total} cold scorecards in db", flush=True)
    con.close()


if __name__ == "__main__":
    main()
