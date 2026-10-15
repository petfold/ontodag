"""When and where a photo or a video was taken, from the file's own
metadata (docs/plans/BROWSER.md §17, questions 49 and 50).

Standard library only, and only what a file states, never a guess:

- **Photos:** EXIF, in JPEG, TIFF and the raw formats built on it (DNG,
  NEF, CR2), PNG (`eXIf`, or the hex "Raw profile type exif" text that
  ImageMagick and GIMP write), WebP (`EXIF`) and HEIF (HEIC, AVIF: its
  `Exif` item). The time is `DateTimeOriginal`, a local time: with its
  `OffsetTimeOriginal` it is exact to the second, in UTC; without one the
  zone is unknown, so the time is the UTC days it can fall on, whatever the
  zone (UTC-12:00 to UTC+14:00), `2026-07-13..2026-07-14`. The place is
  the GPS position, written to the precision its numbers carry (at most a
  millionth of a degree), or, where the file states the receiver's error
  (`GPSHPositioningError`), the square that much either way.
- **Videos:** MP4, MOV, M4V, 3GP. The time is Apple's creation date, which
  carries its offset, else the movie header's creation time, UTC by the
  format (one before 1970 is taken as not stated: writers that counted
  from 1970, not 1904, give such dates). The place is the ISO 6709 position
  (Apple's key, or `©xyz`), to the precision it is written with, or 3GPP's
  `loci` (ffmpeg's), to the 1/65536 of a degree it is stored in.

`read_capture(read, size)` takes `read(offset, n)`, which returns the
file's bytes from `offset` (fewer at its end). A caller holding only some
of the file, as the page does, raises `NeedBytes` from `read` for what it
lacks, fetches it and asks again; it passes through.
"""

import datetime
import re
import struct
import zlib
from dataclasses import dataclass
from fractions import Fraction

__all__ = ["Capture", "NeedBytes", "read_capture", "of_file", "from_ranges"]


class NeedBytes(Exception):
    """The reader needs `size` bytes at `offset`, which it was not given."""

    def __init__(self, offset, size):
        super().__init__(offset, size)
        self.offset, self.size = offset, size


@dataclass(frozen=True)
class Capture:
    """When (`time`, a `time` parameter) and where (`geo`, a `geo`
    parameter) a file was taken; None for what it does not state."""
    time: str = None
    geo: str = None

    def terms(self):
        """The version's capture terms: `capture-time(…)`, `capture-geo(…)`."""
        out = []
        if self.time:
            out.append(f"capture-time({self.time})")
        if self.geo:
            out.append(f"capture-geo({self.geo})")
        return out


_NOTHING = Capture()
_MAX_BOXES = 4096        # boxes, chunks or IFD entries looked at in one file


def read_capture(read, size):
    """The Capture a file's own metadata states (both None if it states
    nothing, or is no format read here, or is malformed)."""
    head = read(0, 16)
    try:
        if head[:3] == b"\xff\xd8\xff":
            return _jpeg(read, size)
        if head[:4] in (b"II*\x00", b"MM\x00*"):
            return _exif(read(0, min(size, 1 << 20)))
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return _png(read, size)
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            return _webp(read, size)
        if head[4:8] == b"ftyp":
            return _bmff(read, size)
    except NeedBytes:
        raise
    except (struct.error, ValueError, IndexError, OverflowError, ZeroDivisionError):
        return _NOTHING
    return _NOTHING


def of_file(path):
    """The Capture a file on disk states."""
    import os
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        def read(offset, n):
            fh.seek(offset)
            return fh.read(n)
        return read_capture(read, size)


def from_ranges(ranges, size):
    """The Capture of a file of `size` bytes of which only `ranges`
    ([(offset, bytes)]) are at hand; raises NeedBytes for a read none of
    them covers (the page fetches it and asks again)."""
    def read(offset, n):
        n = max(0, min(n, size - offset))
        if n == 0:
            return b""                  # at or past the end: nothing to fetch
        for start, data in ranges:
            if start <= offset and offset + n <= start + len(data):
                return bytes(data[offset - start:offset - start + n])
        raise NeedBytes(offset, n)
    return read_capture(read, size)


# -- EXIF ------------------------------------------------------------------- #

_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}


