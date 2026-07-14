"""Ingest, transcribe, and feature-extract customer-org call samples.

Extends ext_pipeline.py to the 2026-07-11 S3 batches (calls_recorded_batch2,
calls_with_recordings) and adds full eGeMAPS capture: because customer
recordings are STEREO (one channel per party), speaker attribution is exact,
and all 88 functionals are computed per channel over its whisper speech
segments (edge-trimmed, >=1.5s, >=5s total speech).

Rep channel detection mirrors ext_pipeline.py: the side that names the org,
falling back to greater talk time on outbound calls.

Writes ext_calls (+owner_id), ext_turns, ext_functionals. Resumable.
Run inside the analysis venv:  python ext_features.py
"""
import json
import sqlite3
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import opensmile
from faster_whisper import WhisperModel

HERE = Path(__file__).parent
DB = HERE / "voice.db"
SAMPLES = HERE / "raw" / "s3-samples" / "hubspot-call-samples"
SR = 16000
MIN_SEG_SEC = 1.5
EDGE_TRIM = 0.15

CALL_FILES = ("calls.jsonl", "calls_recorded_batch2.jsonl",
              "calls_with_recordings.jsonl")


def ensure_schema(con):
    cols = {r[1] for r in con.execute("PRAGMA table_info(ext_calls)")}
    if "owner_id" not in cols:
        con.execute("ALTER TABLE ext_calls ADD COLUMN owner_id TEXT")
    con.execute("""CREATE TABLE IF NOT EXISTS ext_functionals (
        org_id INTEGER NOT NULL,
        call_id TEXT NOT NULL,
        role TEXT NOT NULL,              -- rep | counterpart
        feature TEXT NOT NULL,
        value REAL,
        PRIMARY KEY (org_id, call_id, role, feature))""")
    con.commit()


def ingest(con):
    n = 0
    for date_dir in sorted(SAMPLES.iterdir()):
        summary = json.loads((date_dir / "summary.json").read_text())
        for org in summary["orgs"]:
            org_dir = date_dir / org["pattern"]
            seen = set()
            for fname in CALL_FILES:
                f = org_dir / fname
                if not f.exists():
                    continue
                for line in f.read_text().splitlines():
                    r = json.loads(line)
                    cid = r["hubspot_call_id"]
                    if cid in seen:
                        continue
                    seen.add(cid)
                    rec = org_dir / "recordings" / f"{cid}.wav"
                    con.execute(
                        """INSERT OR REPLACE INTO ext_calls
                           (org_id, org_name, call_id, title, ts, duration_ms,
                            direction, disposition, status, from_number,
                            to_number, recording_path, owner_id)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (org["org_id"], org["org_name"], cid,
                         r.get("hs_call_title"), r.get("hs_timestamp"),
                         int(r["hs_call_duration"]) if r.get("hs_call_duration") else None,
                         r.get("hs_call_direction"), r.get("hs_call_disposition"),
                         r.get("hs_call_status"), r.get("hs_call_from_number"),
                         r.get("hs_call_to_number"),
                         str(rec.relative_to(HERE)) if rec.exists() else None,
                         r.get("hubspot_owner_id")))
                    n += 1
    con.commit()
    print(f"ingested {n} customer call records", flush=True)


def split_channels(wav, td):
    chans = [Path(td) / "ch0.wav", Path(td) / "ch1.wav"]
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(wav),
         "-filter_complex", "[0:a]channelsplit=channel_layout=stereo[a][b]",
         "-map", "[a]", "-ar", str(SR), str(chans[0]),
         "-map", "[b]", "-ar", str(SR), str(chans[1])],
        check=True, timeout=300)
    return chans


def read_wav(path):
    import wave
    with wave.open(str(path)) as wf:
        assert wf.getframerate() == SR and wf.getnchannels() == 1
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


def channel_functionals(smile, path, segs):
    audio = read_wav(path)
    pieces = []
    for t0, t1 in segs:
        a, b = t0 + EDGE_TRIM, t1 - EDGE_TRIM
        if b - a < MIN_SEG_SEC:
            continue
        pieces.append(audio[int(a * SR):int(b * SR)])
    if not pieces:
        return None
    signal = np.concatenate(pieces)
    if len(signal) < SR * 5:
        return None
    df = smile.process_signal(signal, SR)
    return {c: round(float(df[c].iloc[0]), 5) for c in df.columns}


def process(con):
    rows = con.execute(
        """SELECT org_id, call_id, recording_path, org_name, direction
           FROM ext_calls
           WHERE recording_path IS NOT NULL
             AND NOT EXISTS (SELECT 1 FROM ext_functionals f
                             WHERE f.org_id=ext_calls.org_id
                               AND f.call_id=ext_calls.call_id)""").fetchall()
    print(f"processing {len(rows)} stereo customer calls", flush=True)
    model = WhisperModel("small", device="cpu", compute_type="int8",
                         cpu_threads=8)
    smile = opensmile.Smile(
        feature_set=opensmile.FeatureSet.eGeMAPSv02,
        feature_level=opensmile.FeatureLevel.Functionals)
    for i, (org_id, call_id, rel, org_name, direction) in enumerate(rows, 1):
        wav = HERE / rel
        try:
            with tempfile.TemporaryDirectory() as td:
                chans = split_channels(wav, td)
                turns, talk, ch_segs = [], [0.0, 0.0], [[], []]
                for ch, path in enumerate(chans):
                    segs, _ = model.transcribe(str(path), language="en",
                                               vad_filter=True)
                    for s in segs:
                        turns.append((s.start, s.end, ch, s.text.strip()))
                        talk[ch] += s.end - s.start
                        ch_segs[ch].append((s.start, s.end))
                turns.sort()
                org_token = org_name.split()[0].lower()
                mentions = [sum(org_token in t[3].lower() for t in turns
                                if t[2] == ch) for ch in (0, 1)]
                if mentions[0] != mentions[1]:
                    rep_ch = 0 if mentions[0] > mentions[1] else 1
                else:
                    rep_ch = 0 if talk[0] >= talk[1] else 1

                con.execute("DELETE FROM ext_turns WHERE org_id=? AND call_id=?",
                            (org_id, call_id))
                con.executemany(
                    "INSERT INTO ext_turns VALUES (?,?,?,?,?,?,?)",
                    [(org_id, call_id, idx,
                      "rep" if ch == rep_ch else "counterpart",
                      round(t0, 1), round(t1, 1), text)
                     for idx, (t0, t1, ch, text) in enumerate(turns)])

                n_feats = 0
                for ch, path in enumerate(chans):
                    feats = channel_functionals(smile, path, ch_segs[ch])
                    if feats is None:
                        continue
                    role = "rep" if ch == rep_ch else "counterpart"
                    con.executemany(
                        "INSERT OR REPLACE INTO ext_functionals VALUES (?,?,?,?,?)",
                        [(org_id, call_id, role, k, v)
                         for k, v in feats.items()])
                    n_feats += len(feats)
            con.commit()
            print(f"[{i}/{len(rows)}] {call_id} ({len(turns)} turns, "
                  f"{n_feats} functionals)", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(rows)}] {call_id} FAILED: {e}", flush=True)


def main():
    con = sqlite3.connect(DB, timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    ensure_schema(con)
    ingest(con)
    process(con)
    con.close()


if __name__ == "__main__":
    main()
