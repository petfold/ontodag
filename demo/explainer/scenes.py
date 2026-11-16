"""The film: what is on the stage, and when.

Every time here hangs on the narration (`out/timeline.json`): `at("d3")` is
when line d3 begins, `at("d3", "flight")` when that word of it is heard. So
the pictures keep step with the voice whatever its pace, and a change to the
script moves them with it. What the screen quotes from `odag` (commands,
answers, roots) is read from `out/facts.json`, which `facts.py` wrote by
running them.
"""

import json
import math
from pathlib import Path

import anim
from anim import (AMBER, BLUE, GREEN, HAIR, INK, MONO, MUTED, PAPER, PURPLE,
                  RED, SKY, SLATE, WHITE, Custom, Edge, Group, Node, Region,
                  Stage, Text, Track, ease_out, fade, linear, rounded, source,
                  tint, write)

HERE = Path(__file__).resolve().parent

LEFT = 96                       # the left margin
HEAD_Y, TITLE_Y = 78, 140       # a scene's label and its headline
TERM_Y, TERM_STEP = 906, 44     # the command line and the answers under it
CODE = 28                       # the size of what is typed

OUT, PASS = "japan-outbound.pdf", "boarding-pass.png"
TOKYO, BERLIN = "hotel-tokyo.pdf", "berlin-flight.pdf"
KYOTO, RAIL = "hotel-kyoto.pdf", "rail-pass.pdf"


class Clock:
    """When things are said."""

    def __init__(self, timeline):
        self.lines, self.scenes = timeline["lines"], timeline["scenes"]
        self.duration = timeline["duration"]

    def __call__(self, line, word=None, nth=1):
        entry = self.lines[line]
        if word is None:
            return entry["start"]
        seen = 0
        for spoken, start, _ in entry["words"]:
            if spoken.strip("'\"").lower() == word.lower():
                seen += 1
                if seen == nth:
                    return start
        raise KeyError((line, word, nth))

    def end(self, line):
        return self.lines[line]["end"]

    def scene(self, name):
        return self.scenes[name]["start"], self.scenes[name]["end"]


def _load(name):
    return json.loads((HERE / "out" / name).read_text())


def duration():
    return _load("timeline.json")["duration"]


# ------------------------------------------------------- shared furniture

def heading(S, label, start, end):
    """A scene's small label, top left."""
    spaced = f'<span letter_spacing="3200">{label.upper()}</span>'
    small = Text(S, spaced, LEFT, HEAD_Y, size=20, weight="Bold",
                 color=MUTED, markup=True)
    small.show(start + 0.3, 0.6).hide(end - 0.7, 0.5)
    return small


def headline(S, text, start, end, markup=False):
    """The sentence a scene turns on, under its label."""
    line = Text(S, text, LEFT, TITLE_Y, size=42, weight="Semibold",
                markup=markup)
    line.rise(start, 0.7).hide(end, 0.5)
    return line


class Terminal:
    """The commands typed at the foot of the screen, and their answers."""

    def __init__(self, S, x=LEFT, y=TERM_Y):
        self.S, self.x, self.y = S, x, y
        self.shown, self.rows = [], 0

    def run(self, t, command, answer=(), wait=0.3, rate=36.0, color=SLATE,
            answer_at=None, keep=False):
        """Type a command at `t`; its answer follows. Returns when."""
        if not keep:
            self.clear(t - 0.3)
        row = self.y + TERM_STEP * self.rows
        prompt = Text(self.S, "$", self.x, row, size=CODE, family=MONO,
                      color=MUTED)
        prompt.show(t - 0.1, 0.2)
        line = Text(self.S, command, self.x + 36, row, size=CODE,
                    family=MONO, color=INK)
        typed = line.type(t, rate)
        when = answer_at if answer_at is not None else typed + wait
        self.shown += [prompt, line]
        for number, text in enumerate(answer):
            out = Text(self.S, text, self.x + 36,
                       row + TERM_STEP * (number + 1), size=CODE,
                       family=MONO, color=color)
            out.show(when + 0.13 * number, 0.3)
            self.shown.append(out)
        self.rows += 1 + len(answer)
        return when

    def clear(self, t, dur=0.3):
        for thing in self.shown:
            thing.hide(t, dur)
        self.shown, self.rows = [], 0


class Trip:
    """The graph the film builds: a trip's paperwork under its categories."""

    PLACE = {
        "*": (1153, 150),
        "Flight": (641, 345), "Japan": (1164, 345), "Hotel": (1659, 345),
        BERLIN: (394, 560), OUT: (888, 560), TOKYO: (1440, 560),
        PASS: (888, 775),
        # what Alice and Bob add, in the scene where they merge
        KYOTO: (1680, 560), RAIL: (1164, 775),
    }
    # (above, below, where it leaves, where it arrives)
    LINKS = [
        ("*", "Flight", -14, 0), ("*", "Japan", 0, 0), ("*", "Hotel", 14, 0),
        ("Flight", BERLIN, -16, 0), ("Flight", OUT, 16, -26),
        ("Japan", OUT, -16, 26), ("Japan", TOKYO, 16, -26),
        ("Hotel", TOKYO, -8, 26), (OUT, PASS, 0, 0),
        ("Hotel", KYOTO, 14, 22), ("Japan", KYOTO, 34, -22),
        ("Japan", RAIL, 2, 0),
    ]
    BASE = ["*", "Flight", "Japan", "Hotel", BERLIN, OUT, TOKYO, PASS]

    def __init__(self, S, group=None, names=None, small=False, z=0):
        self.S, self.group = S, group
        self.n, self.e = {}, {}
        for name in names or self.BASE:
            x, y = self.PLACE[name]
            if name == "*":
                node = Star(S, "", x, y, group, z + 10, width=64)
            else:
                node = Node(S, name, x, y, group, z + 10)
            if small:                       # a miniature: shapes, no names
                node.label_opacity = Track(0.0)
                node.line_width = Track(4.0)
                if name != "*":
                    node.w *= 0.72
            self.n[name] = node
        for above, below, leave, arrive in self.LINKS:
            if above in self.n and below in self.n:
                edge = Edge(S, self.n[above], self.n[below], group, z + 5,
                            out=("bottom", leave), into=("top", arrive),
                            head=30.0 if small else 17.0,
                            gap=10 if small else 6)
                if small:
                    edge.width = Track(4.0)
                self.e[above, below] = edge

    def edges_of(self, name):
        return [edge for (_, below), edge in self.e.items() if below == name]

    def put(self, t, name, color=None):
        """A thing arrives, and then the arrows from what it is under."""
        self.n[name].appear(t)
        for edge in self.edges_of(name):
            edge.draw(t + 0.25, 0.6)
            if color:
                edge.line = Track(color)
        if color:
            self.n[name].line = Track(color)
            self.n[name].fill = Track(tint(color, 0.2))

    def show(self, t, names=None, dur=0.6):
        names = names or list(self.n)
        for name in names:
            self.n[name].show(t, dur)
        for (above, below), edge in self.e.items():
            if above in names and below in names:
                edge.progress.set(t, 1.0)
                edge.show(t, dur)

    def hide(self, t, dur=0.6):
        for thing in list(self.n.values()) + list(self.e.values()):
            thing.hide(t, dur)

    def where(self, name):
        """Where a node is on the stage, through the group it is in."""
        x, y = self.PLACE[name]
        g = self.group
        return g.x.initial + g.scale.initial * x, \
            g.y.initial + g.scale.initial * y

    def extent(self, names=None):
        """The box round some of its nodes: left, right, top, bottom."""
        boxes = [self.n[name].box(0.0) for name in names or self.n]
        return (min(x - w / 2 for x, _, w, _ in boxes),
                max(x + w / 2 for x, _, w, _ in boxes),
                min(y - h / 2 for _, y, _, h in boxes),
                max(y + h / 2 for _, y, _, h in boxes))


class Star(Node):
    """The root, `*`: above everything."""

    def paint(self, ctx, t, alpha):
        super().paint(ctx, t, alpha)
        x, y, w, _ = self.box(t)
        source(ctx, self.ink.at(t), alpha)
        ctx.set_line_width(max(3.0, self.line_width.at(t) * 1.3) * w / 64)
        ctx.set_line_cap(1)
        for k in range(3):
            angle = math.pi / 2 + k * math.pi / 3
            dx, dy = 12 * w / 64 * math.cos(angle), 12 * w / 64 * math.sin(angle)
            ctx.move_to(x - dx, y - dy)
            ctx.line_to(x + dx, y + dy)
        ctx.stroke()