def _ifd(tiff, offset, order):
    """{tag: (type, count, value bytes)} of the IFD at `offset` in `tiff`."""
    if offset <= 0 or offset + 2 > len(tiff):
        return {}
    (count,) = struct.unpack_from(order + "H", tiff, offset)
    entries = {}
    for i in range(min(count, _MAX_BOXES)):
        at = offset + 2 + 12 * i
        if at + 12 > len(tiff):
            break
        tag, kind, n = struct.unpack_from(order + "HHI", tiff, at)
        width = _TYPE_SIZES.get(kind)
        if width is None:
            continue
        length = width * n
        if length <= 4:
            data = tiff[at + 8:at + 8 + length]
        else:
            (where,) = struct.unpack_from(order + "I", tiff, at + 8)
            data = tiff[where:where + length]
            if len(data) != length:
                continue
        entries[tag] = (kind, n, data)
    return entries


def _ascii(entry):
    if entry is None or entry[0] != 2:
        return None
    return entry[2].split(b"\x00", 1)[0].decode("ascii", "replace").strip()


def _rationals(entry, order):
    if entry is None or entry[0] not in (5, 10):
        return None
    fmt = order + ("II" if entry[0] == 5 else "ii")
    out = []
    for i in range(entry[1]):
        num, den = struct.unpack_from(fmt, entry[2], 8 * i)
        if den == 0:
            return None
        out.append(Fraction(num, den))
    return out


def _offset_of(entry, order):
    if entry is None or entry[0] not in (4, 13) or entry[1] < 1:
        return 0
    return struct.unpack_from(order + "I", entry[2])[0]


def _exif(tiff):
    """The Capture an EXIF block (a TIFF structure) states."""
    if tiff[:2] == b"II":
        order = "<"
    elif tiff[:2] == b"MM":
        order = ">"
    else:
        return _NOTHING
    (first,) = struct.unpack_from(order + "I", tiff, 4)
    ifd0 = _ifd(tiff, first, order)
    exif = _ifd(tiff, _offset_of(ifd0.get(0x8769), order), order)
    gps = _ifd(tiff, _offset_of(ifd0.get(0x8825), order), order)
    when = _exif_time(_ascii(exif.get(0x9003)), _ascii(exif.get(0x9011)))
    return Capture(when, _gps_place(gps, order))


_EXIF_TIME = re.compile(r"^(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})")
_OFFSET = re.compile(r"^([+-])(\d{2}):?(\d{2})$")


def _exif_time(local, offset):
    """A `time` parameter from EXIF's local date and time and its offset."""
    if not local:
        return None
    m = _EXIF_TIME.match(local)
    if not m:
        return None
    try:
        when = datetime.datetime(*map(int, m.groups()))
    except ValueError:
        return None        # 0000:00:00 00:00:00 and the like: no time stated
    return _with_offset(when, offset)


def _with_offset(local, offset):
    """`local` (naive) at `offset` (`+02:00`) as UTC to the second; with no
    offset, the UTC days it falls on in any zone."""
    m = _OFFSET.match(offset or "")
    if m:
        delta = datetime.timedelta(hours=int(m.group(2)), minutes=int(m.group(3)))
        utc = local - delta if m.group(1) == "+" else local + delta
        return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    first = (local - datetime.timedelta(hours=14)).date()
    last = (local + datetime.timedelta(hours=12)).date()
    return f"{first.isoformat()}..{last.isoformat()}"


def _gps_place(gps, order):
    lat, lon = _rationals(gps.get(2), order), _rationals(gps.get(4), order)
    north, east = _ascii(gps.get(1)), _ascii(gps.get(3))
    if not lat or not lon or len(lat) != 3 or len(lon) != 3 \
            or north not in ("N", "S") or east not in ("E", "W"):
        return None
    lat_value = lat[0] + lat[1] / 60 + lat[2] / 3600
    lon_value = lon[0] + lon[1] / 60 + lon[2] / 3600
    if north == "S":
        lat_value = -lat_value
    if east == "W":
        lon_value = -lon_value
    if not (-90 <= lat_value <= 90 and -180 <= lon_value <= 180):
        return None
    error = _rationals(gps.get(0x1F), order)
    if error and len(error) == 1 and error[0] > 0:
        return f"{_decimal(lat_value, 6)},{_decimal(lon_value, 6)}±{_decimal(error[0], 3)}m"
    return f"{_decimal(lat_value, _places(lat))},{_decimal(lon_value, _places(lon))}"


