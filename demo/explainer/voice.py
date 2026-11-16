"""Speak the narration: one sound track, and the time of every line.

    ../../../.venv-voice/bin/python voice.py            # speak what changed
    ../../../.venv-voice/bin/python voice.py --phonemes # print, speak nothing

Writes `out/narration.wav`, `out/timeline.json` (when each scene, line,
utterance and word is heard, which `scenes.py` times its pictures by) and
`out/ontodag-explained.srt`. Every utterance is kept in `out/voice/` under
a name made from its phonemes, the voice and the speed, so a second run
speaks only what changed.

The voice says a sentence of two or three words badly when it is given
nothing else: after the full stop of "One rule." comes a murmur, which
`listen.py` hears as "One real, sir". So the script never leaves such a
sentence as an utterance of its own (run `listen.py` after changing it).

The voice is Kokoro (kokoro-onnx), which runs on this machine. It was
trained on its own phoneme spelling, so espeak's British phonemes are
turned into that spelling here, and the words espeak gets wrong are given
in `LEXICON`.
"""

import hashlib
import json
import os
import re
import sys
import wave
from pathlib import Path

import numpy as np

import narration

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
MODELS = Path(os.environ.get(
    "EXPLAINER_VOICE_MODELS", HERE.parents[2] / ".venv-voice" / "models"))
RATE = 24000

# Words espeak mispronounces, in Kokoro's British phonemes
# (Q is the vowel of "go", A of "day", I of "my", a of "cat").
LEXICON = {
    "OntoDAG": "ˈɒntQdˌaɡ",
    "DAG": "dˈaɡ",
    "acyclic": "ˌAsˈIklɪk",
    "Kyoto": "kiˈQtQ",
}

# Whole words of espeak's en-gb to say otherwise. It has the short a of the
# north in most of these, and the voice is southern and says them long; and
# it joins "idea" to a vowel after it with an r nobody wrote.
RESPELL = {
    "pˈas": "pˈɑːs", "ɡɹˈaf": "ɡɹˈɑːf", "ˈask": "ˈɑːsk", "ˈasks": "ˈɑːsks",
    "ˈansə": "ˈɑːnsə", "ˈansəz": "ˈɑːnsəz", "lˈast": "lˈɑːst",
    "kəmˈand": "kəmˈɑːnd", "kəmˈandz": "kəmˈɑːndz", "ˈaftə": "ˈɑːftə",
    "Idˈɪəɹ": "Idˈɪə",
}

# espeak's joined sounds (marked with ^) in Kokoro's spelling.
TO_KOKORO = [
    ("a^ɪ", "I"), ("a^ʊ", "W"), ("e^ɪ", "A"), ("ɔ^ɪ", "Y"), ("ə^ʊ", "Q"),
    ("d^ʒ", "ʤ"), ("t^ʃ", "ʧ"), ("e^ə", "ɛː"), ("i^ə", "ɪə"),
    ("ə^l", "ᵊl"), ("ɐ", "ə"), ("^", ""),
]

_MARKS = ",.;:?!"
_espeak = None


def _phonemize(text):
    """espeak's British phonemes for a piece of text, stress marked."""
    global _espeak
    if _espeak is None:
        import espeakng_loader
        from phonemizer.backend import EspeakBackend
        from phonemizer.backend.espeak.wrapper import EspeakWrapper
        EspeakWrapper.set_library(espeakng_loader.get_library_path())
        EspeakWrapper.set_data_path(espeakng_loader.get_data_path())
        _espeak = EspeakBackend(
            "en-gb", preserve_punctuation=True, with_stress=True, tie="^")
    return _espeak.phonemize([text])[0].strip()


def phonemes(text):
    """An utterance in the phonemes the voice was trained on."""
    pattern = "|".join(
        rf"\b{re.escape(word)}\b"
        for word in sorted(LEXICON, key=len, reverse=True))
    pieces, at = [], 0
    for match in re.finditer(pattern, text):
        before = text[at:match.start()].strip()
        if before:
            pieces.append(_convert(_phonemize(before)))
        pieces.append(LEXICON[match.group()])
        at = match.end()
    rest = text[at:].strip()
    if rest:
        pieces.append(_convert(_phonemize(rest)))
    joined = " ".join(pieces)
    return re.sub(rf"\s+([{re.escape(_MARKS)}])", r"\1", joined)


def _convert(espeak):
    for old, new in TO_KOKORO:
        espeak = espeak.replace(old, new)
    for old, new in RESPELL.items():
        espeak = re.sub(
            rf"(?<![^\s]){re.escape(old)}(?![^\s{re.escape(_MARKS)}])",
            new, espeak)
    return espeak


# ---------------------------------------------------------------- speaking

_kokoro = None


