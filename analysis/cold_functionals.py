"""Extract all 88 eGeMAPS functionals on Max's rep-only audio for the cold
(phone) calls that already have cached whisper transcripts.

Reuses cold_engagement.py's voice-print attribution: build Max's ECAPA
voice-print from the demo corpus, cluster each call's whisper segments, keep
the cluster nearer the print. Cold calls are MONO single-mix, so attribution
is approximate (unlike the stereo customer calls) - rep_similarity is stored
per call so low-confidence calls can be filtered downstream.

Recordings are (re)downloaded on demand from the HubSpot getAuthRecording URL,
which redirects to a signed CDN url and needs no token (same as
fetch_recordings.py). Nooks-hosted URLs are skipped (expired).

Writes cold_functionals(call_id, feature, value) + cold_rep_conf(call_id,
rep_similarity, rep_share, rep_seconds). Resumable. Run in the analysis venv:
  python cold_functionals.py [--limit N]
"""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import numpy as np
import torch
from speechbrain.inference.speaker import EncoderClassifier

from features import speaker_functionals

HERE = Path(__file__).parent
DB = HERE / "voice.db"
REC = HERE / "recordings"
SR = 16000
REP = "Max Riemer"
REF_TURNS = 40
MIN_SEG_SEC = 1.5


def load_wav_16k(path):
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le",
         "-ac", "1", "-ar", str(SR), "pipe:1"],
        capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def embed(encoder, audio):
    with torch.no_grad():
        return encoder.encode_batch(
            torch.from_numpy(audio).unsqueeze(0)).squeeze().numpy()


def cos(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def rep_voiceprint(encoder, con, n_vm=20):
    """Average ECAPA embedding over the rep's VOICEMAILS - pure rep speech
    (prospect absent), so no attribution ambiguity. Skips the first 3s
    (ringing/beep) and embeds ~4s windows."""
    rows = con.execute(
        """SELECT call_id, recording_url FROM hs_calls
           WHERE disposition_label='Left voicemail'
             AND recording_url LIKE '%hubspot%'
             AND duration_ms BETWEEN 15000 AND 90000
           ORDER BY duration_ms DESC LIMIT ?""", (n_vm,)).fetchall()
    embs = []
    for call_id, url in rows:
        try:
            path = REC / f"{call_id}.wav"
            if not (path.exists() and path.stat().st_size > 4096):
                download(url, path)
            audio = load_wav_16k(path)
            audio = audio[int(3 * SR):]  # skip ring/beep
            for start in range(0, max(1, len(audio) - 4 * SR), 4 * SR):
                w = audio[start:start + 4 * SR]
                if len(w) >= 3 * SR:
                    embs.append(embed(encoder, w))
        except Exception as e:  # noqa: BLE001
            print(f"  voicemail {call_id} skipped: {e}", flush=True)
    print(f"voice-print from {len(embs)} voicemail windows "
          f"({len(rows)} voicemails)", flush=True)
    return np.mean(embs, axis=0)


def download(url, path):
    """HubSpot getAuthRecording -> signed CDN redirect -> mono 16k wav."""
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", url,
         "-vn", "-ac", "1", "-ar", str(SR), str(path)],
        check=True, timeout=1800)


def attribute_rep(encoder, audio, segments, ref):
    """-> list of rep (start,end,text) turns, mean rep similarity, rep share."""
    segs = [s for s in segments if s["end"] - s["start"] >= MIN_SEG_SEC]
    embs, keep = [], []
    for s in segs:
        a = audio[int(s["start"] * SR):int(s["end"] * SR)]
        if len(a) < SR:
            continue
        embs.append(embed(encoder, a))
        keep.append(s)
    if len(keep) < 2:
        raise ValueError("too few usable segments")
    X = np.stack(embs)
    sims = np.array([cos(e, ref) for e in embs])
    c0 = X[sims >= np.median(sims)].mean(axis=0)
    c1 = X[sims < np.median(sims)].mean(axis=0)
    for _ in range(8):
        d0 = X @ c0 / (np.linalg.norm(X, axis=1) * np.linalg.norm(c0))
        d1 = X @ c1 / (np.linalg.norm(X, axis=1) * np.linalg.norm(c1))
        lab = d0 >= d1
        if lab.all() or (~lab).all():
            break
        c0, c1 = X[lab].mean(axis=0), X[~lab].mean(axis=0)
    rep_cluster = lab if cos(c0, ref) >= cos(c1, ref) else ~lab
    rep_segs = [s for s, is_rep in zip(keep, rep_cluster) if is_rep]
    rep_sim = float(sims[rep_cluster].mean())
    if not rep_segs or rep_sim < 0.15:
        raise ValueError(f"rep not identified (sim {rep_sim:.2f})")
    share = len(rep_segs) / len(keep)
    return rep_segs, rep_sim, share


def main():
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    con = sqlite3.connect(DB, timeout=60)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""CREATE TABLE IF NOT EXISTS cold_functionals (
        call_id INTEGER NOT NULL, feature TEXT NOT NULL, value REAL,
        PRIMARY KEY (call_id, feature))""")
    con.execute("""CREATE TABLE IF NOT EXISTS cold_rep_conf (
        call_id INTEGER PRIMARY KEY, rep_similarity REAL, rep_share REAL,
        rep_seconds REAL)""")
    con.commit()
    REC.mkdir(exist_ok=True)

    encoder = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=str(HERE / ".cache" / "ecapa"))
    ref = rep_voiceprint(encoder, con)

    rows = con.execute(
        """SELECT t.call_id, h.recording_url, h.recording_path, t.segments
           FROM cold_transcripts t JOIN hs_calls h USING(call_id)
           WHERE h.recording_url NOT LIKE '%nooks%'
             AND t.call_id NOT IN (SELECT call_id FROM cold_functionals)""").fetchall()
    if limit:
        rows = rows[:limit]
    print(f"extracting rep functionals on {len(rows)} cold phone calls",
          flush=True)

    ok = fail = 0
    for i, (call_id, url, rel_path, segments_json) in enumerate(rows, 1):
        try:
            path = REC / f"{call_id}.wav"
            if not (path.exists() and path.stat().st_size > 4096):
                download(url, path)
            audio = load_wav_16k(path)
            segments = json.loads(segments_json)
            rep_segs, rep_sim, share = attribute_rep(encoder, audio, segments, ref)
            timed = [(s["start"], s["end"], REP, s["text"]) for s in rep_segs]
            feats = speaker_functionals(path, timed, [REP]).get(REP)
            if not feats:
                raise ValueError("no functionals (insufficient rep audio)")
            con.executemany(
                "INSERT OR REPLACE INTO cold_functionals VALUES (?,?,?)",
                [(call_id, k, v) for k, v in feats.items()])
            rep_seconds = sum(s["end"] - s["start"] for s in rep_segs)
            con.execute("INSERT OR REPLACE INTO cold_rep_conf VALUES (?,?,?,?)",
                        (call_id, round(rep_sim, 3), round(share, 2),
                         round(rep_seconds, 1)))
            con.commit()
            ok += 1
            if i % 20 == 0:
                print(f"[{i}/{len(rows)}] ok={ok} fail={fail}", flush=True)
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"[{i}/{len(rows)}] {call_id} FAILED: {e}", flush=True)
    print(f"done: {ok} extracted, {fail} failed", flush=True)
    con.close()


if __name__ == "__main__":
    main()
