"""Listen to the narration: write down what was said, and compare.

    ../../../.venv-voice/bin/python listen.py

Whoever builds the film may not be able to hear it, and a voice can say a
word wrong however right the script is. This transcribes every line as the
film plays it with a small speech recogniser (Whisper base.en, run by
onnxruntime on this machine) and prints those whose words differ from the
script. A difference is a thing to look at, not a verdict: the recogniser
has its own spellings (`2026`, `Onto-DAG`) and its own mistakes.
"""

import json
import re
import sys

import numpy as np

import narration
import voice

MODEL = voice.MODELS / "whisper-base.en"
RATE = 16000


def resample(audio, rate):
    """24 kHz to 16 kHz: up by two, low-pass, every third sample."""
    assert rate == 24000, rate
    up = np.zeros(len(audio) * 2, dtype=np.float32)
    up[::2] = audio
    taps = np.arange(-60, 61)
    lowpass = 2 * 0.158 * np.sinc(2 * 0.158 * taps) * np.hamming(len(taps))
    return np.convolve(up, 2 * lowpass, mode="same")[::3].astype(np.float32)


def _mel_filters(bins=80, fft=400):
    """The filter bank Whisper was trained with (Slaney's mel scale)."""
    def to_mel(hz):
        hz = np.asarray(hz, dtype=np.float64)
        return np.where(hz >= 1000.0,
                        15.0 + np.log(np.maximum(hz, 1e-9) / 1000.0)
                        / (np.log(6.4) / 27.0), hz / (200.0 / 3))

    def to_hz(mel):
        mel = np.asarray(mel, dtype=np.float64)
        return np.where(mel >= 15.0,
                        1000.0 * np.exp((np.log(6.4) / 27.0) * (mel - 15.0)),
                        mel * (200.0 / 3))

    freqs = np.linspace(0, RATE / 2, fft // 2 + 1)
    edges = to_hz(np.linspace(to_mel(0.0), to_mel(RATE / 2), bins + 2))
    widths = np.diff(edges)
    ramps = edges[:, None] - freqs[None, :]
    lower = -ramps[:-2] / widths[:-1, None]
    upper = ramps[2:] / widths[1:, None]
    bank = np.maximum(0.0, np.minimum(lower, upper))
    return (bank * (2.0 / (edges[2:] - edges[:-2]))[:, None]).astype(
        np.float32)


def features(audio):
    """Thirty seconds of audio as Whisper's log-mel picture, 80 by 3000."""
    audio = np.pad(audio[:RATE * 30], (0, max(0, RATE * 30 - len(audio))))
    padded = np.pad(audio, 200, mode="reflect")
    window = np.hanning(401)[:-1].astype(np.float32)
    count = 1 + (len(padded) - 400) // 160
    index = np.arange(400)[None, :] + 160 * np.arange(count)[:, None]
    power = np.abs(np.fft.rfft(padded[index] * window, axis=1)[:-1]) ** 2
    mel = np.log10(np.maximum(_mel_filters() @ power.T, 1e-10))
    mel = np.maximum(mel, mel.max() - 8.0)
    return ((mel + 4.0) / 4.0)[None].astype(np.float32)


class Recogniser:
    def __init__(self):
        import onnxruntime
        quiet = onnxruntime.SessionOptions()
        quiet.log_severity_level = 3
        self.encoder = onnxruntime.InferenceSession(
            str(MODEL / "encoder_model.onnx"), quiet)
        self.decoder = onnxruntime.InferenceSession(
            str(MODEL / "decoder_model.onnx"), quiet)
        tokens = json.loads((MODEL / "vocab.json").read_text())
        self.words = {number: token for token, number in tokens.items()}
        rules = json.loads((MODEL / "generation_config.json").read_text())
        self.start = [rules["decoder_start_token_id"],
                      rules["no_timestamps_token_id"]]
        self.end = rules["eos_token_id"]
        self.never = rules["suppress_tokens"]
        self.not_first = rules["begin_suppress_tokens"]

    def hear(self, audio, rate):
        """The words in a few seconds of speech."""
        heard = self.encoder.run(
            None, {"input_features": features(resample(audio, rate))})[0]
        tokens = list(self.start)
        for _ in range(120):
            logits = self.decoder.run(["logits"], {
                "input_ids": np.array([tokens], dtype=np.int64),
                "encoder_hidden_states": heard})[0][0, -1]
            logits[self.never] = -np.inf
            if len(tokens) == len(self.start):
                logits[self.not_first] = -np.inf
            best = int(logits.argmax())
            if best == self.end:
                break
            tokens.append(best)
        text = "".join(self.words.get(token, "")
                       for token in tokens[len(self.start):])
        return text.replace("Ġ", " ").strip()


# What the recogniser writes for what the script says, where both are right.
SAME = [(r"\b2026\b", "twenty twenty six"), (r"\b500\b", "five hundred"),
        (r"\b15th\b", "fifteenth"), (r"\bonto[- ]?dag\b", "ontodag"),
        (r"\bon to dag\b", "ontodag"), (r"\bone[- ]half\b", "one half")]


def plain(text):
    text = text.lower().replace("’", "'")
    for pattern, words in SAME:
        text = re.sub(pattern, words, text)
    return re.sub(r"[^a-z0-9' ]+", " ", text).split()


def main():
    ears, total, differ = Recogniser(), 0, 0
    pause = np.zeros(int(narration.PAUSE * voice.RATE), dtype=np.float32)
    for _, line_id, parts in narration.lines():
        pieces = []
        for part in parts:
            pieces += [voice.speak(voice.phonemes(part)), pause]
        heard = ears.hear(np.concatenate(pieces[:-1]), voice.RATE)
        said = " ".join(parts)
        total += 1
        if plain(heard) != plain(said):
            differ += 1
            print(f"{line_id}  said:  {said}\n    heard: {heard}")
    print(f"{total} lines, {differ} heard differently")
    return differ


if __name__ == "__main__":
    sys.exit(0 if main() == 0 else 1)
