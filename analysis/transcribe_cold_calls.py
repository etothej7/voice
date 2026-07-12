"""Transcribe downloaded cold-call recordings with faster-whisper.

Targets hs_calls rows that are connected dispositions, under 10 minutes
(dialer conversations, not meetings), and already downloaded. Writes to the
cold_transcripts table: full text + timestamped segments (JSON). No speaker
diarization in v1 — cold calls are two-party and the rubric judge can
attribute lines from content ("Hi, this is Max from Optimus...").

Resumable: call_ids already in cold_transcripts are skipped, so rerun as
more recordings land.

Usage (inside the analysis venv):
  python transcribe_cold_calls.py [--model small] [--limit N]
"""
import json
import sqlite3
import sys
import time
from pathlib import Path

from faster_whisper import WhisperModel

HERE = Path(__file__).parent
DB = HERE / "voice.db"

CONNECT_LABELS = ("Connected", "Connected - Demo booked",
                  "Interested - gatekeeper", "Interested - send info")


def main():
    model_name = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else "small"
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None

    con = sqlite3.connect(DB, timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    placeholders = ",".join("?" * len(CONNECT_LABELS))
    rows = con.execute(
        f"""SELECT call_id, recording_path FROM hs_calls
            WHERE disposition_label IN ({placeholders})
              AND recording_path IS NOT NULL
              AND duration_ms < 600000
              AND call_id NOT IN (SELECT call_id FROM cold_transcripts)
            ORDER BY disposition_label = 'Connected - Demo booked' DESC, ts DESC""",
        CONNECT_LABELS).fetchall()
    if limit:
        rows = rows[:limit]
    print(f"transcribing {len(rows)} cold calls with whisper-{model_name}", flush=True)

    model = WhisperModel(model_name, device="cpu", compute_type="int8", cpu_threads=8)
    t0 = time.time()
    for i, (call_id, rel_path) in enumerate(rows, 1):
        wav = HERE / rel_path
        if not wav.exists():
            continue
        try:
            segments, _info = model.transcribe(str(wav), language="en", vad_filter=True)
            segs = [{"start": round(s.start, 1), "end": round(s.end, 1),
                     "text": s.text.strip()} for s in segments]
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(rows)}] {call_id} FAILED: {e}", flush=True)
            continue
        text = " ".join(s["text"] for s in segs)
        con.execute("INSERT OR REPLACE INTO cold_transcripts VALUES (?,?,?,?)",
                    (call_id, model_name, text, json.dumps(segs)))
        con.commit()
        if i % 10 == 0:
            rate = i / (time.time() - t0)
            print(f"[{i}/{len(rows)}] {rate*60:.0f} calls/hour", flush=True)
    print(f"done: {con.execute('SELECT COUNT(*) FROM cold_transcripts').fetchone()[0]} "
          f"transcripts in db", flush=True)
    con.close()


if __name__ == "__main__":
    main()
