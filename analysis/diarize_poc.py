"""POC: per-speaker attribution of the MODE call without gated models.

Speaker embeddings (speechbrain ECAPA) over sliding windows inside speech
regions -> agglomerative clustering (k=3) -> smoothed speaker turns ->
per-speaker engaged-delivery metrics from eGeMAPS LLDs + interaction stats.
Cluster->name mapping validated against Granola transcript word shares.
"""
import json

import wave

import numpy as np
import opensmile
import torch
from sklearn.cluster import AgglomerativeClustering

from analyze import FRAME_SEC, speech_mask, segments_from_mask, count_loudness_peaks

WAV = "/private/tmp/claude-501/-Users-edstockman-Documents-GitHub-voice/d8d5eda7-6ab4-4021-960b-9d1c53fa23f0/scratchpad/audio/mode.wav"
OUT = "/private/tmp/claude-501/-Users-edstockman-Documents-GitHub-voice/d8d5eda7-6ab4-4021-960b-9d1c53fa23f0/scratchpad/results/mode_speakers.json"
SR = 16000
WIN, HOP = 1.5, 0.5  # seconds

print("1/5 speech mask from eGeMAPS LLDs...", flush=True)
smile = opensmile.Smile(feature_set=opensmile.FeatureSet.eGeMAPSv02,
                        feature_level=opensmile.FeatureLevel.LowLevelDescriptors)
lld = smile.process_file(WAV).reset_index(drop=True)
loudness = lld["Loudness_sma3"].to_numpy()
f0 = lld["F0semitoneFrom27.5Hz_sma3nz"].to_numpy()
mask = speech_mask(loudness, f0)
segs = segments_from_mask(mask)
print(f"   {len(segs)} speech segments, {mask.sum()*FRAME_SEC/60:.1f} min speech", flush=True)

print("2/5 loading audio + ECAPA model...", flush=True)
with wave.open(WAV) as wf:
    assert wf.getframerate() == SR and wf.getnchannels() == 1 and wf.getsampwidth() == 2
    pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
wav = torch.from_numpy(pcm.astype(np.float32) / 32768.0)
from speechbrain.inference.speaker import EncoderClassifier
enc = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                                     run_opts={"device": "cpu"})

print("3/5 embedding windows...", flush=True)
wins = []
for a, b in segs:
    t = a
    while t + WIN <= b or (t == a and b - a > 0.6):  # short segs get one window
        w0, w1 = t, min(t + WIN, b)
        wins.append((w0, w1))
        t += HOP
        if w1 >= b:
            break
embs = []
BATCH = 64
for i in range(0, len(wins), BATCH):
    chunk = wins[i:i + BATCH]
    maxlen = max(int((b - a) * SR) for a, b in chunk)
    batch = torch.zeros(len(chunk), maxlen)
    lens = torch.zeros(len(chunk))
    for j, (a, b) in enumerate(chunk):
        seg = wav[int(a * SR):int(b * SR)]
        batch[j, :len(seg)] = seg
        lens[j] = len(seg) / maxlen
    with torch.no_grad():
        e = enc.encode_batch(batch, lens).squeeze(1)
    embs.append(e.cpu().numpy())
embs = np.concatenate(embs)
embs = embs / np.linalg.norm(embs, axis=1, keepdims=True)
print(f"   {len(wins)} windows embedded", flush=True)

print("4/5 clustering k=3 + smoothing...", flush=True)
labels = AgglomerativeClustering(n_clusters=3, metric="cosine", linkage="average").fit_predict(embs)

# median-smooth labels over each contiguous window run (windows are time-ordered)
centers = np.array([(a + b) / 2 for a, b in wins])
order = np.argsort(centers)
sm = labels.copy()
for k in range(2, len(order) - 2):
    idx = order[k - 2:k + 3]
    vals, counts = np.unique(labels[idx], return_counts=True)
    sm[order[k]] = vals[np.argmax(counts)]
labels = sm

