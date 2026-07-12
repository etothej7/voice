"""Full eGeMAPS feature capture: all 88 functionals per speaker per call.

Each speaker's turns (edge-trimmed, >=1.5s) are concatenated and the complete
eGeMAPSv02 functional set is computed over that audio. Temporal features are
approximate at concatenation joins, but the method is identical for every
speaker/call so values are comparable across the dataset.

Output: analysis/features/<call-slug>.json  {speaker: {feature: value, ...}}
Combine + mine with mine_features.py.
"""
import wave

import numpy as np
import opensmile

SR = 16000
MIN_TURN_SEC = 1.5

_smile = None


def _get_smile():
    global _smile
    if _smile is None:
        _smile = opensmile.Smile(
            feature_set=opensmile.FeatureSet.eGeMAPSv02,
            feature_level=opensmile.FeatureLevel.Functionals,
        )
    return _smile


def _read_wav(path):
    with wave.open(str(path)) as wf:
        assert wf.getframerate() == SR and wf.getnchannels() == 1
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


def speaker_functionals(wav_path, timed_turns, speakers=None):
    """-> {speaker: {feature_name: float, ...}} for all 88 eGeMAPS functionals."""
    smile = _get_smile()
    audio = _read_wav(wav_path)
    if speakers is None:
        speakers = sorted({s for _, _, s, _ in timed_turns})

    out = {}
    for spk in speakers:
        segs = []
        for a, b, s, _ in timed_turns:
            if s != spk:
                continue
            a2, b2 = a + 0.4, b - 0.4
            if b2 - a2 < MIN_TURN_SEC:
                continue
            segs.append(audio[int(a2 * SR):int(b2 * SR)])
        if not segs:
            continue
        signal = np.concatenate(segs)
        if len(signal) < SR * 5:  # need a few seconds for stable functionals
            continue
        df = smile.process_signal(signal, SR)
        out[spk] = {c: round(float(df[c].iloc[0]), 5) for c in df.columns}
    return out
