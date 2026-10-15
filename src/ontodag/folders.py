"""Your files, organised where they are (docs/plans/BROWSER.md §17,
questions 40 to 45, 49 and 50).

A folder is read, never written. What a file's type says is the folder's
layer: each content under its kind (`image-file`, `video-file`, core's
`document`), rebuilt whenever the folder is looked at and never stored
(docs/plans/PROJECTIONS.md §3). What you file is in your store, as a
document:

    reading-list.md ⊑ notes                          you filed it
    sha256:4be1… ⊑ reading-list.md, modification-time(2026-10-01T08:30:12Z)
    sha256:91c0… ⊑ reading-list.md, modification-time(2026-10-13T09:12:41Z)
    sha256:77e2… ⊑ IMG_2041.jpg, modification-time(…),
                   capture-time(2026-07-14T08:22:31Z), capture-geo(41.902784,12.496366±4.7m)

- A **document** is named by the file's name when it was first filed, and
  your categories go on it.
- Each content the file has had is a **version** below it, named by its
  SHA-256 as holdings names files, and filed under the time it was last
  modified when it was first seen, and, for a photo or a video, when and
  where it was taken, as far as its own metadata says (`ontodag.capture`).
  The heads are the organiser's own (`HEADS`), declared in a store the
  first time it files a version.

The document is the class of its versions, so this is ordinary "below".
Renames, moves and which folder was opened do not matter (a known
version is found by its hash), copies are one version, and the store
reads by file names without the folder.

**Recognising an edit:** a file whose content the store does not know,
named as a document whose known versions are no longer in the folder, is
that document's new version. With one such document it is attached;
with several it is left for the person to choose.

`scan` walks a folder natively (`odag`) and `look_at` reads a single
file; the page hands in what the browser's file and folder inputs give it
instead (`Seen`). Everything else is shared. A single file is filed as a
folder's files are. Where a document of its name exists already, the
person says whether it is a new version of it (`named_like`, and `file`'s
`version_of`): without its folder, the page cannot tell that the old
version is gone.
"""

import hashlib
import json
import os
import re
from dataclasses import dataclass

__all__ = ["KINDS", "HEADS", "Seen", "HashCache", "Folder", "kind_of", "is_media",
           "skipped", "scan", "look_at", "hash_file", "taken", "version_name",
           "is_version", "modification_time", "version_parents", "documents",
           "versions_of", "document_of", "document_name", "named_like", "file",
           "unfiled", "recognise_edits", "attach"]

# What a file's extension says it is: computing's file kinds, and core's
# `document` and `presentation` (core's `spreadsheet` is the program, so a
# spreadsheet is a document).
KINDS = {
    **dict.fromkeys(("jpg", "jpeg", "png", "heic", "heif", "gif", "webp", "tif", "tiff", "bmp", "svg", "raw", "cr2", "nef", "dng"), "image-file"),
    **dict.fromkeys(("mp4", "mov", "mkv", "avi", "webm", "m4v", "3gp"), "video-file"),
    **dict.fromkeys(("mp3", "m4a", "wav", "flac", "ogg", "opus", "aac", "aiff"), "audio-file"),
    **dict.fromkeys(("txt", "md", "markdown", "rst", "csv", "tsv", "json", "yaml", "yml", "xml", "html", "htm", "tex", "log", "ini", "toml"), "text-file"),
    **dict.fromkeys(("zip", "gz", "tgz", "tar", "bz2", "xz", "7z", "rar", "zst"), "archive-file"),
    **dict.fromkeys(("pdf", "doc", "docx", "odt", "rtf", "epub", "xls", "xlsx", "ods", "pages", "numbers"), "document"),
    **dict.fromkeys(("ppt", "pptx", "odp", "key"), "presentation"),
}

# Never looked at, as holdings skips them: version control, caches, sync
# tools' own folders, and editors' and systems' temporary files.
SKIPPED_FOLDERS = frozenset({".git", ".hg", ".svn", "node_modules", "__pycache__", ".cache",
                             ".stfolder", ".stversions", ".Trash", ".Trashes", ".venv", "venv"})
_TEMPORARY = re.compile(r"(~$|^\.#|^~\$|\.(swp|swo|swx|tmp|part|crdownload)$|^(\.DS_Store|Thumbs\.db|desktop\.ini)$)",
                        re.IGNORECASE)
_VERSION = re.compile(r"^sha256:[0-9a-f]{64}$")


