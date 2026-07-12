"""Backfill arousal/valence onto existing scorecards + ledgers (no re-judge).

Uses the cached wavs in .cache/ (re-extracts from the recording if missing).
Safe to run while the main pipeline is idle; skips scorecards that already
have emotion data.

Usage: python backfill_emotion.py
"""
import json

from emotion import speaker_emotion
from pipeline import (CACHE, HERE, LEDGER, SCORECARDS, baseline_of,
                      estimate_turn_times, extract_audio, find_pairs,
                      parse_gemini, slugify)

pairs = {slugify(p): (r, n) for p, r, n in find_pairs()}

updated = 0
for path in sorted(SCORECARDS.glob("*.json")):
    sc = json.loads(path.read_text())
    slug = sc["call"]
    if all(v.get("arousal") is not None for v in sc["acoustics"].values()):
        continue
    if slug not in pairs:
        print(f"[{slug}] source files missing; skipping")
        continue
    recording, notes = pairs[slug]
    print(f"[{slug}] computing emotion...", flush=True)
    try:
        _, turns, _ = parse_gemini(notes)
        timed = estimate_turn_times(turns)
        wav = CACHE / f"{slug}.wav"
        if not wav.exists():
            wav = extract_audio(recording, slug)
        emo = speaker_emotion(wav, timed, speakers=list(sc["acoustics"]))
    except Exception as e:  # noqa: BLE001
        print(f"[{slug}] FAILED: {e}")
        continue
    for name, vals in emo.items():
        sc["acoustics"][name].update(vals)
    path.write_text(json.dumps(sc, indent=2))
    updated += 1

    # push arousal/valence into ledger entries
    for name in sc.get("sellers", {}):
        lp = LEDGER / f"{name.lower().replace(' ', '-')}.json"
        if not lp.exists() or name not in emo:
            continue
        led = json.loads(lp.read_text())
        for call in led["calls"]:
            if call["call"] == slug:
                call["arousal"] = emo[name]["arousal"]
                call["valence"] = emo[name]["valence"]
        led["baseline"] = baseline_of(led)
        lp.write_text(json.dumps(led, indent=2))

print(f"done: {updated} scorecards enriched")