def miniature(S, names, scale, top, left=None, right=None, center=None):
    """The graph small, its nodes without their names, placed by one side."""
    group = Group(0.0, 0.0, scale)
    trip = Trip(S, group, names, small=True)
    x0, x1, y0, _ = trip.extent()
    if left is not None:
        group.x.initial = left - scale * x0
    elif right is not None:
        group.x.initial = right - scale * x1
    else:
        group.x.initial = center - scale * (x0 + x1) / 2
    group.y.initial = top - scale * y0
    return trip


def plain(t, *things, dur=0.5):
    """Nodes and arrows back to their plain look."""
    for thing in things:
        thing.color(t, None, dur)
        if isinstance(thing, Node):
            thing.line_width.to(t, thing.line_width.initial, dur)


class Hex(anim.Thing):
    """A string worked out a character at a time, as a hash is."""

    def __init__(self, S, text, x, y, size=CODE, color=INK, anchor="l",
                 z=20):
        super().__init__(S, None, z)
        self.text, self.x, self.y, self.anchor = text, x, y, anchor
        self.font = f"{MONO} {size}px"
        self.cell = S.measure("0" * 20, self.font)[0] / 20
        self.color = Track(color)
        self.done = Track(0.0)          # characters settled
        self.agree = Track(0.0)         # characters found equal, from the left

    def work(self, t, dur=1.4):
        self.opacity.set(t, 1.0)
        self.done.set(t, 0.0)
        self.done.to(t, float(len(self.text)), dur, linear)
        return t + dur

    def width(self):
        return self.cell * len(self.text)

    def paint(self, ctx, t, alpha):
        text, cell = self.text, self.cell
        done, agree = int(self.done.at(t)), int(self.agree.at(t))
        left = self.x - {"l": 0.0, "c": 0.5, "r": 1.0}[self.anchor] \
            * cell * len(text)
        if agree:
            write(self.stage, ctx, text[:agree], self.font, left, self.y,
                  GREEN, alpha)
        if done > agree:
            write(self.stage, ctx, text[agree:done], self.font,
                  left + agree * cell, self.y, self.color.at(t), alpha)
        if done < len(text):
            beat = int(t * 15)
            churn = "".join(
                "0123456789abcdef"[(i * 7919 + beat * 104729 + i * i) % 16]
                for i in range(done, min(len(text), done + 5)))
            write(self.stage, ctx, churn, self.font, left + done * cell,
                  self.y, MUTED, alpha * 0.8)


def short(root):
    return root[:12] + "…"


# ------------------------------------------------------------- the scenes

ORANGE = anim.rgb("#fca746")        # the logo's own, lighter than AMBER


def emblem(S, cx, top):
    """The logo's graph: six dots and the arrows between them, unseen yet.
    Under it, the name and the line that goes with it."""
    spots = [(cx, top, BLUE), (cx - 124, top + 118, GREEN),
             (cx + 124, top + 118, ORANGE), (cx - 205, top + 268, PURPLE),
             (cx, top + 268, RED), (cx + 205, top + 268, SKY)]
    dots = []
    for x, y, color in spots:
        dot = Node(S, "", x, y, width=86, height=86)
        dot.fill, dot.line = Track(color), Track(color)
        dots.append(dot)
    arrows = [Edge(S, dots[a], dots[b], out=("toward", 0), into=("toward", 0),
                   gap=12, head=22.0)
              for a, b in ((0, 1), (0, 2), (1, 3), (1, 4), (2, 4), (2, 5))]
    for arrow in arrows:
        arrow.width = Track(5.5)
    word = Text(S, '<span foreground="#243140">Onto</span>'
                   '<span foreground="#157bf2">DAG</span>',
                cx, top + 452, size=118, weight="Black", anchor="c",
                markup=True)
    tag = Text(S, "categories beyond trees", cx, top + 548, size=38,
               color=SLATE, anchor="c")
    return dots, arrows, word, tag


def title(S, at):
    start, end = at.scene("title")
    dots, arrows, word, tag = emblem(S, 960, 258)
    t = start + 0.35
    dots[0].appear(t)
    for k, arrow in enumerate(arrows[:2]):
        arrow.draw(t + 0.25 + 0.08 * k, 0.45)
        dots[1 + k].appear(t + 0.55 + 0.08 * k)
    for k, arrow in enumerate(arrows[2:]):
        arrow.draw(t + 0.85 + 0.06 * k, 0.45)
    for k, dot in enumerate(dots[3:]):
        dot.appear(t + 1.15 + 0.08 * k)

    word.rise(at("i1") - 0.15, 0.8, by=20)
    tag.rise(at.end("i1") + 0.1, 0.8)

    # "under every category it belongs to": one thing, two arrows into it
    t = at("i2", "under")
    for arrow in (arrows[3], arrows[4]):
        arrow.width.to(t, 8.0, 0.35).to(at("i2", "Later") - 0.2, 5.5, 0.5)
    dots[4].ping(t + 0.2, RED)
    # "you name a few categories ... everything that falls under all of them"
    t = at("i2", "name")
    dots[1].ping(t, GREEN)
    dots[2].ping(t + 0.35, ORANGE)
    for k in (0, 3, 5):
        dots[k].opacity.to(t + 0.3, 0.3, 0.5).to(at.end("i2") + 0.3, 1.0, 0.6)
    for k in (0, 1, 2, 5):
        arrows[k].opacity.to(t + 0.3, 0.25, 0.5).to(
            at.end("i2") + 0.3, 1.0, 0.6)
    t = at("i2", "everything")
    dots[4].ping(t, RED)
    dots[4].scale.to(t, 1.14, 0.35, ease_out).to(at.end("i2") + 0.2, 1.0, 0.5)

    # "Let us build it up, one step at a time."
    t = at("i3", "one") - 0.2
    for k, dot in enumerate(dots):
        dot.scale.to(t + 0.16 * k, 1.13, 0.2, ease_out).to(
            t + 0.16 * k + 0.2, 1.0, 0.35)

    for thing in dots + arrows + [word, tag]:
        thing.hide(end - 0.9, 0.7)


def _folder(x, y, w=330, h=214):
    """A function drawing a folder centred on (x, y)."""
    def draw(ctx, t, alpha, self):
        left, top, r, tab_w, tab_h = x - w / 2, y - h / 2, 14, w * 0.4, 30
        ctx.new_path()
        ctx.arc(left + r, top + r, r, math.pi, 1.5 * math.pi)
        ctx.arc(left + tab_w - r, top + r, r, 1.5 * math.pi, 2 * math.pi)
        ctx.line_to(left + tab_w + 16, top + tab_h)
        ctx.arc(left + w - r, top + tab_h + r, r, 1.5 * math.pi, 2 * math.pi)
        ctx.arc(left + w - r, top + h - r, r, 0, 0.5 * math.pi)
        ctx.arc(left + r, top + h - r, r, 0.5 * math.pi, math.pi)
        ctx.close_path()
        source(ctx, self.fill.at(t), alpha)
        ctx.fill_preserve()
        source(ctx, self.line.at(t), alpha)
        ctx.set_line_width(2.5)
        ctx.stroke()
    return draw


def _chip(S, label, x, y, color=SLATE, z=10):
    chip = Node(S, label, x, y, z=z, size=23, weight="Medium", pad=18,
                height=44)
    chip.line = Track(fade(color, 0.75))
    chip.fill = Track(tint(color, 0.07))
    chip.line_width = Track(1.75)
    return chip


