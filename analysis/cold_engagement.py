"""Measure the REP's vocal engagement on cold calls (not the prospect's).

Cold-call audio is single-mix with no speaker labels, so:
 1. Build a voice-print for the rep (ECAPA embedding averaged over known-Max
    turns from the demo corpus, where Gemini transcripts give attribution).
 2. Per cold call, embed each whisper segment >= 1.5s, 2-means cluster, and
    take the cluster nearer the voice-print as the rep (falls back to
    similarity threshold when a call is effectively one voice).
 3. Run the audEERING emotion model + eGeMAPS acoustics on rep-only audio.

Writes cold_engagement rows. Resumable. Run inside the analysis venv:
  python cold_engagement.py [--limit N]
"""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import numpy as np
import torch
from speechbrain.inference.speaker import EncoderClassifier

from emotion import speaker_emotion
from pipeline import speaker_acoustics

HERE = Path(__file__).parent
DB = HERE / "voice.db"
SR = 16000
REP = "Max Riemer"
REF_TURNS = 40          # demo turns to average into the voice-print
MIN_SEG_SEC = 1.5


def load_wav_16k(path):
    """Any input format -> float32 mono 16k via ffmpeg."""
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


def rep_voiceprint(encoder, con):
    """Average embedding over known-rep turns from the demo corpus."""
    rows = con.execute(
        """SELECT call_slug, t0, t1 FROM turns
           WHERE speaker=? AND t1-t0 BETWEEN 4 AND 20
           ORDER BY call_slug, idx""", (REP,)).fetchall()
    # spread across calls: at most 2 turns per call
    per_call, picked = {}, []
    for slug, t0, t1 in rows:
        if per_call.get(slug, 0) < 2:
            per_call[slug] = per_call.get(slug, 0) + 1
            picked.append((slug, t0, t1))
        if len(picked) >= REF_TURNS:
            break
    embs, cache = [], {}
    for slug, t0, t1 in picked:
        wav = HERE / ".cache" / f"{slug}.wav"
        if not wav.exists():
            continue
        if slug not in cache:
            cache[slug] = load_wav_16k(wav)
        seg = cache[slug][int(t0 * SR):int(t1 * SR)]
        if len(seg) > SR:
            embs.append(embed(encoder, seg))
    print(f"voice-print from {len(embs)} demo turns", flush=True)
    return np.mean(embs, axis=0)


def main():
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    con = sqlite3.connect(DB, timeout=60)
    con.execute("PRAGMA journal_mode=WAL")

    encoder = EncoderClassifier.from_hparams(
        source="speechbrain/spkrec-ecapa-voxceleb",
        savedir=str(HERE / ".cache" / "ecapa"))
    ref = rep_voiceprint(encoder, con)

    rows = con.execute(
        """SELECT t.call_id, h.recording_path, t.segments
           FROM cold_transcripts t JOIN hs_calls h USING(call_id)
           WHERE h.recording_path IS NOT NULL
             AND t.call_id NOT IN (SELECT call_id FROM cold_engagement)""").fetchall()
    if limit:
        rows = rows[:limit]
    print(f"analyzing rep engagement on {len(rows)} cold calls", flush=True)

    for i, (call_id, rel_path, segments_json) in enumerate(rows, 1):
        try:
            audio = load_wav_16k(HERE / rel_path)
            segs = [s for s in json.loads(segments_json)
                    if s["end"] - s["start"] >= MIN_SEG_SEC]
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
            # 2-means on embeddings; rep cluster = higher mean similarity
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

            timed = [(s["start"], s["end"], REP, s["text"]) for s in rep_segs]
            wav_path = HERE / rel_path
            acoustics = speaker_acoustics(wav_path, timed)
            emo = speaker_emotion(wav_path, timed, [REP])
            a = acoustics.get(REP, {})
            e = emo.get(REP, {})
            rep_seconds = sum(s["end"] - s["start"] for s in rep_segs)
            con.execute(
                "INSERT OR REPLACE INTO cold_engagement VALUES (?,?,?,?,?,?,?,?,?,?)",
                (call_id, e.get("arousal"), e.get("valence"), e.get("dominance"),
                 a.get("f0_std_semitones"), a.get("pace_peaks_per_sec"),
                 a.get("loudness_cv"), round(len(rep_segs) / len(keep), 2),
                 round(rep_seconds, 1), round(rep_sim, 3)))
            con.commit()
            if i % 20 == 0:
                print(f"[{i}/{len(rows)}]", flush=True)
        except Exception as ex:  # noqa: BLE001
            print(f"[{i}/{len(rows)}] {call_id} skipped: {ex}", flush=True)
    total = con.execute("SELECT COUNT(*) FROM cold_engagement").fetchone()[0]
    print(f"done: {total} calls with rep engagement measured", flush=True)
    con.close()


if __name__ == "__main__":
    main()