# What the organiser files a version under, declared in a store the first
# time it files one: when its content was last modified, and when and where
# a photo or a video was taken (`capture-time` and `capture-geo` take their
# values from the file; `capture-in(paris)` is yours to say, and follows
# `in` as `about` does).
HEADS = [("modification-time", ["time"]), ("capture", []),
         ("capture-time", ["time", "capture"]), ("capture-geo", ["geo", "capture"]),
         ("capture-in", ["enclosing-dimension", "capture"])]


def kind_of(path):
    """The kind a file's extension names, or None."""
    name = path.rsplit("/", 1)[-1]
    if "." not in name.strip("."):
        return None
    return KINDS.get(name.rsplit(".", 1)[1].lower())


def is_media(path):
    """Is this a photo or a video, whose own metadata may say when and where
    it was taken?"""
    return kind_of(path) in ("image-file", "video-file")


def skipped(path):
    """Is this path inside a folder (as `/`-separated parts) left alone? A
    hidden file or folder is, and so is an editor's or system's temporary
    file."""
    parts = path.split("/")
    for part in parts[:-1]:
        if part in SKIPPED_FOLDERS or part.startswith("."):
            return True
    name = parts[-1]
    return name.startswith(".") or bool(_TEMPORARY.search(name))


def version_name(sha256):
    return f"sha256:{sha256}"


def is_version(name):
    return bool(_VERSION.match(name))


def modification_time(mtime):
    """A modification time (seconds since the epoch) as a version's
    `modification-time` term, to the second, in UTC."""
    import datetime
    when = datetime.datetime.fromtimestamp(int(mtime), tz=datetime.timezone.utc)
    return f"modification-time({when.strftime('%Y-%m-%dT%H:%M:%SZ')})"


@dataclass(frozen=True)
class Seen:
    """A file as one look at its folder found it: its path inside the
    folder (`/`-separated), size, modification time (seconds), SHA-256
    (hex, or None if it was not read), and, for a photo or a video, when
    and where its metadata says it was taken (an `ontodag.capture.Capture`,
    or None when not read)."""
    path: str
    size: int
    mtime: float
    sha256: str = None
    taken: object = None

    @property
    def name(self):
        return self.path.rsplit("/", 1)[-1]

    @property
    def folder(self):
        return self.path.rsplit("/", 1)[0] if "/" in self.path else ""


class HashCache:
    """What was hashed, by path, size and modification time: a file seen
    with all three unchanged is taken as unchanged without reading it, as
    holdings' rescan does. That is for speed only, never verification (bit
    rot changes neither size nor time)."""

    def __init__(self, entries=None):
        self.entries = dict(entries or {})

    @staticmethod
    def _key(path, size, mtime_ns):
        return f"{path}\0{size}\0{mtime_ns}"

    def get(self, path, size, mtime_ns):
        return self.entries.get(self._key(path, size, mtime_ns))

    def put(self, path, size, mtime_ns, sha256):
        self.entries[self._key(path, size, mtime_ns)] = sha256

    def keep_only(self, seen_keys):
        """Forget what the last look no longer saw."""
        self.entries = {k: v for k, v in self.entries.items() if k in seen_keys}

    @classmethod
    def load(cls, path):
        try:
            with open(path, encoding="utf-8") as fh:
                return cls(json.load(fh))
        except FileNotFoundError:
            return cls()

    def save(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.entries, fh)
        os.replace(tmp, path)


def hash_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def scan(root, cache=None, hash_over=None, stats=None):
    """Look at a folder: every file not skipped, sorted by path, hashed
    unless the cache knows it (or, with `hash_over`, unless it is larger
    than that many bytes). `stats`, if given, is filled with counts: files,
    hashed, from the cache, not hashed, bytes read, skipped."""
    counts = {"files": 0, "hashed": 0, "cached": 0, "unhashed": 0, "bytes_read": 0, "skipped": 0}
    found, seen_keys = [], set()
    root = os.path.abspath(root)
    for here, dirs, names in os.walk(root):
        rel = os.path.relpath(here, root)
        rel = "" if rel == "." else rel.replace(os.sep, "/")
        kept = []
        for d in sorted(dirs):
            if skipped(f"{rel}/{d}/x" if rel else f"{d}/x"):
                counts["skipped"] += 1
            else:
                kept.append(d)
        dirs[:] = kept
        for n in sorted(names):
            path = f"{rel}/{n}" if rel else n
            full = os.path.join(here, n)
            if skipped(path) or os.path.islink(full) or not os.path.isfile(full):
                counts["skipped"] += 1
                continue
            st = os.stat(full)
            counts["files"] += 1
            digest = cache.get(path, st.st_size, st.st_mtime_ns) if cache else None
            if digest:
                counts["cached"] += 1
            elif hash_over is not None and st.st_size > hash_over:
                counts["unhashed"] += 1
            else:
                digest = hash_file(full)
                counts["hashed"] += 1
                counts["bytes_read"] += st.st_size
            if digest and cache is not None:
                cache.put(path, st.st_size, st.st_mtime_ns, digest)
                seen_keys.add(HashCache._key(path, st.st_size, st.st_mtime_ns))
            found.append(Seen(path, st.st_size, st.st_mtime, digest))
    if cache is not None:
        cache.keep_only(seen_keys)
    if stats is not None:
        stats.update(counts)
    return sorted(found, key=lambda s: s.path)