def folders(S, at):
    start, end = at.scene("folders")
    heading(S, "The trouble with folders", start, at("f3") - 0.1)
    heading(S, "The trouble with tags", at("f3") - 0.5, end)

    doc = Node(S, OUT, 960, 290, z=30)
    doc.appear(at("f1") - 0.2)
    note = Text(S, "a flight confirmation", 960, 350, size=25,
                weight="Italic", color=MUTED, anchor="c")
    note.show(at("f1") + 0.3, 0.6)

    lx, rx, fy = 610, 1310, 620
    boxes, names = [], []
    for x, name in ((lx, "Flights"), (rx, "Japan")):
        boxes.append(Custom(S, _folder(x, fy), z=5, fill=WHITE, line=SLATE))
        names.append(Text(S, name, x, fy + 150, size=31, weight="Medium",
                          anchor="c"))
    t = at("f1", "Where")
    for k, thing in enumerate(boxes + names):
        thing.show(t + 0.12 * (k % 2), 0.6)

    def into(t, k, color):
        note.hide(t - 0.1, 0.3)
        doc.move(t, (lx, rx)[k], fy + 12, 0.8)
        doc.scale.to(t, 0.84, 0.8)
        boxes[k].line.to(t + 0.3, color, 0.4)
        boxes[k].fill.to(t + 0.3, tint(color, 0.07), 0.4)
        boxes[1 - k].line.to(t + 0.3, SLATE, 0.4)
        boxes[1 - k].fill.to(t + 0.3, WHITE, 0.4)

    into(at("f1", "flights") - 0.2, 0, BLUE)
    into(at("f1", "Japan", 2) - 0.2, 1, AMBER)
    # "Folders make you choose one place."
    t = at("f2")
    doc.move(t, 960, 290, 0.9)
    doc.scale.to(t, 1.0, 0.9)
    for box in boxes:
        box.line.to(t, SLATE, 0.5)
        box.fill.to(t, WHITE, 0.5)
    # "whichever you choose, you will look in the other one first"
    into(at("f2", "whichever") + 0.2, 0, BLUE)
    t = at("f2", "look")
    boxes[1].line.to(t, AMBER, 0.3)
    empty = Text(S, "not here", rx, fy + 12, size=27, weight="Italic",
                 color=MUTED, anchor="c")
    empty.show(t + 0.45, 0.5)

    # ---- tags
    row, under = 500, 578
    t = at("f3") - 0.55
    for thing in boxes + names + [empty]:
        thing.hide(t, 0.5)
    doc.move(t + 0.2, 640, row, 0.9)
    doc.scale.to(t + 0.2, 1.0, 0.9)
    tags = [_chip(S, "flight", 574, under, BLUE),
            _chip(S, "japan", 702, under, AMBER)]
    tags[0].appear(at("f3", "one"))
    tags[1].appear(at("f3", "carry"))
    scan = Node(S, PASS, 1280, row, z=30)
    scan_tag = _chip(S, "boarding-pass", 1280, under, PURPLE)
    t = at("f3", "But")
    scan.appear(t + 0.3)
    scan_tag.appear(t + 0.7)
    scan_tag.ping(at("f4", "boarding"), PURPLE)

    # a search for "flight" finds one of them
    t = at("f4", "search") - 0.5
    fx, fy = 960, 310

    def field(ctx, t_, alpha, self):
        rounded(ctx, fx - 230, fy - 36, 460, 72, 36)
        source(ctx, WHITE, alpha)
        ctx.fill_preserve()
        source(ctx, SLATE, alpha)
        ctx.set_line_width(2.25)
        ctx.stroke()
        ctx.arc(fx - 186, fy - 3, 11, 0, 2 * math.pi)
        ctx.move_to(fx - 178, fy + 6)
        ctx.line_to(fx - 168, fy + 17)
        ctx.set_line_width(3.0)
        ctx.set_line_cap(1)
        ctx.stroke()

    box = Custom(S, field, z=5)
    box.show(t, 0.5)
    typed = Text(S, "flight", fx - 146, fy, size=31, family=MONO)
    typed.type(t + 0.5, 14.0)
    found = t + 1.05
    doc.color(found, BLUE)
    tags[0].line.to(found, BLUE, 0.4)
    tags[0].line_width.to(found, 2.6, 0.4)
    missed = at("f4", "miss")
    for thing in (scan, scan_tag):
        thing.opacity.to(missed, 0.28, 0.5)
    # "unless you remember to tag it as a flight as well. Every time."
    extra = [_chip(S, "flight", 1318, under, BLUE),
             _chip(S, "japan", 1423, under, AMBER)]
    t = at("f4", "remember")
    for thing in (scan, scan_tag):
        thing.opacity.to(t, 1.0, 0.5)
    t = at("f4", "flight") - 0.1
    scan_tag.move(t, 1232, None, 0.5)
    extra[0].x = Track(1366)
    extra[0].appear(t + 0.2)
    scan.color(t + 0.5, BLUE)
    extra[0].line.to(t + 0.5, BLUE, 0.4)
    extra[0].line_width.to(t + 0.5, 2.6, 0.4)
    t = at("f4", "Every")
    scan_tag.move(t, 1175, None, 0.5)
    extra[0].move(t, 1308, None, 0.5)
    extra[1].x = Track(1406)
    extra[1].appear(t + 0.2)
    for thing in [doc, scan, scan_tag, box, typed] + tags + extra:
        thing.hide(end - 0.8, 0.6)


def idea(S, at, trip, term):
    start, end = at.scene("idea")
    heading(S, "Filing", start, end)
    n, e = trip.n, trip.e

    # "OntoDAG keeps the good half of each."
    halves = [("from tags", "a thing in many categories", 470),
              ("from folders", "categories with structure", 550)]
    for k, (source_, kept, y) in enumerate(halves):
        for text, x, anchor, color in ((source_, 820, "r", MUTED),
                                       (kept, 850, "l", INK)):
            half = Text(S, text, x, y, size=40, anchor=anchor, color=color)
            half.rise(at("d1", "keeps") + 0.45 * k, 0.6)
            half.hide(at("d1", "Here") - 0.2, 0.5)

    # "Here are two categories: Flight, and Japan."
    t = at("d1", "Flight") - 0.15
    n["Flight"].appear(t)
    term.run(t, "odag put Flight")
    t = at("d1", "Japan") - 0.15
    n["Japan"].appear(t)
    term.run(t, "odag put Japan", keep=True)

    # "File the confirmation under both."
    term.run(at("d2") - 0.1, f"odag put {OUT} Flight Japan")
    n[OUT].appear(at("d2", "confirmation") - 0.1)
    for edge in trip.edges_of(OUT):
        edge.draw(at("d2", "under") - 0.1, 0.7)

    # "Now the boarding pass. ... file it under the flight itself."
    n[PASS].appear(at("d3", "boarding") - 0.1)
    term.run(at("d3", "file") - 0.4, f"odag put {PASS} {OUT}")
    e[OUT, PASS].draw(at("d3", "under") - 0.1, 0.7)

    # "An item and a category are the same kind of thing."
    term.clear(at("d4") - 0.1)
    n[OUT].ping(at("d4"))
    up, down = trip.edges_of(OUT), [e[OUT, PASS]]
    item = Text(S, "an item", 1086, 546, size=28, weight="Italic",
                color=MUTED)
    category = Text(S, "and a category", 1086, 588, size=28,
                    weight="Italic", color=MUTED)
    t = at("d4", "item")
    item.show(t, 0.4)
    for edge in up:
        edge.width.to(t, 4.0, 0.3).to(at("d4", "category"), 2.25, 0.4)
    t = at("d4", "category")
    category.show(t, 0.4)
    for edge in down:
        edge.width.to(t, 4.0, 0.3).to(at.end("d4") + 0.3, 2.25, 0.4)
    for note in (item, category):
        note.hide(at.end("d4") + 0.4, 0.4)

    # "whatever is below also belongs to what is above"
    headline(S, "What is below also belongs to what is above.",
             at("d5", "whatever") - 0.2, at("d6") - 0.5)
    t = at("d5", "boarding")
    n[PASS].ping(t)
    n[PASS].line_width.to(t, 3.4, 0.3)
    t = at("d5", "flight") - 0.15
    e[OUT, PASS].color(t, INK, width=3.4)
    e["Flight", OUT].color(t + 0.2, BLUE)
    n["Flight"].color(t + 0.45, BLUE)
    t = at("d5", "Japan") - 0.15
    e["Japan", OUT].color(t, AMBER)
    n["Japan"].color(t + 0.25, AMBER)
    plain(at("d6") - 0.6, n["Flight"], n["Japan"], n[PASS], e[OUT, PASS],
          e["Flight", OUT], e["Japan", OUT])

    # "Add a hotel booking, and a flight to Berlin."
    t = at("d6", "hotel") - 0.3
    n["Hotel"].appear(t)
    term.run(t, "odag put Hotel")
    n[TOKYO].appear(t + 0.55)
    for edge in trip.edges_of(TOKYO):
        edge.draw(t + 0.8, 0.6)
    term.run(t + 0.6, f"odag put {TOKYO} Hotel Japan", keep=True)
    t = at("d6", "flight") - 0.2
    n[BERLIN].appear(t)
    e["Flight", BERLIN].draw(t + 0.25, 0.6)
    term.run(t, f"odag put {BERLIN} Flight", keep=True)
    # "A single root sits above them all."
    t = at("d6", "root") - 0.3
    term.clear(t)
    n["*"].appear(t)
    for k, name in enumerate(("Flight", "Japan", "Hotel")):
        e["*", name].draw(t + 0.25 + 0.1 * k, 0.7)

    # "The arrows may meet, so this is not a tree."
    t = at("d7", "meet") - 0.1
    for k, name in enumerate((OUT, TOKYO)):
        n[name].ping(t + 0.2 * k)
        for edge in trip.edges_of(name):
            edge.width.to(t + 0.2 * k, 4.0, 0.3).to(at("d7", "so") + 0.6,
                                                    2.25, 0.5)
    # "It is a directed acyclic graph, or DAG."
    blue = '<span foreground="#157bf2">%s</span>'
    words = (blue % "D" + "irected " + blue % "A" + "cyclic "
             + blue % "G" + "raph")
    name = Text(S, words, LEFT, TITLE_Y, size=42, weight="Semibold",
                markup=True)
    name.rise(at("d7", "directed") - 0.2, 0.7)
    dash = Text(S, "—", LEFT + name.extent()[0] + 26, TITLE_Y, size=42,
                color=MUTED)
    mark = Text(S, '<span foreground="#243140">Onto</span>' + blue % "DAG",
                LEFT + name.extent()[0] + 92, TITLE_Y, size=42,
                weight="Black", markup=True)
    t = at("d7", "name") - 0.3
    dash.show(t, 0.5)
    mark.rise(t + 0.1, 0.7)
    for thing in (name, dash, mark):
        thing.hide(end - 0.7, 0.5)


