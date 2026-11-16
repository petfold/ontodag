#!/bin/sh
# Build the film, out/ontodag-explained.mp4: the facts it quotes, its voice,
# then its pictures. Each step runs where what it needs is installed (see
# README.md); VENVS is the directory the two environments are in.
set -e
cd "$(dirname "$0")"
VENVS=${VENVS:-../../..}

"$VENVS/.venv/bin/python" facts.py          # needs ontodag
"$VENVS/.venv-voice/bin/python" voice.py    # needs kokoro-onnx and its model
python3 render.py "$@"                      # needs python3-cairo, python3-gi, ffmpeg
