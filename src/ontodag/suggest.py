"""Suggestions for a person naming a category (docs/plans/BROWSER.md §17).

Typing "phot" or "photo" in the organiser page offers names to pick: the
person's own first, then the shared vocabularies' (the packs), each with
where it sits there, and core's categories also by their other words from
WordNet (`ontodag.core_words`): "photo" offers `photograph`. A suggestion is
only offered. Nothing here writes, and a word is never read as the name it
suggests.
"""

import bisect

__all__ = ["Vocabularies", "key", "suggest"]


def key(text):
    """What a person typed, spelled as names are: lowercase, spaces as
    dashes."""
    return "-".join(text.strip().lower().split())


def _prefixed(names, prefix):
    """The names in a sorted list that start with `prefix`."""
    i = bisect.bisect_left(names, prefix)
    out = []
    while i < len(names) and names[i].startswith(prefix):
        out.append(names[i])
        i += 1
    return out


class Vocabularies:
    """Every pack's names, each with its parents in each pack that has it,
    read from the packs' canonical texts ({pack: .od text}); and core's
    other words."""

    def __init__(self, texts, words=None):
        from ontodag import native
        parsed = {pack: native._parse(texts[pack].splitlines(), pack)[0] for pack in texts}
        core = parsed.get("core", {})
        self.places = {}
        for pack in sorted(parsed):
            for name, parents in parsed[pack].items():
                parents = tuple(p for p in parents if p != "*")
                # A pack over core names core's categories it hangs things
                # from at its own top: borrowed, not placed.
                if name == "*" or (pack != "core" and name in core and not parents):
                    continue
                self.places.setdefault(name, []).append((pack, parents))
        self.names = sorted(self.places)
        if words is None:
            from ontodag.core_words import WORDS
            words = WORDS
        self.words = {name: tuple(ws) for name, ws in words if name in self.places}
        self.by_word = {}
        for name, ws in sorted(self.words.items()):
            for w in ws:
                self.by_word.setdefault(w, []).append(name)
        self.word_list = sorted(self.by_word)

    def packs_having(self, name):
        return [pack for pack, _parents in self.places.get(name, ())]


def suggest(text, vocab, mine=(), shown=(), limit=8):
    """Names for what a person typed, best first: theirs (exact, then
    starting with it), a vocabulary's name or word equal to it, then
    vocabularies' names and words starting with it (the vocabularies shown
    first, shorter first), then theirs containing it. Each is a dict:
    `name`, `mine` (in their store), `places` ([pack, parents] for every
    pack that has it), `word` (the word it was found by, if not its name)
    and `also` (its other words)."""
    k = key(text)
    if not k:
        return []
    shown = set(shown)
    mine = sorted(set(mine), key=lambda n: (n.lower(), n))
    mine_set = set(mine)
    out, seen = [], set()

    def add(name, word=None):
        if name in seen or len(out) >= limit:
            return
        seen.add(name)
        out.append({
            "name": name,
            "mine": name in mine_set,
            "places": [[pack, list(parents)] for pack, parents in vocab.places.get(name, ())],
            "word": word,
            "also": list(vocab.words.get(name, ())),
        })

    for n in mine:
        if n.lower() == k:
            add(n)
    for n in mine:
        if n.lower().startswith(k):
            add(n)
    if k in vocab.places:
        add(k)
    for n in vocab.by_word.get(k, ()):
        add(n, word=k)
    rank = lambda n: (not shown.intersection(vocab.packs_having(n)), len(n), n)
    for n in sorted(_prefixed(vocab.names, k), key=rank):
        add(n)
    for w in _prefixed(vocab.word_list, k):
        for n in sorted(vocab.by_word[w], key=rank):
            add(n, word=w)
    for n in mine:
        if k in n.lower():
            add(n)
    return out