def _places(dms):
    """The decimal places of a degree that degrees, minutes and seconds
    written as these fractions carry, at most six."""
    unit = Fraction(1)
    for value, scale in zip(dms, (1, 60, 3600)):
        if value:
            unit = min(unit, Fraction(1, value.denominator * scale))
    places = 0
    while Fraction(1, 10 ** places) > unit and places < 6:
        places += 1
    return places


def _decimal(value, places):
    """`value` rounded to `places` decimals, written without trailing zeros."""
    scaled = round(Fraction(value) * 10 ** places)
    sign = "-" if scaled < 0 else ""
    digits = str(abs(scaled)).rjust(places + 1, "0")
    whole, frac = digits[:len(digits) - places], digits[len(digits) - places:]
    frac = frac.rstrip("0")
    return f"{sign}{whole}.{frac}" if frac else f"{sign}{whole}"


# -- JPEG, PNG, WebP --------------------------------------------------------- #

def _jpeg(read, size):
    at = 2
    for _ in range(_MAX_BOXES):
        if at + 4 > size:
            break
        marker, length = struct.unpack(">HH", read(at, 4))
        if marker >> 8 != 0xFF or marker in (0xFFD9, 0xFFDA):
            break                   # end of the headers: no EXIF before the image
        if marker == 0xFFE1:
            data = read(at + 4, length - 2)
            if data[:6] == b"Exif\x00\x00":
                return _exif(data[6:])
        at += 2 + length
    return _NOTHING


def _png(read, size):
    at = 8
    for _ in range(_MAX_BOXES):
        if at + 8 > size:
            break
        length, kind = struct.unpack(">I4s", read(at, 8))
        if kind == b"eXIf":
            data = read(at + 8, length)
            return _exif(data[6:] if data[:6] == b"Exif\x00\x00" else data)
        if kind in (b"tEXt", b"zTXt", b"iTXt") and length <= 1 << 20:
            tiff = _raw_profile(kind, read(at + 8, length))
            if tiff is not None:
                return _exif(tiff)
        if kind in (b"IDAT", b"IEND"):
            break                   # metadata comes before the image data
        at += 12 + length
    return _NOTHING


_RAW_PROFILES = (b"Raw profile type exif", b"Raw profile type APP1")


def _raw_profile(kind, data):
    """The EXIF block a PNG text chunk holds as ImageMagick writes it (a
    keyword, then a line naming the profile, its length, and its bytes in
    hex), or None."""
    keyword, _, rest = data.partition(b"\x00")
    if keyword not in _RAW_PROFILES:
        return None
    if kind == b"zTXt":
        rest = zlib.decompressobj().decompress(rest[1:], 1 << 21)
    elif kind == b"iTXt":
        compressed, rest = rest[0], rest[2:]
        rest = rest.split(b"\x00", 2)[-1]          # language tag, translated keyword
        if compressed:
            rest = zlib.decompressobj().decompress(rest, 1 << 21)
    lines = rest.decode("ascii", "replace").split()
    if len(lines) < 3 or not lines[1].isdigit():
        return None
    block = bytes.fromhex("".join(lines[2:]))[:int(lines[1])]
    return block[6:] if block[:6] == b"Exif\x00\x00" else block


def _webp(read, size):
    at = 12
    for _ in range(_MAX_BOXES):
        if at + 8 > size:
            break
        kind, length = struct.unpack("<4sI", read(at, 8))
        if kind == b"EXIF":
            data = read(at + 8, length)
            return _exif(data[6:] if data[:6] == b"Exif\x00\x00" else data)
        at += 8 + length + (length & 1)
    return _NOTHING


# -- ISO base media: HEIF and movies ---------------------------------------- #

def _boxes(read, start, end):
    """(type, content start, content end) of the boxes in [start, end)."""
    at, out = start, []
    for _ in range(_MAX_BOXES):
        if at + 8 > end:
            break
        length, kind = struct.unpack(">I4s", read(at, 8))
        header = 8
        if length == 1:
            (length,) = struct.unpack(">Q", read(at + 8, 8))
            header = 16
        elif length == 0:
            length = end - at
        if length < header or at + length > end:
            break
        out.append((kind, at + header, at + length))
        at += length
    return out