def question(S, at, trip, term):
    start, end = at.scene("question")
    heading(S, "Asking", start, end)
    n, facts = trip.n, S.facts["trip"]
    cone_j = Region(S, [n[x] for x in ("Japan", OUT, TOKYO, PASS)], AMBER)
    cone_f = Region(S, [n[x] for x in ("Flight", BERLIN, OUT, PASS)], BLUE,
                    strength=0.13)
    both = Region(S, [n[OUT], n[PASS]], GREEN, strength=0.26, z=2)

    # "Everything below a category is its cone."
    headline(S, "A cone: everything below a category.",
             at("q1") + 0.1, at("q4") - 0.5)
    t = at("q1", "below") - 0.2
    n["Japan"].color(t, AMBER, fill=0.2)
    cone_j.pour(t + 0.15, 1.2)

    # "Ask for Japan, and you get its cone"
    told = term.run(at("q2") - 0.1, "odag get Japan", facts["get Japan"],
                    answer_at=at("q2", "cone") - 0.1)
    for k, name in enumerate((PASS, TOKYO, OUT)):
        n[name].color(told + 0.13 * k, AMBER)
    n[PASS].ping(at("q2", "boarding"), AMBER)

    # "Ask for two categories, and you get what lies in both cones."
    told = term.run(at("q3") - 0.1, "odag get Flight Japan",
                    facts["get Flight Japan"], answer_at=at("q3", "Here"))
    t = at("q3", "two") - 0.1
    n["Flight"].color(t, BLUE, fill=0.2)
    cone_f.pour(t + 0.15, 1.2)
    n[BERLIN].color(t + 0.8, BLUE)
    t = at("q3", "both") - 0.1
    both.show(t, 0.6)
    cone_j.strength.to(t, 0.09, 0.6)
    cone_f.strength.to(t, 0.075, 0.6)
    for name in (OUT, PASS):
        n[name].color(t + 0.2, GREEN, fill=0.2)
        n[name].line_width.to(t + 0.2, 3.0, 0.4)
    # "Not the hotel, and not the flight to Berlin."
    for word, name in (("hotel", TOKYO), ("Berlin", BERLIN)):
        t = at("q3", word, 1) - 0.15
        for thing in [n[name]] + trip.edges_of(name):
            thing.opacity.to(t, 0.25, 0.4).to(at("q4") - 0.1, 1.0, 0.6)

    # "One question: what is below all of these?"
    headline(S, "One question: what is below all of these?",
             at("q4", "One") - 0.2, end - 0.7)
    # "The order of the words does not matter."
    term.run(at("q4", "order") - 0.3, "odag get Japan Flight",
             facts["get Japan Flight"], answer_at=at("q4", "does"))
    t = end - 0.9
    for region in (cone_j, cone_f, both):
        region.hide(t, 0.6)
    plain(t, *n.values())
    term.clear(t)


def rule(S, at, trip, term):
    start, end = at.scene("rule")
    heading(S, "One rule", start, end)
    n, e, facts = trip.n, trip.e, S.facts["trip"]
    headline(S, "Keep no link that the others already imply.",
             at("r1", "Keep") - 0.2, at("r4") - 0.5)

    # "Try to file the boarding pass under Japan directly"
    term.run(at("r2") + 0.2, f"odag put {PASS} Japan")
    extra = Edge(S, n["Japan"], n[PASS], z=6, dashed=True, bend=-0.16,
                 out=("bottom", 44), into=("right", 0))
    extra.line = Track(AMBER)
    extra.width = Track(3.0)
    extra.draw(at("r2", "under") - 0.2, 0.9)
    said = Text(S, "already implied", 1176, 716, size=28, weight="Italic",
                color=MUTED)
    t = at("r2", "nothing") - 0.1
    for edge in (e["Japan", OUT], e[OUT, PASS]):
        edge.color(t, AMBER, width=3.6)
    said.show(t + 0.2, 0.4)
    extra.hide(at("r2", "graph") - 0.2, 0.7)
    t = at.end("r2") + 0.3
    said.hide(t, 0.4)
    plain(t, e["Japan", OUT], e[OUT, PASS])

    # "And no loops."
    loop = Edge(S, n[PASS], n["Flight"], z=6, dashed=True, bend=-0.07,
                out=("left", 0), into=("bottom", -46))
    loop.line = Track(RED)
    loop.width = Track(3.0)
    typed = at("r3", "Nothing") - 0.4
    term.run(typed, f"odag put Flight {PASS}", [facts["loop"]["said"]],
             color=RED, answer_at=at("r3", "refuses") - 0.1)
    loop.draw(at("r3", "Nothing") + 0.3, 0.9)
    t = at("r3", "below")
    for edge in (e["Flight", OUT], e[OUT, PASS]):
        edge.color(t, RED, width=3.6)
    t = at("r3", "refuses") - 0.1
    loop.hide(t + 0.5, 0.6)
    plain(at.end("r3") + 0.4, e["Flight", OUT], e[OUT, PASS])

    # "Because a graph like this has exactly one smallest form."
    term.clear(at("r4") - 0.1)
    headline(S, "A graph like this has exactly one smallest form.",
             at("r4", "Because") - 0.2, end - 0.7)

    # "So build it in any order, with any detours ..."
    ghost = Trip(S, z=-8)
    for node in ghost.n.values():
        node.line, node.fill = Track(HAIR), Track(PAPER)
        node.ink = Track(fade(MUTED, 0.5))
    for edge in ghost.e.values():
        edge.line = Track(HAIR)
    t = at("r5") - 0.5
    for thing in list(n.values()) + list(e.values()):
        thing.hide(t, 0.5)
    ghost.show(t, dur=0.5)
    detour = Edge(S, n["Japan"], n[PASS], z=6, bend=-0.16,
                  out=("bottom", 44), into=("right", 0))
    step, t = 0.5, at("r5", "build") - 0.1
    n["*"].appear(t)
    order = [("Japan", []), (PASS, [detour]), ("Hotel", []),
             (TOKYO, trip.edges_of(TOKYO)), ("Flight", []),
             (BERLIN, trip.edges_of(BERLIN)), (OUT, trip.edges_of(OUT))]
    for k, (name, arrows) in enumerate(order):
        when = t + 0.15 + step * k
        n[name].appear(when, 0.4)
        if ("*", name) in e:
            e["*", name].draw(when + 0.1, 0.4)
        for arrow in arrows:
            arrow.draw(when + 0.2, 0.45)
    when = t + 0.15 + step * len(order)
    e[OUT, PASS].draw(when, 0.45)           # under the flight after all:
    detour.line.to(when + 0.3, RED, 0.25)   # the direct link is dropped
    detour.hide(when + 0.55, 0.5)
    ghost.hide(when + 1.2, 0.6)


