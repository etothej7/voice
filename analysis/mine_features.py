"""Pattern mining over the full eGeMAPS feature set + emotion + outcomes.

Joins features/<slug>.json with scorecard labels into one table
(features/combined.csv), then reports:
  1. rep-vs-rep contrasts ranked by effect size
  2. buyer-interest contrasts (strong vs rest) on buyer voices
  3. criterion contrasts (pass vs needs_improvement) on seller voices

Effect size = Cohen's d. With n in the tens, |d| >= ~0.6 is worth attention,
|d| >= 1.0 is strong; treat everything as hypothesis-generating, not proof.

Usage: python mine_features.py [--top N]
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
TOP = int(sys.argv[sys.argv.index("--top") + 1]) if "--top" in sys.argv else 12

rows = []
for fpath in (HERE / "features").glob("*.json"):
    slug = fpath.stem
    scpath = HERE / "scorecards" / f"{slug}.json"
    if not scpath.exists():
        continue
    feats = json.loads(fpath.read_text())
    sc = json.loads(scpath.read_text())
    for speaker, values in feats.items():
        acoustic = sc.get("acoustics", {}).get(speaker, {})
        row = {
            "call": slug,
            "speaker": speaker,
            "role": ("seller" if speaker in sc.get("sellers", {})
                     else "buyer" if speaker in sc.get("buyers", {}) else "other"),
            "arousal": acoustic.get("arousal"),
            "valence": acoustic.get("valence"),
            "dominance": acoustic.get("dominance"),
            **values,
        }
        if row["role"] == "seller":
            for crit, res in sc["sellers"][speaker].get("criteria", {}).items():
                row[f"crit_{crit}"] = res.get("verdict")
        if row["role"] == "buyer":
            row["interest"] = sc["buyers"][speaker].get("interest")
        rows.append(row)

df = pd.DataFrame(rows)
df.to_csv(HERE / "features" / "combined.csv", index=False)
feature_cols = [c for c in df.columns if c not in
                ("call", "speaker", "role", "interest") and not c.startswith("crit_")
                and df[c].dtype != object]
print(f"combined table: {len(df)} speaker-calls x {len(feature_cols)} numeric features "
      f"-> features/combined.csv\n")


def cohens_d(a, b):
    a, b = a.dropna(), b.dropna()
    if len(a) < 5 or len(b) < 5:
        return None
    pooled = np.sqrt((a.std() ** 2 + b.std() ** 2) / 2)
    return (a.mean() - b.mean()) / pooled if pooled else None


def contrast(df_a, df_b, label_a, label_b, title):
    print(f"=== {title}  ({label_a} n={len(df_a)} vs {label_b} n={len(df_b)}) ===")
    results = []
    for col in feature_cols:
        d = cohens_d(df_a[col], df_b[col])
        if d is not None and np.isfinite(d):
            results.append((abs(d), d, col, df_a[col].mean(), df_b[col].mean()))
    results.sort(reverse=True)
    for _, d, col, ma, mb in results[:TOP]:
        print(f"  d={d:+5.2f}  {col:58s} {label_a}={ma:9.3f} {label_b}={mb:9.3f}")
    print()


# 1. rep vs rep (sellers only)
sellers = df[df.role == "seller"]
reps = sellers.speaker.value_counts()
if len(reps) >= 2:
    a, b = reps.index[:2]
    contrast(sellers[sellers.speaker == a], sellers[sellers.speaker == b], a.split()[0], b.split()[0],
             f"{a} vs {b} — full feature contrast")

# 2. buyer interest: strong vs rest
buyers = df[df.role == "buyer"]
if buyers.interest.notna().sum() > 10:
    contrast(buyers[buyers.interest == "strong"], buyers[buyers.interest != "strong"],
             "strong", "rest", "Buyer voices — strong interest vs rest")

# 3. seller criteria contrasts
for crit in ("crit_value_prop_clarity", "crit_discovery_progression", "crit_relevance"):
    if crit in sellers.columns:
        passed = sellers[sellers[crit] == "pass"]
        failed = sellers[sellers[crit] == "needs_improvement"]
        if len(passed) >= 5 and len(failed) >= 5:
            contrast(passed, failed, "pass", "needs-imp",
                     f"Seller voices — {crit.removeprefix('crit_')} pass vs needs-improvement")