def taken(seen, full_path):
    """`seen` with when and where it was taken, read from the file at
    `full_path` if it is a photo or a video."""
    import dataclasses
    if not is_media(seen.path):
        return seen
    from ontodag import capture
    return dataclasses.replace(seen, taken=capture.of_file(full_path))


def look_at(path, cache=None):
    """A single file anywhere on this computer, as `Seen`: its path is its
    folder's name and its own (`Downloads/IMG_2041.jpg`), as a folder's
    files are named inside it, and it is hashed unless the cache knows it."""
    full = os.path.abspath(path)
    if not os.path.isfile(full):
        raise ValueError(f"{path} is not a file")
    st = os.stat(full)
    folder = os.path.basename(os.path.dirname(full))
    name = f"{folder}/{os.path.basename(full)}" if folder else os.path.basename(full)
    digest = cache.get(full, st.st_size, st.st_mtime_ns) if cache else None
    if not digest:
        digest = hash_file(full)
        if cache is not None:
            cache.put(full, st.st_size, st.st_mtime_ns, digest)
    return Seen(name, st.st_size, st.st_mtime, digest)


class Folder:
    """What one look at a folder found: its files grouped by content, and
    the folder's layer (each content under its kind)."""

    def __init__(self, seen):
        self.seen = list(seen)
        self.by_hash = {}
        self.unhashed = []
        for s in self.seen:
            if s.sha256:
                self.by_hash.setdefault(s.sha256, []).append(s)
            else:
                self.unhashed.append(s)

    def layer(self):
        """The folder's layer as (item, parents): every content under the
        kind its file's extension names. Rebuilt at every look, never
        stored."""
        out = []
        for digest, files in sorted(self.by_hash.items()):
            kinds = sorted({kind_of(f.path) for f in files} - {None})
            if kinds:
                out.append((version_name(digest), kinds))
        return out

    def kinds(self):
        return sorted({k for _item, kinds in self.layer() for k in kinds})


# -- your store's side ------------------------------------------------------ #

def versions_of(dag, doc):
    """The versions below a document (its direct children named by a hash)."""
    node = dag.nodes.get(doc)
    if node is None:
        return []
    return sorted(c.name for c in node.neighbors if is_version(c.name))


def _reads_as_term(dag, name):
    try:
        return dag.parse_term(name) is not None
    except ValueError:
        return True


def _is_document(dag, name):
    """Is a version's parent `name` its document, not one of its values
    (`modification-time(…)`, `capture-geo(…)`, or `time(…)` as versions
    were filed before the organiser's heads)?"""
    return name != "*" and not ("(" in name and _reads_as_term(dag, name))


def documents(dag):
    """Every document in the store: {name: [its versions]}."""
    found = {}
    for name, node in dag.nodes.items():
        if not is_version(name):
            continue
        for p in node.parents:
            if _is_document(dag, p.name):
                found.setdefault(p.name, []).append(name)
    return {d: sorted(v) for d, v in sorted(found.items())}


def document_of(dag, version):
    """The document a version belongs to, or None."""
    node = dag.nodes.get(version)
    if node is None:
        return None
    for p in sorted(node.parents, key=lambda p: p.name):
        if _is_document(dag, p.name):
            return p.name
    return None


def document_name(dag, seen):
    """The name a newly filed file's document gets: the file's name, unless
    the store has a node of that name already (then the file's folder is
    added, `IMG_0001.jpg (Rome 2026)`, and a number if need be), or the name
    would read as a typed value (a file called `time(2026)`)."""
    base = seen.name
    if _reads_as_term(dag, base) and "(" in base:
        base = f"{base} (file)"
    if base not in dag.nodes:
        return base
    folder = seen.folder.rsplit("/", 1)[-1]
    if folder:
        named = f"{base} ({folder})"
        if named not in dag.nodes:
            return named
    for i in range(2, 10_000):
        named = f"{base} ({i})"
        if named not in dag.nodes:
            return named
    raise ValueError(f"no free name for {seen.path}")


