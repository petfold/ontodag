"""Build tests/fixtures/capture/: tiny photos and videos whose metadata says
when and where they were taken, written by the tools people's files come
from (Pillow and ffmpeg make the files, exiftool and ffmpeg write the
metadata), so `ontodag.capture` is checked against files it did not make.
tests/test_capture.py holds what each one states.

Rerun only to add a case: it needs Pillow, ffmpeg and exiftool.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "capture")

ROME = ["-GPSLatitude=41.902784", "-GPSLatitudeRef=N",
        "-GPSLongitude=12.496366", "-GPSLongitudeRef=E"]
TAKEN = ["-DateTimeOriginal=2026:07:14 10:22:31"]


def run(*args):
    subprocess.run(args, check=True, capture_output=True)


def exif(path, *tags):
    run("exiftool", "-q", "-overwrite_original", *tags, path)


def image(path, fmt):
    from PIL import Image
    Image.new("RGB", (16, 16), (200, 120, 40)).save(path, fmt)


def video(path, *flags):
    run("ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
        "color=c=black:s=16x16:d=0.2", "-pix_fmt", "yuv420p", *flags, path)


def main():
    for tool in ("ffmpeg", "exiftool"):
        if shutil.which(tool) is None:
            sys.exit(f"{tool} is needed to rebuild the fixtures")
    os.makedirs(HERE, exist_ok=True)
    out = lambda name: os.path.join(HERE, name)

    image(out("rome.jpg"), "JPEG")              # offset, position, its error
    exif(out("rome.jpg"), *TAKEN, "-OffsetTimeOriginal=+02:00", *ROME,
         "-GPSHPositioningError=4.7")
    image(out("zone-unknown.jpg"), "JPEG")      # no offset, no position, big-endian
    exif(out("zone-unknown.jpg"), "-ExifByteOrder=Big-endian", *TAKEN)
    image(out("south-west.jpg"), "JPEG")        # signs, and no stated error
    exif(out("south-west.jpg"), "-DateTimeOriginal=2025:12:31 23:59:59",
         "-OffsetTimeOriginal=-03:00", "-GPSLatitude=22.9519", "-GPSLatitudeRef=S",
         "-GPSLongitude=43.2105", "-GPSLongitudeRef=W")
    image(out("blank.jpg"), "JPEG")             # nothing stated
    image(out("rome.png"), "PNG")
    exif(out("rome.png"), *TAKEN, "-OffsetTimeOriginal=+02:00", *ROME)
    image(out("rome.webp"), "WEBP")
    exif(out("rome.webp"), *TAKEN, "-OffsetTimeOriginal=+02:00", *ROME)
    image(out("rome.tif"), "TIFF")
    exif(out("rome.tif"), *TAKEN, "-OffsetTimeOriginal=+02:00", *ROME)

    location = ["-metadata", "location=+41.9028+012.4964/",
                "-metadata", "creation_time=2026-07-14T08:22:31Z"]
    video(out("rome.mp4"), *location)                          # moov after mdat
    video(out("rome-faststart.mp4"), *location, "-movflags", "+faststart")
    video(out("apple.mov"))
    exif(out("apple.mov"), "-Keys:CreationDate=2026:07:14 10:22:31+02:00",
         "-Keys:GPSCoordinates=41.9028, 12.4964")
    with tempfile.TemporaryDirectory() as tmp:
        frame = os.path.join(tmp, "frame.png")
        image(frame, "PNG")
        run("ffmpeg", "-y", "-loglevel", "error", "-i", frame, "-c:v", "libaom-av1",
            "-still-picture", "1", out("rome.avif"))
    exif(out("rome.avif"), *TAKEN, "-OffsetTimeOriginal=+02:00", *ROME)
    print(sorted(os.listdir(HERE)))


if __name__ == "__main__":
    main()