def speak(phoneme_text):
    """The utterance as samples, from the cache or freshly spoken."""
    key = f"{narration.VOICE}|{narration.SPEED}|{phoneme_text}"
    path = OUT / "voice" / (hashlib.sha256(key.encode()).hexdigest()[:20]
                            + ".npy")
    if path.exists():
        return np.load(path)
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro
        _kokoro = Kokoro(str(MODELS / "kokoro-v1.0.onnx"),
                         str(MODELS / "voices-v1.0.bin"))
    audio, rate = _kokoro.create(
        phoneme_text, voice=narration.VOICE, speed=narration.SPEED,
        lang="en-gb", is_phonemes=True, trim=True)
    assert rate == RATE, rate
    audio = _level(_trim(np.asarray(audio, dtype=np.float32)))
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, audio)
    return audio


def _loudness(audio, frame=RATE // 100):
    usable = len(audio) // frame * frame
    return np.sqrt((audio[:usable].reshape(-1, frame) ** 2).mean(1))


def _trim(audio, margin=0.03, fade=0.008):
    """Cut the silence at both ends, and fade the cut."""
    loud = _loudness(audio)
    heard = np.nonzero(loud > loud.max() * 10 ** (-38 / 20))[0]
    frame = RATE // 100
    first = max(0, heard[0] * frame - int(margin * RATE))
    last = min(len(audio), (heard[-1] + 1) * frame + int(margin * RATE))
    audio = audio[first:last].copy()
    ramp = np.linspace(0.0, 1.0, int(fade * RATE), dtype=np.float32)
    audio[:len(ramp)] *= ramp
    audio[-len(ramp):] *= ramp[::-1]
    return audio


def _level(audio, target=0.075):
    """Bring every utterance to the same loudness while it speaks."""
    loud = _loudness(audio)
    speaking = loud[loud > loud.max() * 10 ** (-30 / 20)]
    gain = target / max(float(np.sqrt((speaking ** 2).mean())), 1e-6)
    return audio * min(max(gain, 0.6), 1.6)


# ------------------------------------------------------------ word timings

def _silences(audio, shortest=0.085):
    """The pauses inside an utterance, as (start, end) in seconds."""
    loud = _loudness(audio)
    quiet = loud < loud.max() * 10 ** (-32 / 20)
    runs, start = [], None
    for index, is_quiet in enumerate(list(quiet) + [False]):
        if is_quiet and start is None:
            start = index
        elif not is_quiet and start is not None:
            if start > 0 and index < len(quiet) \
                    and (index - start) * 0.01 >= shortest:
                runs.append((start * 0.01, index * 0.01))
            start = None
    return runs


def _length(word):
    """About how long a word takes to say: its syllables, and its letters."""
    letters = re.sub(r"[^a-z]", "", word.lower())
    syllables = len(re.findall(r"[aeiouy]+", letters))
    if letters.endswith("e") and not letters.endswith("le") and syllables > 1:
        syllables -= 1
    return max(syllables, 1) + 0.12 * max(len(letters), 1)


def word_times(text, audio):
    """When each word of an utterance is heard: [(word, start, end)].

    The model reports no timings, so they are estimated. Time runs in
    proportion to the syllables spoken (a word before a mark a little
    longer), and the pauses in the sound are matched to the punctuation
    marks: of all the ways to give each mark a pause or none, in order,
    the one that leaves the speech between pauses nearest to its share.
    """
    total = len(audio) / RATE
    tokens = re.findall(rf"[^\s{re.escape(_MARKS)}]+|[{re.escape(_MARKS)}]",
                        text)
    weights = [0.0 if token in _MARKS else _length(token)
               + (0.5 if tokens[index + 1:index + 2] != [] and
                  tokens[index + 1] in _MARKS else 0.0)
               for index, token in enumerate(tokens)]
    whole = sum(weights) or 1.0
    marks, spoken = [], 0.0             # (weight spoken before it, the mark)
    for token, weight in zip(tokens[:-1], weights[:-1]):
        spoken += weight
        if token in _MARKS and 0 < spoken < whole:
            marks.append((spoken, token))
    pauses = _silences(audio, 0.05)

    def cost(chosen):
        """How badly a choice of pauses (one or None per mark) fits."""
        used = [pause for pause in chosen if pause is not None]
        pace = (total - sum(end - start for start, end in used)) / whole
        badness, at_weight, at_time = 0.0, 0.0, 0.0
        for (weight, mark), pause in zip(marks, chosen):
            if pause is None:           # a full stop is rarely run through
                badness += 0.25 if mark in ".?!:" else 0.04
                continue
            due = (weight - at_weight) * pace
            badness += (pause[0] - at_time - due) ** 2 / max(due, 0.3)
            badness -= 0.3 * (pause[1] - pause[0])
            at_weight, at_time = weight, pause[1]
        due = (whole - at_weight) * pace
        return badness + (total - at_time - due) ** 2 / max(due, 0.3)

    def choices(mark, first):
        if mark == len(marks):
            yield []
            return
        for rest in choices(mark + 1, first):
            yield [None] + rest
        for index in range(first, len(pauses)):
            for rest in choices(mark + 1, index + 1):
                yield [pauses[index]] + rest

    best = min(choices(0, 0), key=cost) if len(marks) <= 6 else []
    anchors = [(0.0, 0.0, 0.0)]
    anchors += [(weight, pause[0], pause[1])
                for (weight, _), pause in zip(marks, best) if pause]
    anchors.append((whole, total, total))

    def when(amount, opening):
        """The time `amount` of the weight is spoken; a word that opens
        just after a pause opens at the pause's end."""
        for (w0, _, t0), (w1, t1, _) in zip(anchors, anchors[1:]):
            if amount < w1 or (amount == w1 and not opening):
                if w1 <= w0:
                    return t0
                return t0 + (amount - w0) / (w1 - w0) * (t1 - t0)
        return total

    words, spoken = [], 0.0
    for token, weight in zip(tokens, weights):
        if token not in _MARKS:
            words.append((token, round(when(spoken, True), 3),
                          round(when(spoken + weight, False), 3)))
        spoken += weight
    return words


# ---------------------------------------------------------------- the film

def build():
    track, clock = [], 0.0
    timeline = {"voice": narration.VOICE, "speed": narration.SPEED,
                "scenes": {}, "lines": {}, "order": []}

    def silence(seconds):
        nonlocal clock
        track.append(np.zeros(int(round(seconds * RATE)), dtype=np.float32))
        clock += len(track[-1]) / RATE

    by_scene = {}
    for scene, line_id, parts in narration.lines():
        by_scene.setdefault(scene, []).append((line_id, parts))

    for scene, entries in by_scene.items():
        scene_start = clock
        silence(narration.SCENE_LEAD)
        for number, (line_id, parts) in enumerate(entries):
            line = {"scene": scene, "start": round(clock, 3),
                    "text": " ".join(parts), "utterances": [], "words": []}
            for index, part in enumerate(parts):
                if len(part.split()) < 4:
                    raise ValueError(
                        f"{line_id}: {part!r} is too short to be spoken on "
                        "its own; join it to its neighbour in narration.py")
                spoken = phonemes(part)
                audio = speak(spoken)
                start = clock
                track.append(audio)
                clock += len(audio) / RATE
                line["utterances"].append({
                    "text": part, "phonemes": spoken,
                    "start": round(start, 3), "end": round(clock, 3)})
                line["words"] += [
                    (word, round(start + t0, 3), round(start + t1, 3))
                    for word, t0, t1 in word_times(part, audio)]
                if index + 1 < len(parts):
                    silence(narration.PAUSE)
            line["end"] = round(clock, 3)
            timeline["lines"][line_id] = line
            timeline["order"].append(line_id)
            after = narration.AFTER.get(line_id)
            if number + 1 < len(entries):
                silence(narration.LINE_GAP if after is None else after)
            else:
                silence(narration.SCENE_TAIL if after is None else after)
        timeline["scenes"][scene] = {"start": round(scene_start, 3),
                                     "end": round(clock, 3)}

    audio = np.concatenate(track)
    timeline["duration"] = round(len(audio) / RATE, 3)
    OUT.mkdir(exist_ok=True)
    with wave.open(str(OUT / "narration.wav"), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(
            (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes())
    (OUT / "timeline.json").write_text(
        json.dumps(timeline, ensure_ascii=False, indent=1))
    (OUT / "ontodag-explained.srt").write_text(subtitles(timeline))
    return timeline


def subtitles(timeline):
    """The narration as SubRip captions, one for each utterance."""
    def stamp(seconds):
        millis = int(round(seconds * 1000))
        return "%02d:%02d:%02d,%03d" % (
            millis // 3600000, millis // 60000 % 60,
            millis // 1000 % 60, millis % 1000)

    captions = []
    for line_id in timeline["order"]:
        for utterance in timeline["lines"][line_id]["utterances"]:
            captions.append("%d\n%s --> %s\n%s\n" % (
                len(captions) + 1, stamp(utterance["start"]),
                stamp(utterance["end"] + 0.25), utterance["text"]))
    return "\n".join(captions)


if __name__ == "__main__":
    if "--phonemes" in sys.argv:
        for _, line_id, parts in narration.lines():
            for part in parts:
                print(f"{line_id}  {part}\n    {phonemes(part)}")
        sys.exit()
    made = build()
    spoken = sum(u["end"] - u["start"] for line in made["lines"].values()
                 for u in line["utterances"])
    words = sum(len(line["text"].split()) for line in made["lines"].values())
    print("%d lines, %d words, %.0f s spoken (%.0f words a minute), "
          "%.0f s in all" % (len(made["lines"]), words, spoken,
                             words / spoken * 60, made["duration"]))