def root(S, at, trip):
    start, end = at.scene("root")
    heading(S, "The root", start, end)
    n, facts = trip.n, S.facts
    hx = LEFT + 258
    rows = (TERM_Y + 6, TERM_Y + 66)
    one = Hex(S, facts["trip"]["root"], hx, rows[0], size=32)
    two = Hex(S, facts["again"]["root"], hx, rows[1], size=32)
    name = Text(S, "root", hx - 26, rows[0], size=32, family=MONO,
                color=MUTED, anchor="r")
    first = Text(S, "in one order", hx - 26, rows[0], size=26,
                 weight="Italic", color=MUTED, anchor="r")
    second = Text(S, "in another order", hx - 26, rows[1], size=26,
                  weight="Italic", color=MUTED, anchor="r")

    # "One shape can have one fingerprint"
    t = at("p1", "shape") - 0.1
    for k, node in enumerate(n.values()):
        node.ping(t + 0.04 * k)
    headline(S, "One shape, one fingerprint.", at("p1", "fingerprint") - 0.3,
             at("p2", "Equal") - 0.6)
    one.work(at("p1", "fingerprint") - 0.1, 2.2)
    name.show(at("p1", "root") - 0.2, 0.4)

    # "Two people who file the same facts, in any order, get the same root"
    t = at("p2") - 0.1
    name.hide(t, 0.3)
    first.show(t + 0.2, 0.4)
    second.show(at("p2", "any") - 0.2, 0.4)
    two.work(at("p2", "get") - 0.2, 1.6)
    t = at("p2", "last") - 0.5
    for line in (one, two):
        line.agree.set(t, 0.0)
        line.agree.to(t, 64.0, 1.5, linear)
    headline(S, "Equal knowledge, equal root.", at("p2", "Equal") - 0.2,
             end - 0.7)
    same = Text(S, "=", hx + one.width() + 34, (rows[0] + rows[1]) / 2,
                size=44, weight="Bold", color=GREEN)
    same.show(at("p2", "Equal"), 0.4)
    t = end - 0.8
    for thing in (one, two, first, second, same):
        thing.hide(t, 0.6)
    trip.hide(t, 0.6)


def merge(S, at):
    start, end = at.scene("merge")
    heading(S, "Merging", start, end)
    facts, s = S.facts["merge"], 0.52
    names = Trip.BASE + [KYOTO, RAIL]
    a = miniature(S, names, s, 350, left=LEFT + 20)
    b = miniature(S, names, s, 350, right=anim.W - LEFT - 20)
    x0, x1, _, _ = a.extent(Trip.BASE)
    ax = a.group.x.initial + s * (x0 + x1) / 2
    bx = b.group.x.initial + s * (x0 + x1) / 2
    who = [Text(S, "Alice", ax, 286, size=36, weight="Semibold", anchor="c"),
           Text(S, "Bob", bx, 286, size=36, weight="Semibold", anchor="c")]
    hy = 838
    hashes = [Hex(S, short(facts["start"][0]), ax, hy, size=34, anchor="c"),
              Hex(S, short(facts["start"][1]), bx, hy, size=34, anchor="c")]
    labels = [Text(S, "root", x, hy - 48, size=24, weight="Italic",
                   color=MUTED, anchor="c") for x in (ax, bx)]
    t = start + 0.5
    for trip in (a, b):
        trip.show(t, Trip.BASE, dur=0.7)
    for k, thing in enumerate(who + labels):
        thing.show(t + 0.1, 0.7)
    for line in hashes:
        line.work(t + 0.4, 0.9)
    headline(S, "People can work apart.", at("m1") - 0.1, at("m3") - 0.5)

    def tagged(trip, name, color, t):
        """The name of a new node: beside it, or under it at the edge."""
        x, y = trip.where(name)
        if name == RAIL:
            tag = Text(S, name, x + trip.n[name].w * s / 2 + 14, y, size=26,
                       weight="Medium", color=color)
        else:
            tag = Text(S, name, x, y + 42, size=26, weight="Medium",
                       color=color, anchor="c")
        tag.show(t, 0.5)
        return tag

    def change(k, new, color, t, dur=0.9):
        hashes[k].hide(t, 0.15)
        hashes[k] = Hex(S, short(new), (ax, bx)[k], hy, size=34,
                        color=color, anchor="c")
        hashes[k].work(t + 0.1, dur)

    # "Alice adds a hotel in Kyoto. Bob adds a rail pass."
    t = at("m1", "Alice")
    a.put(t + 0.3, KYOTO, PURPLE)
    tags = [tagged(a, KYOTO, PURPLE, t + 0.5)]
    change(0, facts["apart"][0], PURPLE, t + 0.9)
    t = at("m1", "Bob")
    b.put(t + 0.3, RAIL, AMBER)
    tags.append(tagged(b, RAIL, AMBER, t + 0.5))
    change(1, facts["apart"][1], AMBER, t + 0.9)

    # "When they merge, each store takes in what the other knows"
    def cross(t, source_trip, target_trip, name, color, land=True):
        (x0, y0), (x1, y1) = source_trip.where(name), target_trip.where(name)
        node = source_trip.n[name]
        flyer = Node(S, "", x0, y0, z=40, width=node.w * s, height=node.h * s)
        flyer.line, flyer.fill = Track(color), Track(tint(color, 0.2))
        flyer.show(t, 0.2)
        flyer.x.to(t, x1, 1.1)
        flyer.y.to(t, min(y0, y1) - 120, 0.55, ease_out)
        flyer.y.to(t + 0.55, y1, 0.55, anim.ease_in)
        flyer.hide(t + 1.0, 0.2)
        if land:
            target_trip.put(t + 1.0, name, color)
            tags.append(tagged(target_trip, name, color, t + 1.2))
        else:
            target_trip.n[name].ping(t + 1.05, color)

    t = at("m2", "merge") - 0.1
    cross(t, a, b, KYOTO, PURPLE)
    cross(t + 0.25, b, a, RAIL, AMBER)

    # "Both arrive at the same root."
    headline(S, "Both arrive at the same root.", at("m3") - 0.1, end - 0.7)
    t = at("m3", "same") - 0.3
    for k in (0, 1):
        change(k, facts["merged"][k], GREEN, t, 0.8)
    same = Text(S, "=", 960, hy, size=54, weight="Bold", color=GREEN,
                anchor="c")
    same.show(t + 0.8, 0.4)
    # "Merge again, and nothing changes."
    t = at("m3", "Merge")
    cross(t, a, b, KYOTO, PURPLE, land=False)
    cross(t + 0.2, b, a, RAIL, AMBER, land=False)

    t = end - 0.8
    for thing in who + labels + hashes + tags + [same]:
        thing.hide(t, 0.6)
    a.hide(t)
    b.hide(t)


