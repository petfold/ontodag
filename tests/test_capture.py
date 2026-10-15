"""`ontodag.capture`: when and where a photo or a video was taken, from the
file's own metadata (docs/plans/BROWSER.md §17, questions 49 and 50).

The fixtures in tests/fixtures/capture/ were made by the tools people's
files come from (tests/fixtures/make_capture.py: Pillow and ffmpeg, with
exiftool and ffmpeg writing the metadata), so the reader is checked against
files it did not write; what each states is what exiftool reads in it."""

import os
import random
import unittest

from ontodag import capture, prelude
from ontodag.capture import Capture, NeedBytes
from ontodag.dag import OntoDAG

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "capture")

STATED = {
    # offset +02:00; the receiver's stated error makes a square
    "rome.jpg": Capture("2026-07-14T08:22:31Z", "41.902784,12.496366±4.7m"),
    # no offset: the UTC days 10:22:31 local can fall on (big-endian EXIF)
    "zone-unknown.jpg": Capture("2026-07-13..2026-07-14", None),
    # south and west, and an offset that moves the date into the next year
    "south-west.jpg": Capture("2026-01-01T02:59:59Z", "-22.9519,-43.2105"),
    "blank.jpg": Capture(None, None),
    "rome.png": Capture("2026-07-14T08:22:31Z", "41.902784,12.496366"),
    "rome.webp": Capture("2026-07-14T08:22:31Z", "41.902784,12.496366"),
    "rome.tif": Capture("2026-07-14T08:22:31Z", "41.902784,12.496366"),     # little-endian
    "rome.avif": Capture("2026-07-14T08:22:31Z", "41.902784,12.496366"),    # HEIF's Exif item
    # the movie header's UTC time; ffmpeg's position in 3GPP's `loci`, in
    # 1/65536 of a degree; the box after the media, and before it
    "rome.mp4": Capture("2026-07-14T08:22:31Z", "41.90279,12.4964"),
    "rome-faststart.mp4": Capture("2026-07-14T08:22:31Z", "41.90279,12.4964"),
    # Apple's keys: the creation date with its offset, ISO 6709 position
    "apple.mov": Capture("2026-07-14T08:22:31Z", "41.9028,12.4964"),
}


def fixture(name):
    with open(os.path.join(FIXTURES, name), "rb") as fh:
        return fh.read()


def by_ranges(data, given=64, least=4096):
    """Read `data` as the page does: holding its first `given` bytes, then
    fetching what each NeedBytes asks for, `least` bytes at least (0: just
    that). Returns (Capture, rounds)."""
    ranges, rounds = [(0, data[:given])], 0
    while True:
        try:
            return capture.from_ranges(ranges, len(data)), rounds
        except NeedBytes as need:
            rounds += 1
            ranges.append((need.offset, data[need.offset:need.offset + max(need.size, least)]))
            if rounds > 50:
                raise AssertionError("the reader keeps asking")


class TestWhatFilesState(unittest.TestCase):
    def test_every_fixture_reads_as_exiftool_reads_it(self):
        self.assertEqual(sorted(STATED), sorted(n for n in os.listdir(FIXTURES)
                                                 if not n.startswith(".")))
        for name, stated in STATED.items():
            with self.subTest(name=name):
                self.assertEqual(capture.of_file(os.path.join(FIXTURES, name)), stated)

    def test_the_page_reads_by_ranges_to_the_same_answer(self):
        for name, stated in STATED.items():
            with self.subTest(name=name):
                found, rounds = by_ranges(fixture(name))
                self.assertEqual(found, stated)
                self.assertLessEqual(rounds, 2)
                self.assertEqual(by_ranges(fixture(name), least=0)[0], stated)   # byte by byte too

    def test_a_head_and_a_tail_are_mostly_enough(self):
        # The page hands in the first and the last 256 KB of a file at once:
        # every fixture then needs no further round trip.
        for name, stated in STATED.items():
            data = fixture(name)
            ranges = [(0, data[:1 << 18]), (max(0, len(data) - (1 << 18)), data[-(1 << 18):])]
            self.assertEqual(capture.from_ranges(ranges, len(data)), stated, name)

    def test_the_terms_file_and_answer_in_a_store(self):
        d = OntoDAG()
        prelude.apply(d)
        d.put("capture", [])
        d.put("capture-time", ["time", "capture"])
        d.put("capture-geo", ["geo", "capture"])
        d.put("rome", ["geo(41.8..42,12.4..12.6)"])
        for name, stated in STATED.items():
            if stated.terms():
                d.put(name, stated.terms())
        rome_july = {n.name for n in d.get(["capture-geo(41.8..42,12.4..12.6)",
                                            "capture-time(2026-07)"], items_only=True)}
        self.assertEqual(rome_july, {"rome.jpg", "rome.png", "rome.webp", "rome.tif",
                                     "rome.avif", "rome.mp4", "rome-faststart.mp4", "apple.mov"})
        # the day range of an unknown zone is inside July, not inside the 14th
        self.assertTrue(d.is_below("zone-unknown.jpg", "capture-time(2026-07)"))
        self.assertFalse(d.is_below("zone-unknown.jpg", "capture-time(2026-07-14)"))


