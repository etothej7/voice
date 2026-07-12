"""Call scorecard pipeline.

Scans meetings/ for (recording, "Notes by Gemini" .docx) pairs and, for each
call not yet scored, produces:
  - analysis/scorecards/<slug>.json  - rubric verdicts w/ quoted evidence + one
    coaching action per seller, buyer interest signals, acoustic evidence
  - analysis/ledger/<rep>.json       - append-only per-rep history; acoustic
    baseline activates at min_calls_for_baseline calls

The rubric judge runs through the local `claude` CLI (headless), so it uses
the machine's existing Claude Code auth - no API key required.

Usage:  ./venv/bin/python pipeline.py            (from analysis/)
        ./venv/bin/python pipeline.py --force    (rescore everything)
"""
import html
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
import opensmile

from analyze import FRAME_SEC, speech_mask, count_loudness_peaks

HERE = Path(__file__).resolve().parent
MEETINGS = HERE.parent / "meetings"
SCORECARDS = HERE / "scorecards"
LEDGER = HERE / "ledger"
CACHE = HERE / ".cache"

RUBRIC_VERSION = "v2-2026-07-10"  # v2: adds dimensional emotion (arousal/valence) evidence
CONFIG = json.loads((HERE / "sellers.json").read_text())
SELLERS = set(CONFIG["sellers"])
TEAM = set(CONFIG.get("team", []))  # Optimus staff: never graded, never buyers
BASELINE_N = CONFIG["min_calls_for_baseline"]

TS = re.compile(r"^(\d{2}):(\d{2}):(\d{2})$")
TURN = re.compile(r"^([A-Z][A-Za-z .'-]+): ?(.*)$")

RUBRIC_PROMPT = """You are scoring a recorded sales call for a sales manager. \
Judge only from the transcript and the acoustic evidence provided. Be specific \
and cite exact quotes with their timestamps; do not invent quotes.

Score each SELLER on four criteria. For each criterion give:
- verdict: "pass" or "needs_improvement"
- explanation: one or two sentences
- evidence: 1-3 items, each {{"timestamp": "HH:MM:SS", "quote": "verbatim words"}}

Criteria:
1. delivery_engagement - Did the seller sound prepared, attentive, and \
responsive to what the buyer actually said (not reciting a script)? Use the \
acoustic evidence (pitch variation, pace, energy consistency vs the rep's own \
baseline when available) as supporting signal, and weigh responsiveness in the \
transcript most.
2. value_prop_clarity - Could a neutral listener explain, in one sentence, why \
this prospect should care? Quantified, concrete claims beat generic ones.
3. relevance - Was the pitch tailored to this prospect's company, freight \
network, lanes, capacity, or the buyer's role? Generic pitches fail this.
4. discovery_progression - Did the seller ask productive questions and move \
toward a concrete, dated next step?

Also give each seller exactly one coaching_action: the single most valuable \
behavior change for their next call, phrased as an instruction.

Then rate each BUYER's interest: level "strong" | "moderate" | "weak", with \
2-4 signals (own-words commitments, buyer-owned next steps, question depth, \
objections) each backed by a quote+timestamp.

A quiet or low-key seller who asks sharp questions and lands a clear value \
prop must NOT be marked down on delivery for tone alone.

Respond with ONLY valid JSON (no markdown fences) in exactly this shape:
{{
  "call_summary": "2-3 sentences",
  "sellers": {{
    "<seller name>": {{
      "criteria": {{
        "delivery_engagement": {{"verdict": "...", "explanation": "...", "evidence": [...]}},
        "value_prop_clarity":  {{"verdict": "...", "explanation": "...", "evidence": [...]}},
        "relevance":           {{"verdict": "...", "explanation": "...", "evidence": [...]}},
        "discovery_progression": {{"verdict": "...", "explanation": "...", "evidence": [...]}}
      }},
      "coaching_action": "..."
    }}
  }},
  "buyers": {{
    "<buyer name>": {{"interest": "...", "signals": [{{"signal": "...", "timestamp": "...", "quote": "..."}}]}}
  }}
}}

=== CALL METADATA ===
{meta}

=== SELLERS ON THIS CALL ===
{sellers}

=== ACOUSTIC EVIDENCE (per speaker, from openSMILE eGeMAPS) ===
{acoustics}

=== TRANSCRIPT (timestamps are HH:MM:SS from recording start) ===
{transcript}
"""


def slugify(prefix: str) -> str:
    s = re.sub(r"optimus|_|\s+", " ", prefix.lower()).strip()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return re.sub(r"-+", "-", s)


def docx_lines(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    lines = []
    for p in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        text = html.unescape("".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S))).strip()
        if text:
            lines.append(text)
    return lines


