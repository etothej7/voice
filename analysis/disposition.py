"""Engagement disposition per rep - the passion/coachability axis.

Computed across a rep's full scored history (never a single call):
  mean_arousal   - overall vocal energy level (0-1, speech emotion model)
  ceiling        - 90th percentile of per-third arousal across all calls:
                   "does this rep EVER light up?"
  fade_rate      - share of calls where arousal fades start->end
  range_mean     - avg within-call arousal range (responsiveness)

Levels (heuristic v1 thresholds - documented as provisional until outcome
data validates them; see hypotheses.json H1):
  high_energy - consistently animated or clearly capable of lighting up
  steady      - normal conversational engagement
  flat        - never rises; low energy across the whole sample. Combined
                with weak quality criteria this is the "coaching won't fix
                it" signal.

Requires baseline-active sample size; otherwise "insufficient_data".
"""
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
THRESHOLDS = {
    "flat_ceiling": 0.52,   # never exceeds this in any call third -> can't light up
    "flat_mean": 0.47,
    "high_mean": 0.52,
    "high_ceiling": 0.60,
    "fade_warn": 0.40,      # >40% of calls fading start->end
}


def rep_slug(name):
    import re
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def compute_dispositions(min_calls=5):
    per_rep = {}
    for p in (HERE / "scorecards").glob("*.json"):
        sc = json.loads(p.read_text())
        for name in sc.get("sellers", {}):
            a = sc.get("acoustics", {}).get(name, {})
            if a.get("arousal") is None:
                continue
            thirds = [t for t in (a.get("arousal_thirds") or []) if t is not None]
            per_rep.setdefault(name, []).append({
                "arousal": a["arousal"],
                "thirds": thirds,
                "fade": len(thirds) >= 2 and thirds[-1] - thirds[0] <= -0.05,
                "range": max(thirds) - min(thirds) if len(thirds) >= 2 else None,
            })

    out = {}
    for name, calls in per_rep.items():
        n = len(calls)
        if n < min_calls:
            out[name] = {"level": "insufficient_data", "n_calls": n}
            continue
        arousal = [c["arousal"] for c in calls]
        all_thirds = [t for c in calls for t in c["thirds"]]
        ranges = [c["range"] for c in calls if c["range"] is not None]
        mean = float(np.mean(arousal))
        ceiling = float(np.percentile(all_thirds, 90)) if all_thirds else mean
        fade_rate = sum(c["fade"] for c in calls) / n

        if ceiling < THRESHOLDS["flat_ceiling"] and mean < THRESHOLDS["flat_mean"]:
            level = "flat"
        elif mean >= THRESHOLDS["high_mean"] or ceiling >= THRESHOLDS["high_ceiling"]:
            level = "high_energy"
        else:
            level = "steady"

        out[name] = {
            "level": level,
            "n_calls": n,
            "mean_arousal": round(mean, 3),
            "ceiling": round(ceiling, 3),
            "fade_rate": round(fade_rate, 2),
            "range_mean": round(float(np.mean(ranges)), 3) if ranges else None,
            "fade_warning": fade_rate > THRESHOLDS["fade_warn"],
            "thresholds_version": "v1-heuristic",
        }
    return out


def update_ledgers(min_calls=5):
    dispositions = compute_dispositions(min_calls)
    for name, disp in dispositions.items():
        lp = HERE / "ledger" / f"{rep_slug(name)}.json"
        if not lp.exists():
            continue
        led = json.loads(lp.read_text())
        led["disposition"] = disp
        lp.write_text(json.dumps(led, indent=2))
        print(f"{name}: {disp}")
    return dispositions


if __name__ == "__main__":
    update_ledgers()
