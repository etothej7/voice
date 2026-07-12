"""Run openSMILE eGeMAPSv02 over meeting audio and compute engaged-delivery metrics."""
import json
import sys

import numpy as np
import opensmile
import pandas as pd

AUDIO_DIR = "/private/tmp/claude-501/-Users-edstockman-Documents-GitHub-voice/d8d5eda7-6ab4-4021-960b-9d1c53fa23f0/scratchpad/audio"
OUT_DIR = "/private/tmp/claude-501/-Users-edstockman-Documents-GitHub-voice/d8d5eda7-6ab4-4021-960b-9d1c53fa23f0/scratchpad/results"

MEETINGS = {
    "flock": f"{AUDIO_DIR}/flock.wav",
    "freightplus": f"{AUDIO_DIR}/freightplus.wav",
    "mode": f"{AUDIO_DIR}/mode.wav",
}

FRAME_SEC = 0.01  # eGeMAPS LLD frame step


def speech_mask(loudness, f0, frame_sec=FRAME_SEC):
    """Speech-activity mask: voiced frames (F0>0) dilated +/-200ms to catch
    unvoiced consonants, OR loudness above an adaptive floor."""
    voiced = f0 > 0
    # dilate voiced regions by 200ms each side
    k = int(0.2 / frame_sec)
    kernel = np.ones(2 * k + 1)
    dilated = np.convolve(voiced.astype(float), kernel, mode="same") > 0
    # adaptive loudness floor: midpoint between silence floor and speech level
    loud_speech = np.percentile(loudness[dilated], 50) if dilated.any() else 0
    loud_floor = np.percentile(loudness, 10)
    thresh = loud_floor + 0.15 * (loud_speech - loud_floor)
    active = dilated & (loudness > thresh)
    return active


def segments_from_mask(mask, frame_sec=FRAME_SEC, min_gap_sec=0.3):
    """Merge active frames into speech segments; gaps < min_gap join."""
    idx = np.where(mask)[0]
    if len(idx) == 0:
        return []
    segs = []
    start = prev = idx[0]
    max_gap = int(min_gap_sec / frame_sec)
    for i in idx[1:]:
        if i - prev > max_gap:
            segs.append((start * frame_sec, (prev + 1) * frame_sec))
            start = i
        prev = i
    segs.append((start * frame_sec, (prev + 1) * frame_sec))
    return segs


def count_loudness_peaks(loudness, mask, frame_sec=FRAME_SEC):
    """Syllable-rate proxy: local maxima in smoothed loudness during speech."""
    k = int(0.05 / frame_sec)  # 50ms smoothing
    sm = np.convolve(loudness, np.ones(2 * k + 1) / (2 * k + 1), mode="same")
    peaks = 0
    floor = np.percentile(sm[mask], 25) if mask.any() else 0
    for i in range(1, len(sm) - 1):
        if mask[i] and sm[i] > sm[i - 1] and sm[i] >= sm[i + 1] and sm[i] > floor:
            peaks += 1
    return peaks


def window_metrics(lld, win_sec=60):
    """Per-window engaged-delivery metrics from LLDs."""
    loudness = lld["Loudness_sma3"].to_numpy()
    f0 = lld["F0semitoneFrom27.5Hz_sma3nz"].to_numpy()
    n = len(loudness)
    mask = speech_mask(loudness, f0)
    rows = []
    win = int(win_sec / FRAME_SEC)
    for w0 in range(0, n, win):
        w1 = min(w0 + win, n)
        if w1 - w0 < win // 2:
            break
        m = mask[w0:w1]
        ld = loudness[w0:w1]
        f = f0[w0:w1]
        voiced = f > 0
        speech_time = m.sum() * FRAME_SEC
        total_time = (w1 - w0) * FRAME_SEC
        segs = segments_from_mask(m)
        pauses = []
        for (a0, a1), (b0, b1) in zip(segs, segs[1:]):
            pauses.append(b0 - a1)
        rows.append({
            "t_min": round(w0 * FRAME_SEC / 60, 2),
            "speech_ratio": speech_time / total_time,
            "pause_ratio": 1 - speech_time / total_time,
            "loudness_mean": float(ld[m].mean()) if m.any() else 0.0,
            "loudness_cv": float(ld[m].std() / ld[m].mean()) if m.any() and ld[m].mean() > 0 else 0.0,
            "f0_std_semitones": float(f[voiced].std()) if voiced.sum() > 10 else 0.0,
            "f0_range_1090": float(np.percentile(f[voiced], 90) - np.percentile(f[voiced], 10)) if voiced.sum() > 10 else 0.0,
            "peaks_per_speech_sec": count_loudness_peaks(ld, m) / speech_time if speech_time > 0 else 0.0,
            "mean_pause_sec": float(np.mean(pauses)) if pauses else 0.0,
        })
    return pd.DataFrame(rows), mask