def values(S, at, term):
    start, end = at.scene("values")
    heading(S, "Values", start, end)
    facts = S.facts
    x0, x1, axis = 180, 1740, 500
    months = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

    def day(month, date):
        """Where a day of 2026 starts on the axis."""
        return x0 + (sum(months[:month - 1]) + date - 1) / 365 * (x1 - x0)

    def draw_axis(ctx, t, alpha, self):
        reach = x0 + (x1 - x0) * self.drawn.at(t)
        source(ctx, SLATE, alpha)
        ctx.set_line_width(2.5)
        ctx.set_line_cap(1)
        ctx.move_to(x0, axis)
        ctx.line_to(reach, axis)
        ctx.stroke()
        names = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
        shown = self.named.at(t)
        for k in range(13):
            x = day(k + 1, 1) if k < 12 else x1
            if x <= reach + 0.5:
                ctx.move_to(x, axis - 9)
                ctx.line_to(x, axis + 9)
                ctx.stroke()
            if k < 12 and shown > 0:
                write(S, ctx, names[k], f"{anim.SANS} 23px",
                      (x + day(k + 2, 1)) / 2 if k < 11 else (x + x1) / 2,
                      axis + 36, MUTED, alpha * shown, "c")

    line = Custom(S, draw_axis, z=4, drawn=0.0, named=0.0)
    year = Text(S, "2026", x0 - 22, axis, size=26, weight="Bold",
                color=MUTED, anchor="r")
    t = at("v1") - 0.6
    line.show(t, 0.2)
    line.drawn.to(t, 1.0, 1.3)
    line.named.to(at("v1", "Take") - 0.3, 1.0, 0.6)
    year.show(at("v1", "Take") - 0.3, 0.6)

    def flight(name, month, date, x, y):
        """A flight above the axis, with a stem down to its day."""
        px = (day(month, date) + day(month, date + 1)) / 2
        pill = Node(S, name, x, y, z=12)
        when = f"time(2026-{month:02d}-{date:02d})"

        def draw_stem(ctx, t, alpha, self):
            top = y + 38 + 44 * self.lower.at(t)
            reach = top + (axis - top) * self.drawn.at(t)
            source(ctx, self.line.at(t), alpha)
            ctx.set_line_width(2.25)
            ctx.move_to(px, top)
            ctx.line_to(px, reach)
            ctx.stroke()
            if self.drawn.at(t) > 0.95:
                ctx.arc(px, axis, 7, 0, 2 * math.pi)
                ctx.fill()

        stem = Custom(S, draw_stem, z=6, drawn=0.0, line=SLATE, lower=0.0)
        term_ = Text(S, when, x, y + 58, size=24, family=MONO, color=SLATE,
                     anchor="c")
        return pill, stem, term_, px

    out = flight(OUT, 8, 15, 1038, 236)
    back = flight("japan-return.pdf", 8, 29, 1318, 362)
    berlin = flight(BERLIN, 3, 2, 438, 362)

    def arrive(t, item, named=True):
        pill, stem, label, _ = item
        pill.appear(t)
        stem.show(t + 0.2, 0.2)
        stem.drawn.to(t + 0.2, 1.0, 0.6)
        if named:
            name_it(t + 0.5, item)

    def name_it(t, item):
        _, stem, label, _ = item
        label.show(t, 0.5)
        stem.lower.to(t, 1.0, 0.4)

    # "A flight on the fifteenth of August was in August, in the summer ..."
    arrive(at("v1", "flight") - 0.2, out, named=False)
    here = out[3]

    def bracket(a, b, y, label):
        def draw(ctx, t, alpha, self):
            grown = self.grow.at(t)
            left, right = here - (here - a) * grown, here + (b - here) * grown
            source(ctx, self.line.at(t), alpha)
            ctx.set_line_width(self.weight.at(t))
            ctx.set_line_cap(1)
            ctx.move_to(left, y - 12)
            ctx.line_to(left, y)
            ctx.line_to(right, y)
            ctx.line_to(right, y - 12)
            ctx.stroke()
        bar = Custom(S, draw, z=4, grow=0.0, line=SLATE, weight=2.5)
        name = Text(S, label, min(max((a + b) / 2, a + 110), x1 - 180),
                    y + 30, size=24, family=MONO, color=SLATE, anchor="c")
        return bar, name

    def open_(t, pair, dur=0.7):
        bar, name = pair
        bar.show(t, 0.2)
        bar.grow.to(t, 1.0, dur, ease_out)
        name.show(t + 0.3, 0.5)

    august = bracket(day(8, 1), day(9, 1), 610, "time(2026-08)")
    summer = bracket(day(6, 1), day(9, 1), 690, facts["flights"]["summer"])
    whole = bracket(x0, x1, 770, "time(2026)")

    def draw_drop(ctx, t, alpha, self):
        source(ctx, fade(SLATE, 0.5), alpha)
        ctx.set_line_width(1.5)
        ctx.set_dash([5, 7])
        ctx.move_to(here, axis + 10)
        ctx.line_to(here, axis + 10 + (770 - axis - 10) * self.drawn.at(t))
        ctx.stroke()
        ctx.set_dash([])

    drop = Custom(S, draw_drop, z=3, drawn=0.0)
    t = at("v1", "August", 2) - 0.25
    drop.show(t, 0.2)
    drop.drawn.to(t, 1.0, 2.2, ease_out)
    open_(t, august)
    open_(at("v1", "summer") - 0.3, summer)
    open_(at("v1", "twenty") - 0.3, whole)

    # "Nobody could file it under every period that contains it."
    # The periods between the three named ones: a week, a season and a half...
    spans = [(8, 15, 8, 16, 558), (8, 12, 8, 19, 584), (7, 15, 9, 15, 650),
             (5, 1, 10, 15, 730), (2, 15, 11, 20, 750)]
    others = []
    t = at("v2") - 0.1
    for pair in (august, summer, whole):
        pair[1].hide(t, 0.4)
    for k, (m0, d0, m1, d1, y) in enumerate(spans):
        bar, _ = bracket(day(m0, d0), day(m1, d1), y, "")
        bar.line, bar.weight = Track(fade(SLATE, 0.55)), Track(1.75)
        bar.show(t + 0.3 + 0.28 * k, 0.2)
        bar.grow.to(t + 0.3 + 0.28 * k, 1.0, 0.6, ease_out)
        others.append(bar)
    t = at("v3") - 0.4
    for bar in others:
        bar.hide(t, 0.5)
    for pair in (august, summer, whole):
        pair[1].show(at("v3", "names") - 0.5, 0.5)

    # "OntoDAG works out the order from the names themselves."
    headline(S, "The names themselves give the order.",
             at("v3", "OntoDAG") - 0.2, at("v5") - 0.5)
    name_it(at("v3", "names") - 0.3, out)
    t = at("v3", "names") - 0.1
    for k, pair in enumerate((august, summer, whole)):
        pair[1].color.to(t + 0.12 * k, BLUE, 0.3).to(at("v3", "File") - 0.2,
                                                     SLATE, 0.5)
    out[2].color.to(t, BLUE, 0.3).to(at("v3", "File") - 0.2, SLATE, 0.5)
    # "File each flight under its day."
    t = at("v3", "File") - 0.2
    term.run(t, "odag put japan-return.pdf Flight 'time(2026-08-29)'")
    arrive(t + 0.2, back)
    arrive(t + 0.6, berlin)

    # "Then ask for the flights in any stretch of time"
    t = at("v4") - 0.2
    for thing in august + whole + (drop,):
        thing.hide(t, 0.5)
    told = term.run(t + 0.2, "odag get Flight '%s'" % facts["flights"]["summer"],
                    facts["flights"]["get Flight summer"],
                    answer_at=at("v4", "computes") - 0.1)
    sa, sb = day(6, 1), day(9, 1)

    def draw_band(ctx, t, alpha, self):
        source(ctx, BLUE, alpha * 0.09)
        ctx.rectangle(sa, 196, sb - sa, 690 - 196)
        ctx.fill()

    band = Custom(S, draw_band, z=1)
    t = at("v4", "stretch") - 0.3
    band.show(t, 0.7)
    summer[0].line.to(t, BLUE, 0.4)
    summer[0].weight.to(t, 3.5, 0.4)
    summer[1].color.to(t, BLUE, 0.4)
    for item in (out, back):
        item[0].color(told, BLUE)
        item[1].line.to(told, BLUE, 0.4)
    for thing in berlin[:3]:
        thing.opacity.to(told, 0.3, 0.5)

    # "The same holds for masses and lengths, for sizes, and for places"
    t = at("v5") - 0.6
    term.clear(t)
    for thing in (line, year, band) + summer + out[:3] + back[:3] + berlin[:3]:
        thing.hide(t, 0.5)
    headline(S, "The same holds for other values.", at("v5") - 0.1,
             at("v6") - 0.6)
    cues = ("masses", "lengths", "sizes", "places")
    pairs = []
    for k, ((below, above, _), cue) in enumerate(zip(facts["pairs"], cues)):
        y = 330 + 92 * k
        row = [Text(S, below, 880, y, size=34, family=MONO, anchor="r"),
               Text(S, "is below", 960, y, size=28, weight="Italic",
                    color=MUTED, anchor="c"),
               Text(S, above, 1040, y, size=34, family=MONO)]
        for j, thing in enumerate(row):
            thing.rise(at("v5", cue) - 0.2 + 0.1 * j, 0.5)
        pairs += row

    # "OntoDAG stores five hundred grams as one half of a kilogram"
    headline(S, "And the arithmetic is exact.", at("v6") - 0.1, end - 0.7)
    t = at("v6", "OntoDAG") - 0.3
    for thing in pairs:
        thing.hide(t, 0.5)
    stored = facts["parcels"]["stored"]
    left, right, size = 590, 750, 48
    over = [Text(S, "what you type", left, 380, size=26, weight="Italic",
                 color=MUTED, anchor="r"),
            Text(S, "what is stored", right, 380, size=26, weight="Italic",
                 color=MUTED)]
    rows = []
    for typed_, y in (("mass(500g)", 460), ("mass(1lb)", 560)):
        rows.append([
            Text(S, typed_, left, y, size=size, family=MONO, anchor="r"),
            Text(S, "→", (left + right) / 2, y - 4, size=44, color=MUTED,
                 anchor="c"),
            Text(S, stored[typed_], right, y, size=size, family=MONO,
                 color=BLUE)])
    t = at("v6", "five") - 0.2
    rows[0][0].rise(t, 0.5)
    over[0].show(t + 0.1, 0.5)
    t = at("v6", "one") - 0.2
    rows[0][1].show(t - 0.2, 0.4)
    rows[0][2].rise(t, 0.5)
    over[1].show(t + 0.1, 0.5)
    # "never as a rounded number": a pound, to the last digit
    t = at("v6", "never") - 0.2
    rows[1][0].rise(t, 0.5)
    rows[1][1].show(t + 0.3, 0.4)
    rows[1][2].rise(t + 0.5, 0.5)
    for thing in sum(rows, []) + over:
        thing.hide(end - 0.8, 0.6)