def parse_gemini(path: Path):
    """-> (meta_text, transcript_turns, transcript_lines_for_prompt)"""
    lines = docx_lines(path)
    try:
        i0 = next(i for i, l in enumerate(lines) if l.strip().endswith("- Transcript"))
    except StopIteration:
        raise SystemExit(f"no transcript section in {path.name}")
    meta = "\n".join(lines[1:i0][:40])  # notes/summary/next-steps before transcript

    turns, prompt_lines = [], []
    cur_t = None
    for line in lines[i0 + 1:]:
        line = line.strip()
        m = TS.match(line)
        if m:
            cur_t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            prompt_lines.append(f"[{line}]")
            continue
        m = TURN.match(line)
        if m and cur_t is not None:
            turns.append([cur_t, m.group(1).strip(), m.group(2)])
            prompt_lines.append(f"{m.group(1).strip()}: {m.group(2)}")
        elif turns and cur_t is not None and line:
            turns[-1][2] += " " + line
            prompt_lines.append(line)
    return meta, turns, "\n".join(prompt_lines)


def estimate_turn_times(turns):
    """Distribute each timestamp block's span across its turns by word count."""
    blocks = {}
    for t0, spk, txt in turns:
        blocks.setdefault(t0, []).append((spk, txt))
    stamps = sorted(blocks)
    timed = []
    for i, t0 in enumerate(stamps):
        t1 = stamps[i + 1] if i + 1 < len(stamps) else t0 + 60
        blk = blocks[t0]
        wc = [max(1, len(t.split())) for _, t in blk]
        total, t = sum(wc), t0
        for (spk, txt), w in zip(blk, wc):
            dur = (t1 - t0) * w / total
            timed.append((t, t + dur, spk, txt))
            t += dur
    return timed


def extract_audio(recording: Path, slug: str) -> Path:
    CACHE.mkdir(exist_ok=True)
    wav = CACHE / f"{slug}.wav"
    if not wav.exists():
        print(f"   extracting audio -> {wav.name}", flush=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(recording),
                        "-vn", "-ac", "1", "-ar", "16000", str(wav)], check=True)
    return wav


def speaker_acoustics(wav: Path, timed_turns):
    smile = opensmile.Smile(feature_set=opensmile.FeatureSet.eGeMAPSv02,
                            feature_level=opensmile.FeatureLevel.LowLevelDescriptors)
    lld = smile.process_file(str(wav)).reset_index(drop=True)
    loudness = lld["Loudness_sma3"].to_numpy()
    f0 = lld["F0semitoneFrom27.5Hz_sma3nz"].to_numpy()
    mask = speech_mask(loudness, f0)
    n = len(loudness)

    speakers = sorted({s for _, _, s, _ in timed_turns})
    out = {}
    for s in speakers:
        m = np.zeros(n, bool)
        for a, b, spk, _ in timed_turns:
            if spk != s:
                continue
            a2, b2 = a + 0.4, b - 0.4  # trim edges to limit cross-speaker bleed
            if b2 - a2 < 0.6:
                continue
            m[int(a2 / FRAME_SEC):min(int(b2 / FRAME_SEC), n)] = True
        m &= mask
        voiced = m & (f0 > 0)
        ld = loudness[m]
        words = sum(len(t.split()) for _, _, spk, t in timed_turns if spk == s)
        out[s] = {
            "words": words,
            "questions": sum(t.count("?") for _, _, spk, t in timed_turns if spk == s),
            "speech_min": round(m.sum() * FRAME_SEC / 60, 1),
            "loudness_mean": round(float(ld.mean()), 3) if m.any() else None,
            "loudness_cv": round(float(ld.std() / ld.mean()), 3) if m.any() and ld.mean() > 0 else None,
            "f0_std_semitones": round(float(f0[voiced].std()), 2) if voiced.sum() > 100 else None,
            "pace_peaks_per_sec": round(count_loudness_peaks(loudness, m) / (m.sum() * FRAME_SEC), 2) if m.sum() > 100 else None,
        }
    total_words = sum(v["words"] for v in out.values())
    for v in out.values():
        v["talk_share_pct"] = round(100 * v["words"] / total_words, 1) if total_words else 0
    return out


def add_emotion(wav, timed_turns, acoustics):
    """Merge arousal/valence per speaker into the acoustics dict (best-effort)."""
    try:
        from emotion import speaker_emotion
        emo = speaker_emotion(wav, timed_turns, speakers=list(acoustics))
        for name, vals in emo.items():
            acoustics[name].update(vals)
    except Exception as e:  # noqa: BLE001 - emotion is additive, never fatal
        print(f"   !! emotion model unavailable ({e}); continuing without it", flush=True)


