# The explainer film

A film of five and a half minutes that explains OntoDAG to someone who has
never seen it: the trouble with folders and tags, filing under several
categories, the one question, the one rule, the root, merging, typed
values, proof, and where a store lives. It is drawn by the code in this
directory and narrated in British English by a voice that runs on this
machine.

    ./build.sh            # writes out/ontodag-explained.mp4 (and .srt)

`out/` is not tracked: the film is rebuilt from what is here (1920 by 1080,
30 frames a second, about 17 MB; the facts take a few seconds, the voice
five minutes the first time, the pictures two).

## What the film may say

Every command, answer and root on the screen is `odag`'s own. `facts.py`
runs the film's examples on the installed ontodag in a throwaway home and
writes what came back to `out/facts.json`; `scenes.py` draws from that
file. The checks at the end of `facts.py` are the claims the pictures and
the narration make (equal knowledge gives an equal root, a merge in either
direction gives the same root, a loop is refused, and so on), so a release
that changed one of them would stop the build, and the film would have to
change with it. The suite runs the same checks
(`tests/test_explainer.py`), so the film cannot go stale unnoticed.

The narration is `narration.py`, one line per thought. It reads no syntax
aloud; the screen shows it.

## The three steps

Each runs where what it needs is installed.

| step | file | needs |
|---|---|---|
| the facts | `facts.py` | ontodag (the family's `.venv`) |
| the voice | `voice.py` | kokoro-onnx and its model (`.venv-voice`) |
| the pictures | `render.py`, `scenes.py`, `anim.py` | the system's `python3-cairo` and `python3-gi`, the fonts Lato and Ubuntu Sans Mono, and `ffmpeg` |

`voice.py` writes the sound track and `out/timeline.json`: when every
scene, line, utterance and word is heard. `scenes.py` times every picture
against that file (`at("d3", "flight")` is when that word of line d3 is
spoken), so the pictures keep step with the voice at any pace, and a
change to the script moves them with it.

`anim.py` is a small engine: things on a stage, every property a track in
time, drawn by Cairo with type set by Pango. `Stage.paint(t)` draws the
frame of any moment, which is how the film is looked at while it is made:

    python3 render.py --still 123.6 251.6     # out/stills/0123.60.png ...
    python3 sheet.py out/sheet.png 60 65 70   # several moments on one sheet
    python3 render.py --range 100 130         # half a minute, with sound

## The voice

The voice is [Kokoro](https://huggingface.co/hexgrad/Kokoro-82M) (Apache
2.0), run by [kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx)
with `bf_emma`, one of its British speakers. Nothing leaves the machine.
To hear another speaker, or another pace, change `VOICE` or `SPEED` in
`narration.py` and build again: every picture follows the new timing.

    uv venv --python 3.12 ../../../.venv-voice
    uv pip install --python ../../../.venv-voice/bin/python \
        kokoro-onnx==0.6.1 onnxruntime==1.31.1
    # kokoro-v1.0.onnx and voices-v1.0.bin, from kokoro-onnx's release
    # "model-files-v1.0", go in ../../../.venv-voice/models/

The model files are too large for this repository (GitHub takes no file
over 100 MB), so they are fetched from where their makers publish them.
These are the ones the film was made with (sha256):

    7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5  kokoro-v1.0.onnx  (326 MB)
    bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d  voices-v1.0.bin  (28 MB)
    1cc86302d480b061452d348638064383ab41b6f3333ddd0e423532d14edaf535  whisper-base.en/encoder_model.onnx  (82 MB)
    381195952316e01d2cd5f3e51611e56959e660909a1f636de151af13166d23cc  whisper-base.en/decoder_model.onnx  (208 MB)

Three things about the voice are worth knowing before changing the script.

- It was trained on its own phoneme spelling, so `voice.py` turns
  espeak's British phonemes into that spelling, and gives the words
  espeak gets wrong itself (`LEXICON`: espeak spells out "DAG", and says
  "acyclic" with a k). `voice.py --phonemes` prints what will be said.
- It says a sentence of two or three words badly when given nothing
  else: after the full stop of "One rule." comes a murmur. So an
  utterance (what `|` parts in `narration.py`) has four words or more,
  and a shorter sentence stays joined to its neighbour.
- It reports no timings. The time of each word is estimated from the
  pauses in the sound, to about a fifth of a second.

`listen.py` is how the second of these was found. Whoever builds the film
may not be able to hear it, so it transcribes every line with a small
speech recogniser (Whisper base.en, from
[onnx-community](https://huggingface.co/onnx-community/whisper-base.en):
`onnx/encoder_model.onnx`, `onnx/decoder_model.onnx`, `vocab.json` and
`generation_config.json`, in `.venv-voice/models/whisper-base.en/`) and
prints the lines whose words differ from the script. It heard "One real,
sir". What it prints now is its own spelling: `route` for `root`, `15
August` for "the fifteenth of August", the name in three ways.

    ../../../.venv-voice/bin/python listen.py

The sound is set to -16 LUFS, the usual loudness of speech online, by one
gain for the whole track and a limiter (`render.py`).
