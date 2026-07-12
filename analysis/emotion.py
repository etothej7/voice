"""Dimensional speech emotion (arousal / valence) per speaker.

Uses audEERING's wav2vec2 model fine-tuned on MSP-Podcast for dimensional
emotion regression — the same lab as openSMILE. Outputs are in [0, 1]:
  arousal: calm -> excited/energised   (the "enthusiasm" axis)
  valence: negative -> positive
  dominance: submissive -> assertive

Per speaker we report call-level means plus a start/middle/end trajectory so
"energy faded in the back half" is visible. Audio is sampled (up to
MAX_SECONDS per speaker, spread across the call) to bound compute.
"""
import wave

import numpy as np
import torch
import torch.nn as nn
from transformers import Wav2Vec2Processor
from transformers.models.wav2vec2.modeling_wav2vec2 import (
    Wav2Vec2Model,
    Wav2Vec2PreTrainedModel,
)

MODEL_ID = "audeering/wav2vec2-large-robust-12-ft-emotion-msp-dim"
SR = 16000
CHUNK_SEC = 8.0        # model input chunk
MIN_TURN_SEC = 1.5     # ignore tiny interjections
MAX_SECONDS = 180.0    # per-speaker audio budget per call


class RegressionHead(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.dense = nn.Linear(config.hidden_size, config.hidden_size)
        self.dropout = nn.Dropout(config.final_dropout)
        self.out_proj = nn.Linear(config.hidden_size, config.num_labels)

    def forward(self, features):
        x = self.dropout(features)
        x = torch.tanh(self.dense(x))
        x = self.dropout(x)
        return self.out_proj(x)


class EmotionModel(Wav2Vec2PreTrainedModel):
    def __init__(self, config):
        super().__init__(config)
        self.wav2vec2 = Wav2Vec2Model(config)
        self.classifier = RegressionHead(config)
        self.init_weights()

    def forward(self, input_values):
        hidden = self.wav2vec2(input_values)[0].mean(dim=1)
        return self.classifier(hidden)  # [arousal, dominance, valence]


_model = None
_processor = None
_device = None


def _load():
    global _model, _processor, _device
    if _model is None:
        _device = "mps" if torch.backends.mps.is_available() else "cpu"
        _processor = Wav2Vec2Processor.from_pretrained(MODEL_ID)
        _model = EmotionModel.from_pretrained(MODEL_ID).to(_device).eval()
    return _model, _processor, _device


def _read_wav(path):
    with wave.open(str(path)) as wf:
        assert wf.getframerate() == SR and wf.getnchannels() == 1
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


def speaker_emotion(wav_path, timed_turns, speakers=None):
    """timed_turns: [(start_s, end_s, speaker, text), ...] (Gemini-aligned).

    Returns {speaker: {arousal, valence, dominance, arousal_thirds, seconds}}.
    """
    model, processor, device = _load()
    audio = _read_wav(wav_path)
    call_end = max(b for _, b, _, _ in timed_turns) or 1.0

    if speakers is None:
        speakers = sorted({s for _, _, s, _ in timed_turns})

    out = {}
    for spk in speakers:
        chunks = []
        for a, b, s, _ in timed_turns:
            if s != spk:
                continue
            a2, b2 = a + 0.4, b - 0.4  # trim cross-speaker bleed at edges
            while b2 - a2 >= MIN_TURN_SEC:
                end = min(a2 + CHUNK_SEC, b2)
                chunks.append((a2, end))
                a2 = end
        if not chunks:
            continue
        total = sum(b - a for a, b in chunks)
        if total > MAX_SECONDS:  # sample evenly across the call
            keep = max(1, int(len(chunks) * MAX_SECONDS / total))
            idx = np.linspace(0, len(chunks) - 1, keep).astype(int)
            chunks = [chunks[i] for i in sorted(set(idx))]

        rows = []  # (mid_frac, dur, arousal, dominance, valence)
        with torch.no_grad():
            for a, b in chunks:
                seg = audio[int(a * SR):int(b * SR)]
                if len(seg) < SR:
                    continue
                inputs = processor(seg, sampling_rate=SR, return_tensors="pt")
                vals = model(inputs.input_values.to(device))[0].cpu().numpy()
                rows.append(((a + b) / 2 / call_end, b - a, *vals))
        if not rows:
            continue
        rows = np.array(rows)
        w = rows[:, 1]
        mean = lambda col: float(np.average(rows[:, col], weights=w))  # noqa: E731
        thirds = []
        for lo, hi in ((0, 1 / 3), (1 / 3, 2 / 3), (2 / 3, 1.01)):
            m = (rows[:, 0] >= lo) & (rows[:, 0] < hi)
            thirds.append(round(float(np.average(rows[m, 2], weights=rows[m, 1])), 3)
                          if m.any() else None)
        out[spk] = {
            "arousal": round(mean(2), 3),
            "dominance": round(mean(3), 3),
            "valence": round(mean(4), 3),
            "arousal_thirds": thirds,
            "seconds_analyzed": round(float(w.sum()), 0),
        }
    return out


def describe_trend(thirds):
    """Human-readable trajectory for the judge prompt."""
    vals = [v for v in thirds if v is not None]
    if len(vals) < 2:
        return "steady"
    delta = vals[-1] - vals[0]
    if delta <= -0.05:
        return "fading over the call"
    if delta >= 0.05:
        return "building over the call"
    return "steady"