def _bmff(read, size):
    top = _boxes(read, 0, size)
    for kind, start, end in top:
        if kind == b"meta":
            found = _heif_exif(read, start + 4, end)
            if found is not None:
                return found
    for kind, start, end in top:
        if kind == b"moov":
            return _movie(read, start, end)
    return _NOTHING


def _heif_exif(read, start, end):
    """The Capture of a HEIF's `Exif` item, or None if it has none."""
    boxes = {kind: (s, e) for kind, s, e in _boxes(read, start, end)}
    if b"iinf" not in boxes or b"iloc" not in boxes:
        return None
    exif_id = _exif_item(read, *boxes[b"iinf"])
    if exif_id is None:
        return None
    extent = _item_extent(read, *boxes[b"iloc"], exif_id)
    if extent is None:
        return None
    offset, length = extent
    data = read(offset, min(length, 1 << 20))
    if len(data) < 4:
        return None
    (skip,) = struct.unpack(">I", data[:4])
    tiff = data[4 + skip:]
    if tiff[:6] == b"Exif\x00\x00":
        tiff = tiff[6:]
    return _exif(tiff)


def _exif_item(read, start, end):
    version = read(start, 1)[0]
    count_size = 2 if version == 0 else 4
    for kind, s, e in _boxes(read, start + 4 + count_size, end):
        if kind != b"infe":
            continue
        infe = read(s, min(e - s, 64))
        if infe[0] < 2:
            continue
        if infe[0] == 2:
            item_id, item_type = struct.unpack_from(">H", infe, 4)[0], infe[8:12]
        else:
            item_id, item_type = struct.unpack_from(">I", infe, 4)[0], infe[10:14]
        if item_type == b"Exif":
            return item_id
    return None


def _item_extent(read, start, end, wanted):
    """(file offset, length) of the item's first extent, or None."""
    data = read(start, min(end - start, 1 << 16))
    version = data[0]
    sizes = struct.unpack_from(">H", data, 4)[0]
    offset_size, length_size = sizes >> 12, (sizes >> 8) & 15
    base_size, index_size = (sizes >> 4) & 15, sizes & 15 if version in (1, 2) else 0
    at = 6

    def number(width):
        nonlocal at
        value = int.from_bytes(data[at:at + width], "big") if width else 0
        at += width
        return value
    count = number(2 if version < 2 else 4)
    for _ in range(min(count, _MAX_BOXES)):
        item_id = number(2 if version < 2 else 4)
        method = number(2) & 15 if version in (1, 2) else 0
        number(2)                                   # data reference index
        base = number(base_size)
        extents = number(2)
        first = None
        for _ in range(extents):
            number(index_size)
            extent = (number(offset_size), number(length_size))
            first = first or extent
        if item_id == wanted:
            if method != 0 or first is None:
                return None                         # not at a file offset
            return base + first[0], first[1]
    return None


_MOVIE_EPOCH = datetime.datetime(1904, 1, 1)
_UNIX_EPOCH = datetime.datetime(1970, 1, 1)


def _movie(read, start, end):
    children = _boxes(read, start, end)
    when = place = None
    for kind, s, e in children:
        if kind == b"meta":
            when, place = _apple_keys(read, s, e)
    for kind, s, e in children:
        if kind == b"mvhd" and when is None:
            data = read(s, 12)
            seconds = struct.unpack_from(">Q" if data[0] == 1 else ">I", data, 4)[0]
            stamp = _MOVIE_EPOCH + datetime.timedelta(seconds=seconds)
            if stamp >= _UNIX_EPOCH:
                when = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")
        if kind == b"udta" and place is None:
            for k, us, ue in _boxes(read, s, e):
                if k == b"\xa9xyz":
                    data = read(us, min(ue - us, 256))
                    (length,) = struct.unpack_from(">H", data)
                    place = _iso6709(data[4:4 + length].decode("ascii", "replace"))
                elif k == b"loci" and place is None:
                    place = _loci(read(us, min(ue - us, 512)))
    return Capture(when, place)