def rep_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def load_ledger(name: str) -> dict:
    p = LEDGER / f"{rep_slug(name)}.json"
    if p.exists():
        return json.loads(p.read_text())
    return {"rep": name, "calls": []}


def baseline_of(ledger: dict):
    """mean/std of acoustics across calls; active only at BASELINE_N calls."""
    metrics = ["loudness_mean", "loudness_cv", "f0_std_semitones",
               "pace_peaks_per_sec", "arousal", "valence"]
    vals = {m: [c[m] for c in ledger["calls"] if c.get(m) is not None] for m in metrics}
    n = min((len(v) for v in vals.values()), default=0)
    base = {"n_calls": len(ledger["calls"]), "active": n >= BASELINE_N}
    for m in metrics:
        if vals[m]:
            base[m] = {"mean": round(float(np.mean(vals[m])), 3),
                       "std": round(float(np.std(vals[m])), 3)}
    return base


def acoustics_prompt(acoustics: dict, ledgers: dict) -> str:
    lines = []
    for name, a in acoustics.items():
        lines.append(f"{name}: talk share {a['talk_share_pct']}% of words, "
                     f"{a['questions']} questions, ~{a['speech_min']} min speaking, "
                     f"pitch variation {a['f0_std_semitones']} semitones (st), "
                     f"pace {a['pace_peaks_per_sec']} syllable-peaks/s, "
                     f"volume consistency CV {a['loudness_cv']} (lower=steadier)")
        if a.get("arousal") is not None:
            from emotion import describe_trend
            thirds = a.get("arousal_thirds") or []
            lines.append(f"  vocal emotion (0-1 scale, speech emotion model): "
                         f"arousal {a['arousal']} (calm->excited), "
                         f"valence {a['valence']} (negative->positive); "
                         f"arousal by call thirds {thirds} - {describe_trend(thirds)}")
        if name in ledgers:
            base = baseline_of(ledgers[name])
            if base["active"] and a.get("f0_std_semitones") is not None:
                z = {m: round((a[m] - base[m]["mean"]) / base[m]["std"], 1)
                     for m in ("f0_std_semitones", "loudness_cv", "pace_peaks_per_sec",
                               "arousal", "valence")
                     if a.get(m) is not None and base.get(m, {}).get("std")}
                lines.append(f"  vs own {base['n_calls']}-call baseline (z-scores): {z}")
            else:
                lines.append(f"  baseline: provisional ({base['n_calls']} call(s) banked, "
                             f"needs {BASELINE_N}) - judge tone gently, do not penalize vs other people")
        lines.append("  NOTE: absolute loudness is not comparable between people (different mics).")
    return "\n".join(lines)


def _strip_fences(text: str) -> str:
    return re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.M).strip()


def judge(prompt: str) -> dict:
    """Rubric judge. Backend selected by env:
    JUDGE_BACKEND unset/"claude"  -> local `claude` CLI (Anthropic, default)
    JUDGE_BACKEND=<base url>      -> any OpenAI-compatible endpoint, e.g. a
        Qwen box serving via Ollama/vLLM/LM Studio:
        JUDGE_BACKEND=http://192.168.1.50:11434 JUDGE_MODEL=qwen2.5:72b
    """
    import os
    backend = os.environ.get("JUDGE_BACKEND", "claude")
    for attempt in range(2):
        try:
            if backend == "claude":
                r = subprocess.run(
                    ["claude", "-p", "--output-format", "json", "--model", "opus"],
                    input=prompt, capture_output=True, text=True, timeout=900)
                if r.returncode != 0:
                    print(f"   judge attempt {attempt+1} failed: {r.stderr[:300]}", flush=True)
                    continue
                text = json.loads(r.stdout)["result"]
            else:
                import requests
                resp = requests.post(
                    f"{backend.rstrip('/')}/v1/chat/completions",
                    json={
                        "model": os.environ.get("JUDGE_MODEL", ""),
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0,
                        "max_tokens": 4096,
                        "response_format": {"type": "json_object"},
                    },
                    timeout=900,
                )
                resp.raise_for_status()
                text = resp.json()["choices"][0]["message"]["content"]
            return json.loads(_strip_fences(text))
        except Exception as e:  # noqa: BLE001
            print(f"   judge attempt {attempt+1} error: {e}", flush=True)
    raise RuntimeError("rubric judge failed twice")


def find_pairs():
    pairs = []
    for notes in sorted(MEETINGS.glob("* - Notes by Gemini.docx")):
        prefix = notes.name[: -len(" - Notes by Gemini.docx")]
        recs = [p for p in MEETINGS.iterdir() if p.name.startswith(prefix + " - Recording")]
        if recs:
            pairs.append((prefix, recs[0], notes))
        else:
            print(f"!! no recording found for: {notes.name}")
    return pairs