def _person(x, y):
    def draw(ctx, t, alpha, self):
        source(ctx, WHITE, alpha)
        ctx.arc(x, y - 40, 26, 0, 2 * math.pi)
        ctx.fill()
        ctx.move_to(x - 54, y + 46)
        ctx.arc(x, y + 46, 54, math.pi, 2 * math.pi)
        ctx.close_path()
        ctx.fill()
        source(ctx, self.line.at(t), alpha)
        ctx.set_line_width(2.5)
        ctx.arc(x, y - 40, 26, 0, 2 * math.pi)
        ctx.stroke()
        ctx.move_to(x - 54, y + 46)
        ctx.arc(x, y + 46, 54, math.pi, 2 * math.pi)
        ctx.close_path()
        ctx.stroke()
    return draw


def proof(S, at, term):
    start, end = at.scene("proof")
    heading(S, "Proof", start, end)
    facts, s = S.facts["proof"], 0.5
    headline(S, "Answers you can prove.", at("c1", "answers") - 0.2,
             end - 0.7)
    store = miniature(S, None, s, 350, left=130)
    x0, x1, _, _ = store.extent()
    sx = store.group.x.initial + s * (x0 + x1) / 2
    px, hy = 1600, 790
    store.show(start + 0.5)
    person = Custom(S, _person(px, 520), z=5, line=SLATE)
    names = [Text(S, "the store", sx, 286, size=36, weight="Semibold",
                  anchor="c"),
             Text(S, "anyone", px, 286, size=36, weight="Semibold",
                  anchor="c")]
    labels = [Text(S, "root", x, hy - 48, size=24, weight="Italic",
                   color=MUTED, anchor="c") for x in (sx, px)]
    hashes = [Hex(S, short(facts["root"]), x, hy, size=34, anchor="c")
              for x in (sx, px)]
    names[0].show(start + 0.6, 0.6)
    labels[0].show(start + 0.6, 0.6)
    hashes[0].work(start + 0.8, 0.9)
    t = at("c1", "root") - 0.3
    hashes[0].color.to(t, BLUE, 0.4)

    # "Ask whether the boarding pass belongs to the Japan trip."
    term.run(at("c2") - 0.1, f"odag below {PASS} Japan",
             [S.facts["trip"]["below"]], color=GREEN,
             answer_at=at("c2", "Japan") + 0.5)
    t = at("c2", "boarding") - 0.1
    store.n[PASS].color(t, GREEN, fill=0.25)
    store.e[OUT, PASS].color(t + 0.3, GREEN, width=6.0)
    store.n[OUT].color(t + 0.5, GREEN, fill=0.25)
    store.e["Japan", OUT].color(t + 0.8, GREEN, width=6.0)
    store.n["Japan"].color(t + 1.0, GREEN, fill=0.25)

    # "The answer can come with a certificate"
    def card(ctx, t, alpha, self):
        x, y, k = self.x.at(t), self.y.at(t), self.scale.at(t)
        ctx.translate(x, y)
        ctx.scale(k, k)
        rounded(ctx, -120, -92, 240, 184, 16)
        source(ctx, WHITE, alpha)
        ctx.fill_preserve()
        source(ctx, self.line.at(t), alpha)
        ctx.set_line_width(2.5)
        ctx.stroke()
        write(S, ctx, "true", "Ubuntu Sans Mono Bold 30px", -92, -54, GREEN,
              alpha)
        for k_, width in enumerate((184, 150, 172, 128, 160)):
            rounded(ctx, -92, -24 + 20 * k_, width, 9, 4.5)
            source(ctx, fade(SLATE, 0.3), alpha)
            ctx.fill()
        sealed = self.seal.at(t)
        if sealed > 0:
            source(ctx, GREEN, alpha)
            ctx.arc(92, -56, 21, 0, 2 * math.pi)
            ctx.fill()
            source(ctx, WHITE, alpha)
            ctx.set_line_width(4.5)
            ctx.set_line_cap(1)
            ctx.set_line_join(1)
            ctx.move_to(82, -56)
            ctx.line_to(82 + 8 * min(1, sealed * 2), -56 + 8 * min(1, sealed * 2))
            if sealed > 0.5:
                more = (sealed - 0.5) * 2
                ctx.line_to(90 + 13 * more, -48 - 17 * more)
            ctx.stroke()

    paper = Custom(S, card, z=30, x=sx, y=520, scale=0.4, line=SLATE,
                   seal=0.0)
    caption = Text(S, "certificate · %d records" % facts["records"], 1090,
                   650, size=27, weight="Italic", color=MUTED, anchor="c")
    t = at("c2", "certificate") - 0.4
    paper.show(t, 0.4)
    paper.x.to(t, 1090, 0.9)
    paper.scale.to(t, 1.0, 0.9, ease_out)
    caption.show(t + 0.8, 0.5)

    # "Anyone can check it, holding nothing but the root."
    t = at("c3") - 0.2
    person.show(t, 0.6)
    names[1].show(t, 0.6)
    t = at("c3", "holding") - 0.2
    labels[1].show(t, 0.5)
    hashes[1].work(t, 0.8)
    hashes[1].color.to(t, BLUE, 0.1)
    t = at("c3", "check") - 0.2
    caption.hide(t, 0.3)
    paper.x.to(t, 1310, 1.0)
    paper.seal.to(at("c3", "root") + 0.3, 1.0, 0.5, ease_out)
    paper.line.to(at("c3", "root") + 0.3, GREEN, 0.4)
    checked = Text(S, "checked against the root", 1310, 650, size=27,
                   weight="Italic", color=GREEN, anchor="c")
    checked.show(at("c3", "root") + 0.5, 0.5)
    # "The store stays where it is."
    t = at("c3", "store") - 0.1
    for k, node in enumerate(store.n.values()):
        node.ping(t + 0.03 * k, SLATE)

    t = end - 0.8
    term.clear(t)
    for thing in [person, paper, checked] + names + labels + hashes:
        thing.hide(t, 0.6)
    store.hide(t)


