"""Backfill full eGeMAPS functionals for already-scored calls.

Usage: python backfill_features.py
"""
import json

from features import speaker_functionals
from pipeline import (CACHE, HERE, SCORECARDS, estimate_turn_times,
                      extract_audio, find_pairs, parse_gemini, slugify)

FEATURES = HERE / "features"
FEATURES.mkdir(exist_ok=True)

pairs = {slugify(p): (r, n) for p, r, n in find_pairs()}

done = 0
for path in sorted(SCORECARDS.glob("*.json")):
    sc = json.loads(path.read_text())
    slug = sc["call"]
    out = FEATURES / f"{slug}.json"
    if out.exists():
        continue
    if slug not in pairs:
        print(f"[{slug}] source files missing; skipping")
        continue
    recording, notes = pairs[slug]
    print(f"[{slug}] extracting 88 functionals...", flush=True)
    try:
        _, turns, _ = parse_gemini(notes)
        timed = estimate_turn_times(turns)
        wav = CACHE / f"{slug}.wav"
        if not wav.exists():
            wav = extract_audio(recording, slug)
        feats = speaker_functionals(wav, timed, speakers=list(sc["acoustics"]))
    except Exception as e:  # noqa: BLE001
        print(f"[{slug}] FAILED: {e}")
        continue
    out.write_text(json.dumps(feats, indent=1))
    done += 1

print(f"done: {done} calls")