# frame-level speaker attribution: nearest window center within 1s, speech frames only
n = len(loudness)
spk_frame = np.full(n, -1)
times = np.arange(n) * FRAME_SEC
ci = np.searchsorted(centers[order], times)
for i in range(n):
    if not mask[i]:
        continue
    cands = []
    for j in (ci[i] - 1, ci[i]):
        if 0 <= j < len(order):
            cands.append(order[j])
    if cands:
        best = min(cands, key=lambda j: abs(centers[j] - times[i]))
        if abs(centers[best] - times[i]) < 1.0:
            spk_frame[i] = labels[best]

# build speaker turns (merge same-speaker gaps < 1s)
turns = []
cur = None
for i in range(n):
    s = spk_frame[i]
    if s >= 0:
        if cur and cur[2] == s and times[i] - cur[1] < 1.0:
            cur[1] = times[i]
        else:
            if cur:
                turns.append(tuple(cur))
            cur = [times[i], times[i], s]
if cur:
    turns.append(tuple(cur))
turns = [(a, b, s) for a, b, s in turns if b - a >= 0.4]

talk = {k: sum(b - a for a, b, s in turns if s == k) for k in range(3)}
total_talk = sum(talk.values())
print("   talk shares:", {k: f"{100*v/total_talk:.1f}%" for k, v in talk.items()}, flush=True)

print("5/5 per-speaker metrics...", flush=True)
# name mapping: smallest share = Max; of the two large, the one holding the
# single longest turn = Mike (his ~3min Heineken monologue); other = Ed
by_share = sorted(talk, key=talk.get)
small, big1, big2 = by_share[0], by_share[1], by_share[2]
longest = {k: max((b - a for a, b, s in turns if s == k), default=0) for k in range(3)}
mike = big1 if longest[big1] > longest[big2] else big2
ed = big2 if mike == big1 else big1
names = {small: "Max Riemer (Optimus)", mike: "Mike Sinkovitz (MODE)", ed: "Ed Stockman (Optimus)"}

result = {"talk_shares_transcript_truth": {"Ed": 47.8, "Mike(+Them)": 49.8, "Max": 2.4},
          "speakers": {}}
dur_total = n * FRAME_SEC
for k in range(3):
    m = spk_frame == k
    voiced = m & (f0 > 0)
    ld = loudness[m]
    myturns = [(a, b) for a, b, s in turns if s == k]
    # response latency: gap before my turn when previous turn was someone else
    lat = []
    for i, (a, b, s) in enumerate(turns[1:], 1):
        pa, pb, ps = turns[i - 1]
        if s == k and ps != k:
            lat.append(max(0.0, a - pb))
    result["speakers"][names[k]] = {
        "talk_time_min": round(talk[k] / 60, 1),
        "talk_share_pct": round(100 * talk[k] / total_talk, 1),
        "n_turns": len(myturns),
        "longest_turn_sec": round(longest[k], 1),
        "mean_turn_sec": round(float(np.mean([b - a for a, b in myturns])), 1) if myturns else 0,
        "loudness_mean": round(float(ld.mean()), 3) if m.any() else 0,
        "loudness_cv": round(float(ld.std() / ld.mean()), 3) if m.any() and ld.mean() > 0 else 0,
        "f0_std_semitones": round(float(f0[voiced].std()), 2) if voiced.sum() > 20 else 0,
        "f0_mean_semitones": round(float(f0[voiced].mean()), 2) if voiced.sum() > 20 else 0,
        "pace_peaks_per_sec": round(count_loudness_peaks(loudness, m) / talk[k], 2) if talk[k] > 0 else 0,
        "median_response_latency_sec": round(float(np.median(lat)), 2) if lat else None,
        "fast_cutins_under_300ms": int(sum(1 for g in lat if g < 0.3)),
    }

result["n_turn_switches"] = sum(1 for i in range(1, len(turns)) if turns[i][2] != turns[i - 1][2])
result["turns"] = [[round(a, 2), round(b, 2), names[s]] for a, b, s in turns]
with open(OUT, "w") as f:
    json.dump(result, f, indent=2)
print(json.dumps({k: v for k, v in result.items() if k != "turns"}, indent=2))