def _homes(S):
    """The three pictures of where a store can live."""
    def page(ctx, x, y, alpha, color):
        ctx.move_to(x - 44, y - 58)
        ctx.line_to(x + 18, y - 58)
        ctx.line_to(x + 44, y - 32)
        ctx.line_to(x + 44, y + 58)
        ctx.line_to(x - 44, y + 58)
        ctx.close_path()
        source(ctx, WHITE, alpha)
        ctx.fill_preserve()
        source(ctx, color, alpha)
        ctx.set_line_width(2.5)
        ctx.set_line_join(1)
        ctx.stroke()
        ctx.move_to(x + 18, y - 58)
        ctx.line_to(x + 18, y - 32)
        ctx.line_to(x + 44, y - 32)
        ctx.stroke()
        for k, width in enumerate((40, 56, 48, 56)):
            ctx.move_to(x - 28, y - 14 + 17 * k)
            ctx.line_to(x - 28 + width, y - 14 + 17 * k)
        ctx.set_line_width(2.0)
        ctx.stroke()

    def stack(ctx, x, y, alpha, color):
        for k in (2, 1, 0):
            top = y - 50 + 34 * k
            rounded(ctx, x - 58, top, 116, 28, 9)
            source(ctx, WHITE, alpha)
            ctx.fill_preserve()
            source(ctx, color, alpha)
            ctx.set_line_width(2.5)
            ctx.stroke()
            ctx.arc(x - 40, top + 14, 3.5, 0, 2 * math.pi)
            ctx.fill()

    def comb(ctx, x, y, alpha, color):
        r = 31
        for cx, cy in ((x - 28, y - 25), (x + 28, y - 25), (x, y + 24)):
            for k in range(6):
                angle = math.pi / 6 + k * math.pi / 3
                px, py = cx + r * math.cos(angle), cy + r * math.sin(angle)
                if k:
                    ctx.line_to(px, py)
                else:
                    ctx.move_to(px, py)
            ctx.close_path()
            source(ctx, WHITE, alpha)
            ctx.fill_preserve()
            source(ctx, color, alpha)
            ctx.set_line_width(2.5)
            ctx.set_line_join(1)
            ctx.stroke()

    return page, stack, comb


def where(S, at):
    start, end = at.scene("where")
    heading(S, "Where a store lives", start, end)
    icons = _homes(S)
    homes = [("a text file", "works anywhere", "trip.od", "plain"),
             ("a record store", "keeps every version", "rs:trip", "local"),
             ("Swarm", "others can read it", "swarm:trip", "Swarm")]
    blue = '<span foreground="#157bf2">%s</span>'
    cards = []
    for k, (name, note, store, cue) in enumerate(homes):
        x, y = 420 + 540 * k, 400

        def draw(ctx, t, alpha, self, k=k, x=x, y=y):
            rounded(ctx, x - 220, y - 150, 440, 380, 22)
            source(ctx, WHITE, alpha)
            ctx.fill_preserve()
            source(ctx, HAIR, alpha)
            ctx.set_line_width(2.0)
            ctx.stroke()
            icons[k](ctx, x, y - 52, alpha, SLATE)

        things = [
            Custom(S, draw, z=4),
            Text(S, name, x, y + 62, size=36, weight="Semibold", anchor="c"),
            Text(S, note, x, y + 112, size=26, color=MUTED, anchor="c"),
            Text(S, store, x, y + 176, size=30, family=MONO, color=BLUE,
                 anchor="c")]
        t = at("w1", cue) - 0.3
        for j, thing in enumerate(things):
            thing.show(t + 0.08 * j, 0.6)
        cards += things
        # "The commands are the same for all three."
        same = Text(S, f"odag -f {blue % store} get Japan", x, y + 300,
                    size=25, family=MONO, anchor="c", markup=True)
        same.show(at("w2") - 0.1 + 0.25 * k, 0.5)
        cards.append(same)
    headline(S, "The commands are the same for all three.",
             at("w2") - 0.2, at("w3") - 0.5)

    # "And one store serves the command line, Python, a browser, an agent."
    t = at("w3") - 0.6
    for thing in cards:
        thing.hide(t, 0.5)
    headline(S, "One store, however you reach it.", at("w3") - 0.1,
             end - 0.7)
    cx, cy, s = 560, 560, 0.4
    store = miniature(S, None, s, cy - 138, center=cx)

    def tile(ctx, t, alpha, self):
        rounded(ctx, cx - 340, cy - 200, 680, 400, 24)
        source(ctx, WHITE, alpha)
        ctx.fill_preserve()
        source(ctx, HAIR, alpha)
        ctx.set_line_width(2.0)
        ctx.stroke()

    frame = Custom(S, tile, z=-12)
    frame.show(at("w3") - 0.3, 0.6)
    store.show(at("w3") - 0.3)
    # the web app (`odag web`) keeps a graph of its own; the page that opens
    # your store in a browser is the organiser
    ways = [("the command line", "odag", "command"),
            ("Python", "import ontodag", "Python"),
            ("a browser", None, "browser"),
            ("an AI agent", "odag-mcp", "AI")]
    shown = [frame]
    lx = 1250
    for k, (name, code, cue) in enumerate(ways):
        y = 330 + 150 * k

        def spoke(ctx, t, alpha, self, y=y):
            x0, y0, x3, y3 = cx + 352, cy, lx - 34, y
            source(ctx, fade(SLATE, 0.6), alpha)
            ctx.set_line_width(2.25)
            ctx.set_line_cap(1)
            grown, steps = self.drawn.at(t), 40
            ctx.move_to(x0, y0)
            for step in range(1, int(steps * grown) + 1):
                u = step / steps
                bend = 3 * u * u - 2 * u * u * u
                ctx.line_to(x0 + (x3 - x0) * u, y0 + (y3 - y0) * bend)
            ctx.stroke()

        line = Custom(S, spoke, z=3, drawn=0.0)
        t = at("w3", cue) - 0.4
        line.show(t, 0.2)
        line.drawn.to(t, 1.0, 0.6)
        label = Text(S, name, lx, y - 20, size=36, weight="Semibold")
        if code:
            code_ = Text(S, code, lx, y + 28, size=27, family=MONO,
                         color=BLUE)
        else:
            code_ = Text(S, "the organiser page", lx, y + 28, size=27,
                         weight="Italic", color=BLUE)
        label.rise(t + 0.3, 0.5)
        code_.show(t + 0.5, 0.5)
        shown += [line, label, code_]
    # "The agent gets the root with every answer"
    cites = Text(S, "answer + root " + short(S.facts["trip"]["root"]),
                 lx, 780 + 74, size=27, family=MONO, color=GREEN)
    cites.show(at("w3", "root") - 0.3, 0.5)
    t = end - 0.8
    for thing in shown + [cites]:
        thing.hide(t, 0.6)
    store.hide(t)


def close(S, at):
    start, end = at.scene("close")
    cx, top = 960, 250
    dots, arrows, word, tag = emblem(S, cx, top)
    t = at("e1") - 0.5
    for k, dot in enumerate(dots):
        dot.appear(t + 0.05 * k)
    for k, arrow in enumerate(arrows):
        arrow.draw(t + 0.2 + 0.05 * k, 0.5)
    three = [Text(S, words, x, top + 440, size=50, weight="Semibold",
                  anchor="c")
             for words, x in (("One graph.", 560), ("One rule.", 960),
                              ("One question.", 1360))]
    for k, line in enumerate(three):
        line.rise(at("e1", ("graph", "rule", "question")[k]) - 0.35, 0.6)
        line.hide(at("e2") - 0.4, 0.5)
    word.rise(at("e2", "OntoDAG") - 0.3, 0.8, by=20)
    tag.rise(at("e2", "categories") - 0.2, 0.8)
    get = Text(S, "pip install ontodag", cx, top + 664, size=28,
               family=MONO, color=SLATE, anchor="c")
    site = Text(S, "github.com/petfold/ontodag", cx, top + 712, size=26,
                color=MUTED, anchor="c")
    get.show(at.end("e2") + 0.3, 0.8)
    site.show(at.end("e2") + 0.5, 0.8)
    for thing in dots + arrows + [word, tag, get, site]:
        thing.hide(end - 0.7, 0.6)


def build():
    """The whole film, ready to draw any moment of."""
    S = Stage()
    S.facts = _load("facts.json")
    at = Clock(_load("timeline.json"))
    title(S, at)
    folders(S, at)
    trip, term = Trip(S), Terminal(S)
    idea(S, at, trip, term)
    question(S, at, trip, term)
    rule(S, at, trip, term)
    root(S, at, trip)
    merge(S, at)
    values(S, at, term)
    proof(S, at, term)
    where(S, at)
    close(S, at)
    return S

