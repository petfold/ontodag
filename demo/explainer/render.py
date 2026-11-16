"""Draw the film: stills to look at, or all of it with its sound.

    python3 render.py                      # out/ontodag-explained.mp4
    python3 render.py --still 12.5 61      # out/stills/0012.50.png, ...
    python3 render.py --range 100 130      # that half minute, as a preview

Needs `out/timeline.json` and `out/narration.wav` (voice.py), `out/facts.json`
(facts.py), the system's python3-cairo and python3-gi, and ffmpeg.
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
from multiprocessing import Process
from pathlib import Path

import cairo

import anim
import scenes

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"

VIDEO = ["-c:v", "libx264", "-preset", "slow", "-crf", "17",
         "-profile:v", "high", "-pix_fmt", "yuv420p", "-g", "60",
         "-colorspace", "bt709", "-color_primaries", "bt709",
         "-color_trc", "bt709", "-color_range", "tv"]
TO_VIDEO = "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p"


def stills(times, size):
    stage = scenes.build()
    folder = OUT / "stills"
    folder.mkdir(parents=True, exist_ok=True)
    for t in times:
        surface = stage.paint(t)
        if size != 1.0:
            small = cairo.ImageSurface(
                cairo.FORMAT_RGB24, int(anim.W * size), int(anim.H * size))
            ctx = cairo.Context(small)
            ctx.scale(size, size)
            ctx.set_source_surface(surface)
            ctx.get_source().set_filter(cairo.FILTER_BEST)
            ctx.paint()
            surface = small
        path = folder / ("%07.2f.png" % t)
        surface.write_to_png(str(path))
        print(path)


def frames(first, last, path):
    """Draw frames [first, last) into a video file without sound."""
    stage = scenes.build()
    encoder = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo",
         "-pix_fmt", "bgr0", "-s", f"{anim.W}x{anim.H}", "-r", str(anim.FPS),
         "-i", "-", "-vf", TO_VIDEO, *VIDEO, str(path)],
        stdin=subprocess.PIPE)
    for number in range(first, last):
        encoder.stdin.write(stage.paint(number / anim.FPS).get_data())
    encoder.stdin.close()
    if encoder.wait():
        sys.exit("ffmpeg failed on " + str(path))


LOUDNESS = -16.0            # LUFS, the usual level for speech online


def loudness(path):
    """A sound file's loudness and highest peak, as ffmpeg measures them."""
    heard = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(path), "-af",
         "loudnorm=print_format=json", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    measured = json.loads(re.search(r'\{\s*"input_i"[^{}]*\}', heard).group())
    return float(measured["input_i"]), float(measured["input_tp"])


def sound():
    """The narration at the loudness of broadcast speech: out/sound.wav.

    One gain for the whole track, and a limiter for the few consonants that
    would then pass full scale.
    """
    gain = LOUDNESS - loudness(OUT / "narration.wav")[0]
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i",
         str(OUT / "narration.wav"), "-af",
         f"volume={gain:.2f}dB,"
         "alimiter=limit=0.84:attack=2:release=50:level=false",
         "-ar", "48000", "-ac", "2", str(OUT / "sound.wav")], check=True)
    return OUT / "sound.wav"


def film(start, end, jobs, path):
    first, last = int(start * anim.FPS), math.ceil(end * anim.FPS)
    share = math.ceil((last - first) / jobs)
    parts, workers = [], []
    for job in range(jobs):
        a, b = first + job * share, min(last, first + (job + 1) * share)
        if a >= b:
            break
        parts.append(OUT / f"part-{job:02d}.mp4")
        workers.append(Process(target=frames, args=(a, b, parts[-1])))
        workers[-1].start()
    for worker in workers:
        worker.join()
        if worker.exitcode:
            sys.exit("a slice failed")
    listing = OUT / "parts.txt"
    listing.write_text("".join(f"file '{part.name}'\n" for part in parts))
    command = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat",
               "-i", str(listing)]
    command += ["-ss", str(start)] if start else []
    subprocess.run(command + [
        "-i", str(sound()), "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-t", "%.3f" % ((last - first) / anim.FPS),
        "-metadata", "title=OntoDAG: categories beyond trees",
        "-metadata:s:a:0", "language=eng",
        "-movflags", "+faststart", str(path)], check=True)
    for part in parts + [listing]:
        part.unlink()
    print(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--still", nargs="+", type=float, metavar="T")
    parser.add_argument("--size", type=float, default=1.0,
                        help="stills at this fraction of full size")
    parser.add_argument("--range", nargs=2, type=float, metavar=("A", "B"))
    parser.add_argument("--jobs", type=int,
                        default=max(1, min(4, (os.cpu_count() or 2) // 2)))
    args = parser.parse_args()
    if args.still:
        stills(args.still, args.size)
    elif args.range:
        film(args.range[0], args.range[1], args.jobs,
             OUT / ("preview-%04d-%04d.mp4" % tuple(args.range)))
    else:
        film(0.0, scenes.duration(), args.jobs, OUT / "ontodag-explained.mp4")


if __name__ == "__main__":
    main()
