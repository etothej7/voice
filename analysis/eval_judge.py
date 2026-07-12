"""Evaluate an alternative judge (e.g. Qwen) against the Claude-scored corpus.

Re-runs the rubric prompt for sampled already-scored calls through the judge
configured by JUDGE_BACKEND / JUDGE_MODEL, then measures agreement with the
stored (Claude) scorecards:

  - JSON validity rate
  - per-criterion verdict agreement (pass vs needs_improvement)
  - buyer interest agreement (strong/moderate/weak)
  - quote fidelity: % of cited quotes that actually appear verbatim (after
    whitespace/case normalization) in the transcript - the make-or-break
    metric for a local judge, since quotes are the product's evidence

Usage:
  JUDGE_BACKEND=http://<qwen-box>:11434 JUDGE_MODEL=qwen2.5:72b \
      python eval_judge.py [--n 10]

Results append to eval_judge_results.jsonl for comparison across prompt/model
iterations.
"""
import json
import os
import re
import sys
from pathlib import Path

from pipeline import (HERE, RUBRIC_PROMPT, SCORECARDS, SELLERS, TEAM,
                      acoustics_prompt, estimate_turn_times, find_pairs,
                      judge, load_ledger, parse_gemini, slugify)

N = int(sys.argv[sys.argv.index("--n") + 1]) if "--n" in sys.argv else 10
CRITERIA = ["delivery_engagement", "value_prop_clarity", "relevance", "discovery_progression"]


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def quote_fidelity(verdict, transcript_text):
    hits = total = 0
    tnorm = norm(transcript_text)
    for seller in verdict.get("sellers", {}).values():
        for crit in seller.get("criteria", {}).values():
            for ev in crit.get("evidence", []):
                q = norm(ev.get("quote", ""))
                if len(q) < 10:
                    continue
                total += 1
                hits += q in tnorm
    for buyer in verdict.get("buyers", {}).values():
        for sig in buyer.get("signals", []):
            q = norm(sig.get("quote", ""))
            if len(q) < 10:
                continue
            total += 1
            hits += q in tnorm
    return hits, total


pairs = {slugify(p): (r, n_) for p, r, n_ in find_pairs()}
scored = sorted(SCORECARDS.glob("*.json"))[:N]
backend = os.environ.get("JUDGE_BACKEND", "claude")
model = os.environ.get("JUDGE_MODEL", "opus" if backend == "claude" else "?")
print(f"evaluating judge backend={backend} model={model} on {len(scored)} calls\n")

agree = {c: [0, 0] for c in CRITERIA}
interest_agree = [0, 0]
quotes = [0, 0]
json_ok = 0

for path in scored:
    ref = json.loads(path.read_text())
    slug = ref["call"]
    if slug not in pairs:
        continue
    recording, notes = pairs[slug]
    meta, turns, transcript_text = parse_gemini(notes)
    speakers = sorted({s for _, s, _ in turns})
    sellers = [s for s in speakers if s in SELLERS]
    buyers = [s for s in speakers if s not in SELLERS and s not in TEAM]
    ledgers = {s: load_ledger(s) for s in sellers}
    prompt = RUBRIC_PROMPT.format(
        meta=meta,
        sellers=", ".join(sellers) + f"  (buyers: {', '.join(buyers)})",
        acoustics=acoustics_prompt(ref["acoustics"], ledgers),
        transcript=transcript_text,
    )
    print(f"[{slug}] judging...", flush=True)
    try:
        verdict = judge(prompt)
        json_ok += 1
    except RuntimeError as e:
        print(f"  FAILED: {e}")
        continue

    for s in sellers:
        ref_crit = ref.get("sellers", {}).get(s, {}).get("criteria", {})
        new_crit = verdict.get("sellers", {}).get(s, {}).get("criteria", {})
        for c in CRITERIA:
            rv = ref_crit.get(c, {}).get("verdict")
            nv = new_crit.get(c, {}).get("verdict")
            if rv and nv:
                agree[c][1] += 1
                agree[c][0] += rv == nv
    for b in buyers:
        ri = ref.get("buyers", {}).get(b, {}).get("interest")
        ni = verdict.get("buyers", {}).get(b, {}).get("interest")
        if ri and ni:
            interest_agree[1] += 1
            interest_agree[0] += ri == ni
    h, t = quote_fidelity(verdict, transcript_text)
    quotes[0] += h
    quotes[1] += t

print(f"\n=== results: {backend} / {model} ===")
print(f"JSON validity: {json_ok}/{len(scored)}")
for c, (a, t) in agree.items():
    print(f"verdict agreement {c}: {a}/{t}" + (f" = {100*a/t:.0f}%" if t else ""))
if interest_agree[1]:
    print(f"buyer interest agreement: {interest_agree[0]}/{interest_agree[1]} = "
          f"{100*interest_agree[0]/interest_agree[1]:.0f}%")
if quotes[1]:
    print(f"quote fidelity (verbatim in transcript): {quotes[0]}/{quotes[1]} = "
          f"{100*quotes[0]/quotes[1]:.0f}%")

with open(HERE / "eval_judge_results.jsonl", "a") as f:
    f.write(json.dumps({"backend": backend, "model": model, "n": len(scored),
                        "json_ok": json_ok, "agreement": agree,
                        "interest": interest_agree, "quotes": quotes}) + "\n")
