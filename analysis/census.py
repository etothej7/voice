"""Census of meetings/: which Gemini docs have transcripts, who speaks, and
which calls look internal (only Optimus people) vs external.

Usage: python census.py
"""
import json
from collections import Counter
from pathlib import Path

from pipeline import docx_lines, parse_gemini, find_pairs, slugify, HERE, SCORECARDS

config = json.loads((HERE / "sellers.json").read_text())
known = set(config["sellers"]) | set(config.get("team", []))

speaker_counter = Counter()
rows = []
for prefix, recording, notes in find_pairs():
    slug = slugify(prefix)
    try:
        _, turns, _ = parse_gemini(notes)
    except SystemExit:
        rows.append({"slug": slug, "status": "no-transcript"})
        continue
    except Exception as e:  # noqa: BLE001
        rows.append({"slug": slug, "status": f"parse-error: {e}"})
        continue
    words = Counter()
    for _, spk, txt in turns:
        words[spk] += len(txt.split())
    speaker_counter.update(words.keys())
    externals = [s for s in words if s not in known]
    rows.append({
        "slug": slug,
        "status": "scored" if (SCORECARDS / f"{slug}.json").exists() else "new",
        "speakers": {s: words[s] for s in sorted(words, key=words.get, reverse=True)},
        "externals": externals,
        "internal": not externals,
    })

print("=== all distinct speakers (by #calls) ===")
for spk, n in speaker_counter.most_common():
    tag = " [seller]" if spk in set(config["sellers"]) else (" [team]" if spk in known else "")
    print(f"{n:3d}  {spk}{tag}")

internal = [r for r in rows if r.get("internal")]
external = [r for r in rows if r.get("speakers") and not r.get("internal")]
broken = [r for r in rows if not r.get("speakers")]
print(f"\n=== summary: {len(external)} external, {len(internal)} internal, {len(broken)} no-transcript/broken ===")
print("\n--- internal (would be skipped) ---")
for r in internal:
    print(f"  {r['slug']}: {list(r['speakers'])}")
print("\n--- no transcript / parse errors ---")
for r in broken:
    print(f"  {r['slug']}: {r['status']}")

(HERE / "census.json").write_text(json.dumps(rows, indent=2))
print(f"\nwrote census.json ({len(rows)} pairs)")
