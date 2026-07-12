"""Per-speaker engaged-delivery + interaction metrics from Gemini transcripts.

Gemini 'Notes' transcripts carry HH:MM:SS stamps every ~40-70s with named
speaker turns between them. Turn times are estimated by distributing each
block's span across its turns proportional to word count; openSMILE eGeMAPS
frames are then attributed to speakers (turn edges trimmed to limit bleed).
"""
import json
import re

import numpy as np
import opensmile

from analyze import FRAME_SEC, speech_mask, count_loudness_peaks

BASE = "/private/tmp/claude-501/-Users-edstockman-Documents-GitHub-voice/d8d5eda7-6ab4-4021-960b-9d1c53fa23f0/scratchpad"
MEETINGS = {
    "flock": {"wav": f"{BASE}/audio/flock.wav", "txt": f"{BASE}/gemini_flock.txt",
              "sellers": ["Max Riemer"], "buyers": ["Michael Munday"]},
    "freightplus": {"wav": f"{BASE}/audio/freightplus.wav", "txt": f"{BASE}/gemini_freightplus.txt",
                    "sellers": ["Max Riemer"], "buyers": ["Shane Duncan"]},
    "mode": {"wav": f"{BASE}/audio/mode.wav", "txt": f"{BASE}/gemini_mode.txt",
             "sellers": ["Ed Stockman", "Max Riemer"], "buyers": ["Michael Sinkovitz", "Mike Sinkovitz"]},
}
TS = re.compile(r"^(\d{2}):(\d{2}):(\d{2})$")
TURN = re.compile(r"^([A-Z][A-Za-z .'-]+): ?(.*)$")


def parse_transcript(path):
    """-> list of (start_sec, end_sec_estimated, speaker, text)"""
    lines = open(path).read().splitlines()
    # transcript section starts after the '<title> - Transcript' line
    try:
        i0 = next(i for i, l in enumerate(lines) if l.strip().endswith("- Transcript"))
    except StopIteration:
        raise SystemExit(f"no transcript section in {path}")
    blocks = []  # (t_sec, [(speaker, text), ...])
    cur_t, cur_turns = None, []
    for line in lines[i0 + 1:]:
        line = line.strip()
        m = TS.match(line)
        if m:
            if cur_t is not None and cur_turns:
                blocks.append((cur_t, cur_turns))
            cur_t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            cur_turns = []
            continue
        m = TURN.match(line)
        if m and cur_t is not None:
            cur_turns.append((m.group(1).strip(), m.group(2)))
        elif cur_turns and cur_t is not None and line:
            spk, txt = cur_turns[-1]
            cur_turns[-1] = (spk, txt + " " + line)
    if cur_t is not None and cur_turns:
        blocks.append((cur_t, cur_turns))

    turns = []
    for bi, (t0, blk) in enumerate(blocks):
        t1 = blocks[bi + 1][0] if bi + 1 < len(blocks) else t0 + 60
        span = t1 - t0
        wc = [max(1, len(t.split())) for _, t in blk]
        total = sum(wc)
        t = t0
        for (spk, txt), w in zip(blk, wc):
            dur = span * w / total
            turns.append((t, t + dur, spk, txt))
            t += dur
    return turns


def merge_speaker_turns(turns):
    """collapse consecutive same-speaker turns for interaction stats"""
    merged = []
    for a, b, s, txt in turns:
        if merged and merged[-1][2] == s:
            merged[-1][1] = b
            merged[-1][3] += " " + txt
        else:
            merged.append([a, b, s, txt])
    return merged


smile = opensmile.Smile(feature_set=opensmile.FeatureSet.eGeMAPSv02,
                        feature_level=opensmile.FeatureLevel.LowLevelDescriptors)

report = {}
for name, cfg in MEETINGS.items():
    print(f"[{name}] parsing transcript...", flush=True)
    turns = parse_transcript(cfg["txt"])
    speakers = sorted({s for _, _, s, _ in turns})
    print(f"   {len(turns)} turns, speakers: {speakers}", flush=True)

    print(f"[{name}] extracting LLDs...", flush=True)
    lld = smile.process_file(cfg["wav"]).reset_index(drop=True)
    loudness = lld["Loudness_sma3"].to_numpy()
    f0 = lld["F0semitoneFrom27.5Hz_sma3nz"].to_numpy()
    mask = speech_mask(loudness, f0)
    n = len(loudness)

    # frame attribution: trim 0.4s from each estimated turn edge to limit bleed;
    # only turns long enough to survive trimming contribute prosody frames
    spk_frame = {}
    for a, b, s, txt in turns:
        a2, b2 = a + 0.4, b - 0.4
        if b2 - a2 < 0.6:
            continue
        i0, i1 = int(a2 / FRAME_SEC), min(int(b2 / FRAME_SEC), n)
        arr = spk_frame.setdefault(s, np.zeros(n, bool))
        arr[i0:i1] = True

    merged = merge_speaker_turns(turns)
    talk_words = {s: sum(len(t.split()) for _, _, sp, t in turns if sp == s) for s in speakers}
    total_words = sum(talk_words.values())

    meeting = {"speakers": {}, "n_turn_switches": len(merged) - 1,
               "duration_min": round(n * FRAME_SEC / 60, 1)}
    for s in speakers:
        stt = [(a, b, txt) for a, b, sp, txt in merged if sp == s]
        qs = sum(t.count("?") for _, _, t in stt)
        # response latency: my turn start minus previous (other) turn end
        lat = [max(0.0, merged[i][0] - merged[i - 1][1])
               for i in range(1, len(merged)) if merged[i][2] == s]
        m = spk_frame.get(s, np.zeros(n, bool)) & mask
        voiced = m & (f0 > 0)
        ld = loudness[m]
        talk_sec = sum(b - a for a, b, _ in stt)
        meeting["speakers"][s] = {
            "role": "seller" if s in cfg["sellers"] else ("buyer" if s in cfg["buyers"] else "other"),
            "talk_share_words_pct": round(100 * talk_words[s] / total_words, 1),
            "talk_time_est_min": round(talk_sec / 60, 1),
            "n_turns": len(stt),
            "questions": qs,
            "questions_per_10min_talk": round(qs / (talk_sec / 600), 1) if talk_sec > 60 else None,
            "longest_turn_est_sec": round(max((b - a for a, b, _ in stt), default=0), 0),
            "median_response_latency_sec": round(float(np.median(lat)), 2) if lat else None,
            "prosody_frames_min": round(m.sum() * FRAME_SEC / 60, 1),
            "loudness_mean": round(float(ld.mean()), 3) if m.any() else None,
            "loudness_cv": round(float(ld.std() / ld.mean()), 3) if m.any() and ld.mean() > 0 else None,
            "f0_std_semitones": round(float(f0[voiced].std()), 2) if voiced.sum() > 100 else None,
            "pace_peaks_per_sec": round(count_loudness_peaks(loudness, m) / (m.sum() * FRAME_SEC), 2) if m.sum() > 100 else None,
        }
    report[name] = meeting
    print(f"[{name}] done", flush=True)

with open(f"{BASE}/results/per_speaker.json", "w") as f:
    json.dump(report, f, indent=2)
print(json.dumps(report, indent=2))