def _loci(data):
    """`lat,lon` from a 3GPP location box: after its version, flags,
    language, name and role, longitude then latitude, signed 16.16."""
    end = data.find(b"\x00", 6)
    if end < 0 or end + 10 > len(data):
        return None
    lon, lat = struct.unpack_from(">ii", data, end + 2)
    lat_value, lon_value = Fraction(lat, 65536), Fraction(lon, 65536)
    if not (-90 <= lat_value <= 90 and -180 <= lon_value <= 180):
        return None
    return f"{_decimal(lat_value, 5)},{_decimal(lon_value, 5)}"


def _apple_keys(read, start, end):
    """(time, place) from QuickTime's metadata keys, each None if absent."""
    head = read(start, 12)
    if head[4:8] != b"hdlr":
        start += 4                                  # an ISO meta box: a full box
    boxes = {kind: (s, e) for kind, s, e in _boxes(read, start, end)}
    if b"keys" not in boxes or b"ilst" not in boxes:
        return None, None
    ks, ke = boxes[b"keys"]
    data = read(ks, min(ke - ks, 1 << 16))
    (count,) = struct.unpack_from(">I", data, 4)
    names, at = {}, 8
    for index in range(1, min(count, _MAX_BOXES) + 1):
        (length,) = struct.unpack_from(">I", data, at)
        if length < 8:
            break
        names[index] = data[at + 8:at + length].decode("utf-8", "replace")
        at += length
    when = place = None
    for kind, s, e in _boxes(read, *boxes[b"ilst"]):
        name = names.get(int.from_bytes(kind, "big"))
        if name not in ("com.apple.quicktime.creationdate",
                        "com.apple.quicktime.location.ISO6709"):
            continue
        for dk, ds, de in _boxes(read, s, e):
            if dk != b"data":
                continue
            text = read(ds + 8, min(de - ds - 8, 256)).decode("utf-8", "replace")
            if name.endswith("creationdate"):
                when = _iso_time(text)
            else:
                place = _iso6709(text)
    return when, place


_ISO_TIME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})$")


def _iso_time(text):
    m = _ISO_TIME.match(text.strip())
    if not m:
        return None
    try:
        local = datetime.datetime(*map(int, m.groups()[:6]))
    except ValueError:
        return None
    zone = m.group(7)
    return _with_offset(local, "+00:00" if zone == "Z" else zone)


_ISO6709 = re.compile(r"^([+-])(\d+(?:\.\d+)?)([+-])(\d+(?:\.\d+)?)")


def _iso6709(text):
    """`lat,lon` from an ISO 6709 position (`+41.9028+012.4964+050.000/`),
    in decimal degrees, degrees and minutes, or degrees, minutes and
    seconds, written to the precision it has."""
    m = _ISO6709.match(text.strip())
    if not m:
        return None
    lat = _iso_angle(m.group(2), 2)
    lon = _iso_angle(m.group(4), 3)
    if lat is None or lon is None:
        return None
    (lat_value, lat_places), (lon_value, lon_places) = lat, lon
    if m.group(1) == "-":
        lat_value = -lat_value
    if m.group(3) == "-":
        lon_value = -lon_value
    if not (-90 <= lat_value <= 90 and -180 <= lon_value <= 180):
        return None
    return f"{_decimal(lat_value, lat_places)},{_decimal(lon_value, lon_places)}"


def _iso_angle(text, degree_digits):
    """(value, decimal places of a degree it carries) of an ISO 6709 angle."""
    whole, _, frac = text.partition(".")
    value = Fraction(text)
    unit = Fraction(1, 10 ** len(frac))
    if len(whole) == degree_digits:
        pass
    elif len(whole) == degree_digits + 2:          # degrees and minutes
        minutes = value - int(whole[:degree_digits]) * 100
        value, unit = int(whole[:degree_digits]) + minutes / 60, unit / 60
    elif len(whole) == degree_digits + 4:          # degrees, minutes, seconds
        degrees = int(whole[:degree_digits])
        minutes = int(whole[degree_digits:degree_digits + 2])
        seconds = value - (degrees * 10000 + minutes * 100)
        value, unit = degrees + Fraction(minutes, 60) + seconds / 3600, unit / 3600
    else:
        return None
    places = 0
    while Fraction(1, 10 ** places) > unit and places < 6:
        places += 1
    return value, places