def named_like(dag, seen):
    """The documents named as this file is (its name, or its name with a
    folder or number added): a new content under one of them may be its new
    version."""
    return sorted(d for d in documents(dag) if d == seen.name or d.startswith(f"{seen.name} ("))


def _ensure_heads(dag):
    """The prelude's declarations, which the organiser's heads stand on, and
    those heads (`HEADS`), where missing; the number of nodes they added."""
    if all(name in dag.nodes for name, _parents in HEADS):
        return 0
    before = len(dag.nodes)
    if "time" not in dag.nodes:
        from ontodag import prelude
        prelude.apply(dag)
    for name, parents in HEADS:
        if name not in dag.nodes:
            dag.put(name, parents)
    return len(dag.nodes) - before


def version_parents(doc, seen):
    """What a content is filed under as a version of `doc`: the document,
    when the content was last modified, and when and where it was taken, as
    far as `seen.taken` says."""
    return [doc, modification_time(seen.mtime)] + (seen.taken.terms() if seen.taken else [])


def attach(dag, seen, doc):
    """File the content `seen` as a version of the document `doc`; returns
    what it was filed under."""
    _ensure_heads(dag)
    parents = version_parents(doc, seen)
    dag.put(version_name(seen.sha256), parents)
    return parents


def file(dag, seen, categories=(), version_of=None):
    """File a file: its document under `categories`, and its content as a
    version. The document is the one the content is already a version of,
    or `version_of` (the person said it is a new version of that document),
    or else a new one named by the file. A category the store lacks is put
    at its top first, as a name only. Returns what happened: the document,
    whether it was made, the categories made, the declarations added (the
    prelude's and the organiser's heads), and what a new version was filed
    under (`parents`, None if the content was filed already)."""
    if not seen.sha256:
        raise ValueError(f"{seen.path} was not hashed, so it cannot be filed")
    created = []
    for c in categories:
        if c not in dag.nodes and not _reads_as_term(dag, c):
            dag.put(c, [])
            created.append(c)
    prelude = _ensure_heads(dag)
    version = version_name(seen.sha256)
    doc = document_of(dag, version)
    parents = None
    if doc is None and version_of is not None:
        if version_of not in documents(dag):
            raise ValueError(f"{version_of} is not a document in this store")
        doc = version_of
        parents = version_parents(doc, seen)
        dag.put(version, parents)
    made = doc is None
    if made:
        doc = document_name(dag, seen)
        dag.put(doc, list(categories))
        parents = version_parents(doc, seen)
        dag.put(version, parents)
    elif categories:
        dag.put(doc, list(categories))
    return {"document": doc, "version": version, "made": made, "created": created,
            "prelude": prelude, "parents": parents}


def unfiled(dag, folder):
    """The folder's contents the store does not know, as {sha256: [Seen]};
    copies are one."""
    return {h: files for h, files in sorted(folder.by_hash.items())
            if version_name(h) not in dag.nodes}


def recognise_edits(dag, folder):
    """Contents that are new versions of documents the store has: a file
    whose content is not a known version, named as a document none of whose
    versions is in the folder any more. Returns (edits, ambiguous): edits as
    (Seen, document) where one document fits, ambiguous as (Seen,
    [documents]) where several do. Nothing is written."""
    docs = documents(dag)
    present = {version_name(h) for h in folder.by_hash}
    vanished = {d for d, versions in docs.items() if not present.intersection(versions)}
    edits, ambiguous, claimed = [], [], {}
    for digest, files in unfiled(dag, folder).items():
        for s in files:
            fits = sorted(d for d in vanished if d == s.name or d.startswith(f"{s.name} ("))
            if len(fits) > 1:
                exact = [d for d in fits if d == f"{s.name} ({s.folder.rsplit('/', 1)[-1]})"]
                fits = exact or fits
            if len(fits) == 1:
                claimed.setdefault(fits[0], []).append(s)
                break
            if fits:
                ambiguous.append((s, fits))
                break
    for doc, claims in sorted(claimed.items()):
        if len(claims) == 1:
            edits.append((claims[0], doc))
        else:
            ambiguous.extend((s, [doc]) for s in claims)
    return edits, ambiguous
