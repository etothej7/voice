"""Ingest + transcribe customer-org call samples (S3 hubspot-call-samples).

Customer recordings (8x8 via HubSpot) are STEREO: one channel per party, so
speaker attribution is exact — no diarization. Each channel is transcribed
separately and the rep channel is detected by which side names the org
("this is Andrew with Circle Logistics"), falling back to greater talk time
on outbound calls.

Writes ext_calls + ext_turns. Resumable. Run inside the analysis venv:
  python ext_pipeline.py
"""
import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from faster_whisper import WhisperModel

HERE = Path(__file__).parent
DB = HERE / "voice.db"
SAMPLES = HERE / "raw" / "s3-samples" / "hubspot-call-samples"


def ingest(con):
    n = 0
    for calls_file in sorted(SAMPLES.glob("*/*/calls.jsonl")):
        org_dir = calls_file.parent
        summary = json.loads((org_dir.parent / "summary.json").read_text())
        org = next(o for o in summary["orgs"] if o["pattern"] == org_dir.name)
        for line in calls_file.read_text().splitlines():
            r = json.loads(line)
            cid = r["hubspot_call_id"]
            rec = org_dir / "recordings" / f"{cid}.wav"
            con.execute(
                "INSERT OR REPLACE INTO ext_calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (org["org_id"], org["org_name"], cid, r.get("hs_call_title"),
                 r.get("hs_timestamp"),
                 int(r["hs_call_duration"]) if r.get("hs_call_duration") else None,
                 r.get("hs_call_direction"), r.get("hs_call_disposition"),
                 r.get("hs_call_status"), r.get("hs_call_from_number"),
                 r.get("hs_call_to_number"),
                 str(rec.relative_to(HERE)) if rec.exists() else None))
            n += 1
    con.commit()
    print(f"ingested {n} customer call records", flush=True)


def transcribe(con, model):
    rows = con.execute(
        """SELECT org_id, call_id, recording_path, org_name, direction FROM ext_calls
           WHERE recording_path IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM ext_turns t
                             WHERE t.org_id=ext_calls.org_id
                               AND t.call_id=ext_calls.call_id)""").fetchall()
    print(f"transcribing {len(rows)} stereo customer calls", flush=True)
    for i, (org_id, call_id, rel, org_name, direction) in enumerate(rows, 1):
        wav = HERE / rel
        try:
            with tempfile.TemporaryDirectory() as td:
                chans = [Path(td) / "ch0.wav", Path(td) / "ch1.wav"]
                subprocess.run(
                    ["ffmpeg", "-v", "error", "-y", "-i", str(wav),
                     "-filter_complex", "[0:a]channelsplit=channel_layout=stereo[a][b]",
                     "-map", "[a]", str(chans[0]), "-map", "[b]", str(chans[1])],
                    check=True, timeout=300)
                turns, talk = [], [0.0, 0.0]
                for ch, path in enumerate(chans):
                    segs, _ = model.transcribe(str(path), language="en", vad_filter=True)
                    for s in segs:
                        turns.append((s.start, s.end, ch, s.text.strip()))
                        talk[ch] += s.end - s.start
            turns.sort()
            org_token = org_name.split()[0].lower()
            mentions = [sum(org_token in t[3].lower() for t in turns if t[2] == ch)
                        for ch in (0, 1)]
            if mentions[0] != mentions[1]:
                rep_ch = 0 if mentions[0] > mentions[1] else 1
            else:  # fallback: on outbound calls the rep usually talks more
                rep_ch = 0 if talk[0] >= talk[1] else 1
            con.execute("DELETE FROM ext_turns WHERE org_id=? AND call_id=?",
                        (org_id, call_id))
            con.executemany(
                "INSERT INTO ext_turns VALUES (?,?,?,?,?,?,?)",
                [(org_id, call_id, idx,
                  "rep" if ch == rep_ch else "counterpart",
                  round(t0, 1), round(t1, 1), text)
                 for idx, (t0, t1, ch, text) in enumerate(turns)])
            con.commit()
            print(f"[{i}/{len(rows)}] {call_id} ({len(turns)} turns)", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(rows)}] {call_id} FAILED: {e}", flush=True)


def main():
    con = sqlite3.connect(DB, timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    ingest(con)
    model = WhisperModel("small", device="cpu", compute_type="int8", cpu_threads=8)
    transcribe(con, model)
    con.close()


if __name__ == "__main__":
    main()