class TestTimes(unittest.TestCase):
    def test_an_offset_gives_utc_to_the_second(self):
        self.assertEqual(capture._exif_time("2026:07:14 10:22:31", "+02:00"), "2026-07-14T08:22:31Z")
        self.assertEqual(capture._exif_time("2026:07:14 23:30:00", "-05:30"), "2026-07-15T05:00:00Z")

    def test_without_one_every_zone_is_allowed_for(self):
        # UTC-12:00 to UTC+14:00: 14 hours before to 12 after, as whole days
        self.assertEqual(capture._exif_time("2026:07:14 10:22:31", None), "2026-07-13..2026-07-14")
        self.assertEqual(capture._exif_time("2026:07:14 15:00:00", None), "2026-07-14..2026-07-15")
        self.assertEqual(capture._exif_time("2026:07:14 13:00:00", ""), "2026-07-13..2026-07-15")

    def test_no_time_is_none(self):
        for local in ("0000:00:00 00:00:00", "    :  :     :  :  ", "", None, "2026:13:40 10:00:00"):
            self.assertIsNone(capture._exif_time(local, "+02:00"), local)


class TestPlacesWritten(unittest.TestCase):
    def test_iso6709_in_its_three_forms(self):
        self.assertEqual(capture._iso6709("+41.9028+012.4964+050.000/"), "41.9028,12.4964")
        self.assertEqual(capture._iso6709("-22.9519-043.2105/"), "-22.9519,-43.2105")
        self.assertEqual(capture._iso6709("+4154.168+01229.784/"), "41.9028,12.4964")      # minutes
        self.assertEqual(capture._iso6709("+415410.1+0122947.0/"), "41.90281,12.49639")  # seconds
        self.assertIsNone(capture._iso6709("+91.0+012.0/"))
        self.assertIsNone(capture._iso6709("nowhere"))

    def test_precision_follows_the_numbers(self):
        from fractions import Fraction as F
        self.assertEqual(capture._places([F(41), F(54), F(1001, 100)]), 6)   # 1/360000 of a degree
        self.assertEqual(capture._places([F(41), F(54), F(10)]), 4)          # whole seconds
        self.assertEqual(capture._places([F(41), F(54), F(0)]), 2)           # whole minutes
        self.assertEqual(capture._decimal(F(-43210500, 1000000), 6), "-43.2105")


class TestNothingBreaksIt(unittest.TestCase):
    def test_truncated_and_damaged_files_read_as_stating_less(self):
        rnd = random.Random(7)
        for name in STATED:
            data = fixture(name)
            for cut in range(0, len(data), max(1, len(data) // 60)):
                capture.from_ranges([(0, data[:cut])], cut)
            for _ in range(150):
                damaged = bytearray(data)
                for _ in range(rnd.randint(1, 8)):
                    damaged[rnd.randrange(len(damaged))] = rnd.randrange(256)
                found = capture.from_ranges([(0, bytes(damaged))], len(damaged))
                self.assertIsInstance(found, Capture)

    def test_not_a_photo(self):
        self.assertEqual(capture.from_ranges([(0, b"hello, world")], 12), Capture())
        self.assertEqual(capture.from_ranges([(0, b"")], 0), Capture())