def overall_metrics(lld, mask):
    loudness = lld["Loudness_sma3"].to_numpy()
    f0 = lld["F0semitoneFrom27.5Hz_sma3nz"].to_numpy()
    voiced = f0 > 0
    total_time = len(loudness) * FRAME_SEC
    speech_time = mask.sum() * FRAME_SEC
    segs = segments_from_mask(mask)
    pauses = [b0 - a1 for (a0, a1), (b0, b1) in zip(segs, segs[1:])]
    long_pauses = [p for p in pauses if p >= 1.0]
    return {
        "duration_min": round(total_time / 60, 1),
        "speech_time_min": round(speech_time / 60, 1),
        "speech_ratio": round(speech_time / total_time, 3),
        "pause_ratio": round(1 - speech_time / total_time, 3),
        "n_speech_segments": len(segs),
        "mean_pause_sec": round(float(np.mean(pauses)), 2) if pauses else 0,
        "n_pauses_over_1s": len(long_pauses),
        "loudness_mean": round(float(loudness[mask].mean()), 3),
        "loudness_cv": round(float(loudness[mask].std() / loudness[mask].mean()), 3),
        "f0_mean_semitones": round(float(f0[voiced].mean()), 2),
        "f0_std_semitones": round(float(f0[voiced].std()), 2),
        "f0_range_1090_semitones": round(float(np.percentile(f0[voiced], 90) - np.percentile(f0[voiced], 10)), 2),
        "peaks_per_speech_sec": round(count_loudness_peaks(loudness, mask) / speech_time, 2),
    }


def main():
    import os
    os.makedirs(OUT_DIR, exist_ok=True)

    smile_lld = opensmile.Smile(
        feature_set=opensmile.FeatureSet.eGeMAPSv02,
        feature_level=opensmile.FeatureLevel.LowLevelDescriptors,
    )
    smile_func = opensmile.Smile(
        feature_set=opensmile.FeatureSet.eGeMAPSv02,
        feature_level=opensmile.FeatureLevel.Functionals,
    )

    summary = {}
    for name, path in MEETINGS.items():
        print(f"[{name}] extracting LLDs...", flush=True)
        lld = smile_lld.process_file(path)
        lld = lld.reset_index(drop=True)
        print(f"[{name}] {len(lld)} frames; computing metrics...", flush=True)
        windows, mask = window_metrics(lld)
        windows.to_csv(f"{OUT_DIR}/{name}_windows.csv", index=False)
        summary[name] = overall_metrics(lld, mask)

        print(f"[{name}] extracting functionals...", flush=True)
        func = smile_func.process_file(path)
        keep = [c for c in func.columns if any(k in c for k in (
            "loudnessPeaksPerSec", "VoicedSegmentsPerSec", "MeanVoicedSegmentLengthSec",
            "MeanUnvoicedSegmentLength", "F0semitone", "loudness_sma3_amean",
            "loudness_sma3_stddevNorm", "loudness_sma3_pctlrange",
        ))]
        summary[name]["egemaps_functionals"] = {
            c: round(float(func[c].iloc[0]), 4) for c in keep
        }
        print(f"[{name}] done", flush=True)

    with open(f"{OUT_DIR}/summary.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "egemaps_functionals"} for k, v in summary.items()}, indent=2))


if __name__ == "__main__":
    main()