def process_call(prefix, recording, notes, force):
    slug = slugify(prefix)
    out = SCORECARDS / f"{slug}.json"
    if out.exists() and not force:
        print(f"[{slug}] already scored, skipping (use --force to rescore)")
        return
    print(f"[{slug}] processing", flush=True)

    meta, turns, transcript_text = parse_gemini(notes)
    timed = estimate_turn_times(turns)

    speakers = sorted({s for _, s, _ in turns})
    sellers = [s for s in speakers if s in SELLERS]
    buyers = [s for s in speakers if s not in SELLERS and s not in TEAM]
    team_present = [s for s in speakers if s in TEAM and s not in SELLERS]
    if not sellers:
        print(f"   -- no configured seller among {speakers}; skipping")
        return
    if not buyers:
        print(f"   -- internal call (speakers: {speakers}); skipping")
        return

    wav = extract_audio(recording, slug)
    print("   acoustics (openSMILE eGeMAPS)...", flush=True)
    acoustics = speaker_acoustics(wav, timed)
    print("   emotion (arousal/valence)...", flush=True)
    add_emotion(wav, timed, acoustics)
    feats = None
    try:  # full 88-functional capture for pattern mining (additive, never fatal)
        from features import speaker_functionals
        feats = speaker_functionals(wav, timed, speakers=list(acoustics))
        fdir = HERE / "features"
        fdir.mkdir(exist_ok=True)
        (fdir / f"{slug}.json").write_text(json.dumps(feats, indent=1))
    except Exception as e:  # noqa: BLE001
        print(f"   !! functionals capture failed ({e}); continuing", flush=True)
    ledgers = {s: load_ledger(s) for s in sellers}

    print("   rubric judge (claude)...", flush=True)
    seller_line = ", ".join(sellers) + f"  (buyers: {', '.join(buyers)})"
    if team_present:
        seller_line += (f"\nOther Optimus team members on the call (score them neither "
                        f"as sellers nor buyers): {', '.join(team_present)}")
    prompt = RUBRIC_PROMPT.format(
        meta=meta,
        sellers=seller_line,
        acoustics=acoustics_prompt(acoustics, ledgers),
        transcript=transcript_text,
    )
    verdict = judge(prompt)

    scorecard = {
        "call": slug,
        "source": {"recording": recording.name, "notes": notes.name},
        "rubric_version": RUBRIC_VERSION,
        "acoustics": acoustics,
        **verdict,
    }
    out.write_text(json.dumps(scorecard, indent=2))
    print(f"   wrote {out.relative_to(HERE)}", flush=True)

    try:  # mirror every data point into the SQLite store (derived, never fatal)
        import db
        db.upsert_call(scorecard, feats)
        db.store_turns(slug, timed)
    except Exception as e:  # noqa: BLE001
        print(f"   !! db upsert failed ({e}); run `python db.py rebuild` later", flush=True)

    for s in sellers:
        led = ledgers[s]
        led["calls"] = [c for c in led["calls"] if c["call"] != slug]
        entry = {"call": slug, **{k: acoustics[s].get(k) for k in
                 ("talk_share_pct", "questions", "speech_min", "loudness_mean",
                  "loudness_cv", "f0_std_semitones", "pace_peaks_per_sec",
                  "arousal", "valence")}}
        crits = verdict.get("sellers", {}).get(s, {}).get("criteria", {})
        entry["rubric"] = {k: v.get("verdict") for k, v in crits.items()}
        led["calls"].append(entry)
        led["baseline"] = baseline_of(led)
        (LEDGER / f"{rep_slug(s)}.json").write_text(json.dumps(led, indent=2))
        state = "ACTIVE" if led["baseline"]["active"] else \
            f"provisional {led['baseline']['n_calls']}/{BASELINE_N}"
        print(f"   ledger {s}: {len(led['calls'])} calls, baseline {state}", flush=True)


def main():
    force = "--force" in sys.argv
    SCORECARDS.mkdir(exist_ok=True)
    LEDGER.mkdir(exist_ok=True)

    failures = []
    for prefix, recording, notes in find_pairs():
        try:
            process_call(prefix, recording, notes, force)
        except Exception as e:  # noqa: BLE001 - keep the batch going
            failures.append((slugify(prefix), str(e)))
            print(f"[{slugify(prefix)}] FAILED: {e}", flush=True)

    try:
        from disposition import update_ledgers
        print("\nupdating engagement dispositions...")
        update_ledgers(BASELINE_N)
    except Exception as e:  # noqa: BLE001
        print(f"disposition update failed: {e}")

    if failures:
        print(f"\n{len(failures)} call(s) failed:")
        for slug, err in failures:
            print(f"  {slug}: {err}")
    print("done")


if __name__ == "__main__":
    main()
