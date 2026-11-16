"""A small animation engine: things on a stage, every property a track in time.

Cairo draws and Pango sets the type (the system's `python3-cairo` and
`python3-gi`; nothing to install on a desktop Linux). A film is built by
making things (`Node`, `Edge`, `Text`, `Region`, `Custom`) and telling their
tracks where to be when:

    node = Node(stage, "Flight", 600, 300)
    node.appear(2.0)                       # at two seconds
    node.line.to(5.0, BLUE, 0.4)           # its outline turns blue at five

`Stage.paint(t)` then draws the frame of any moment, so a film can be looked
at one still at a time, and rendered in slices side by side.
"""

import bisect
import math

import cairo
import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo

W, H, FPS = 1920, 1080, 30

SANS = "Lato"
MONO = "Ubuntu Sans Mono Medium"


def rgb(code, alpha=1.0):
    code = code.lstrip("#")
    return tuple(int(code[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (alpha,)


def fade(color, alpha):
    return color[:3] + (alpha,)


def mix(a, b, amount):
    return tuple(x + (y - x) * amount for x, y in zip(a, b))


# The palette: the logo's colours on the project pages' paper.
PAPER = rgb("#fbfaf7")
WHITE = rgb("#ffffff")
INK = rgb("#243140")
SLATE = rgb("#3b4858")
MUTED = rgb("#8a8d8f")
HAIR = rgb("#d8d4cb")
BLUE = rgb("#157bf2")
AMBER = rgb("#f2941d")
GREEN = rgb("#1fa97a")
RED = rgb("#e9523f")
PURPLE = rgb("#8855d7")
SKY = rgb("#47b0fd")


def tint(color, amount=0.12):
    """A pale fill of a colour, for the inside of an outlined shape."""
    return mix(WHITE, color[:3] + (1.0,), amount)


# ------------------------------------------------------------------ easing

def linear(u):
    return u


def ease(u):
    """Slow, fast, slow."""
    return u * u * u * (u * (6 * u - 15) + 10)


def ease_out(u):
    return 1 - (1 - u) ** 3


def ease_in(u):
    return u ** 3


# ------------------------------------------------------------------ tracks

class Track:
    """One property through time: where it starts, and its moves."""

    def __init__(self, value):
        self.initial = value
        self.moves = []
        self._starts = None

    def to(self, t, value, dur=0.5, easing=ease):
        """From `t`, move to `value` over `dur` seconds, from wherever it is."""
        self.moves.append((t, dur, value, easing))
        self._starts = None
        return self

    def set(self, t, value):
        return self.to(t, value, 0.0)

    def _prepare(self):
        self.moves.sort(key=lambda move: move[0])
        self._segments, self._starts = [], []
        for t, dur, value, easing in self.moves:
            start = self._value(t, len(self._segments))
            self._segments.append((t, dur, start, value, easing))
            self._starts.append(t)

    def _value(self, t, count):
        index = bisect.bisect_right(self._starts, t, 0, count) - 1
        if index < 0:
            return self.initial
        t0, dur, start, value, easing = self._segments[index]
        if dur <= 0 or t >= t0 + dur:
            return value
        u = easing((t - t0) / dur)
        if isinstance(value, tuple):
            return tuple(a + (b - a) * u for a, b in zip(start, value))
        return start + (value - start) * u

    def at(self, t):
        if self._starts is None:
            self._prepare()
        return self._value(t, len(self._starts))


# ------------------------------------------------------------------- stage

class Stage:
    """The picture: every thing in the film, and how to draw a moment."""

    def __init__(self, width=W, height=H):
        self.width, self.height = width, height
        self.surface = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
        self.ctx = cairo.Context(self.surface)
        options = cairo.FontOptions()
        options.set_antialias(cairo.ANTIALIAS_GRAY)
        options.set_hint_style(cairo.HINT_STYLE_NONE)
        options.set_hint_metrics(cairo.HINT_METRICS_OFF)
        self.pango = PangoCairo.create_context(self.ctx)
        PangoCairo.context_set_font_options(self.pango, options)
        self.things = []
        self._ordered = None
        self._layouts = {}

    def add(self, thing):
        thing.order = len(self.things)
        self.things.append(thing)
        self._ordered = None

    def layout(self, text, font, markup=False, width=None, align="l",
               spacing=0.0):
        key = (text, font, markup, width, align, spacing)
        made = self._layouts.get(key)
        if made is None:
            made = Pango.Layout.new(self.pango)
            made.set_font_description(Pango.FontDescription.from_string(font))
            if width:
                made.set_width(int(width * Pango.SCALE))
                made.set_alignment({"l": Pango.Alignment.LEFT,
                                    "c": Pango.Alignment.CENTER,
                                    "r": Pango.Alignment.RIGHT}[align])
            if spacing:
                made.set_line_spacing(spacing)
            if markup:
                made.set_markup(text, -1)
            else:
                made.set_text(text, -1)
            if len(self._layouts) > 20000:
                self._layouts.clear()
            self._layouts[key] = made
        return made

    def measure(self, text, font, markup=False):
        """The width and height a line of text takes."""
        _, logical = self.layout(text, font, markup).get_pixel_extents()
        return logical.width, logical.height

    def paint(self, t):
        """Draw the frame of time `t` on the stage's surface."""
        if self._ordered is None:
            self._ordered = sorted(self.things, key=lambda th: (th.z, th.order))
        ctx = self.ctx
        ctx.identity_matrix()
        ctx.set_source_rgb(*PAPER[:3])
        ctx.paint()
        for thing in self._ordered:
            alpha = thing.alpha(t)
            if alpha <= 0.004:
                continue
            ctx.save()
            if thing.parent is not None:
                thing.parent.apply(ctx, t)
            thing.paint(ctx, t, alpha)
            ctx.restore()
        self.surface.flush()
        return self.surface


class Group:
    """A frame of reference: what is in it moves, scales and fades together."""

    def __init__(self, x=0.0, y=0.0, scale=1.0, parent=None):
        self.x, self.y, self.scale = Track(x), Track(y), Track(scale)
        self.opacity = Track(1.0)
        self.parent = parent

    def apply(self, ctx, t):
        if self.parent is not None:
            self.parent.apply(ctx, t)
        ctx.translate(self.x.at(t), self.y.at(t))
        scale = self.scale.at(t)
        ctx.scale(scale, scale)


class Thing:
    """Anything drawn. Unseen until shown."""

    def __init__(self, stage, parent=None, z=0):
        self.stage, self.parent, self.z = stage, parent, z
        self.opacity = Track(0.0)
        stage.add(self)

    def show(self, t, dur=0.5, to=1.0):
        self.opacity.to(t, to, dur, ease_out)
        return self

    def hide(self, t, dur=0.5):
        self.opacity.to(t, 0.0, dur)
        return self

    def alpha(self, t):
        alpha = self.opacity.at(t)
        parent = self.parent
        while parent is not None and alpha > 0:
            alpha *= parent.opacity.at(t)
            parent = parent.parent
        return alpha

    def paint(self, ctx, t, alpha):
        raise NotImplementedError


# ------------------------------------------------------------------ shapes

def rounded(ctx, x, y, w, h, r):
    """The path of a rectangle with round corners, top left at (x, y)."""
    r = min(r, w / 2, h / 2)
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    ctx.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    ctx.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    ctx.close_path()


def source(ctx, color, alpha=1.0):
    ctx.set_source_rgba(color[0], color[1], color[2], color[3] * alpha)


def write(stage, ctx, text, font, x, y, color, alpha=1.0, anchor="l",
          scale=1.0, markup=False, middle=True, width=None, align="l",
          spacing=0.0):
    """Set a line of type. `anchor` is the side `x` names (l, c or r); with
    `middle` the capitals are centred on `y`, otherwise `y` is the top."""
    layout = stage.layout(text, font, markup, width, align, spacing)
    PangoCairo.update_layout(ctx, layout)
    _, logical = layout.get_pixel_extents()
    size = layout.get_font_description().get_size() / Pango.SCALE
    left = {"l": 0.0, "c": -logical.width / 2, "r": -logical.width}[anchor]
    if width:
        left = {"l": 0.0, "c": -width / 2, "r": -width}[anchor]
    top = 0.36 * size - layout.get_baseline() / Pango.SCALE if middle else 0.0
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(scale, scale)
    ctx.move_to(left, top)
    if markup and alpha < 0.999:
        ctx.push_group()
        source(ctx, color)
        PangoCairo.show_layout(ctx, layout)
        ctx.pop_group_to_source()
        ctx.paint_with_alpha(alpha)
    else:
        source(ctx, color, alpha)
        PangoCairo.show_layout(ctx, layout)
    ctx.restore()
    return logical.width * scale


class Node(Thing):
    """A named thing in the graph: a pill with its name in it."""

    def __init__(self, stage, label, x, y, parent=None, z=10, size=30,
                 weight="Medium", pad=30, height=64, width=None, family=SANS,
                 radius=None):
        super().__init__(stage, parent, z)
        self.label = label
        self.font = f"{family} {weight} {size}px"
        self.x, self.y, self.scale = Track(x), Track(y), Track(1.0)
        self.fill, self.line, self.ink = Track(WHITE), Track(SLATE), Track(INK)
        self.line_width = Track(2.25)
        self.label_opacity = Track(1.0)
        self.ring = Track(1.0)          # 0..1: a ring leaving the node
        self.ring_color = SLATE
        self.h = height
        self.w = width or max(stage.measure(label, self.font)[0] + 2 * pad,
                              height)
        self.radius = height / 2 if radius is None else radius

    def box(self, t):
        scale = self.scale.at(t)
        return self.x.at(t), self.y.at(t), self.w * scale, self.h * scale

    def appear(self, t, dur=0.5):
        self.opacity.to(t, 1.0, dur * 0.8, ease_out)
        self.scale.set(t, 0.88)
        self.scale.to(t, 1.0, dur, ease_out)
        return self

    def color(self, t, color=None, dur=0.4, fill=0.11):
        """Outline and tint in a colour; with none, back to plain."""
        self.line.to(t, color or SLATE, dur)
        self.fill.to(t, tint(color, fill) if color else WHITE, dur)
        return self

    def ping(self, t, color=SLATE, dur=0.9):
        """A ring that widens from the node and fades: look here."""
        self.ring_color = color
        self.ring.set(t, 0.0)
        self.ring.to(t, 1.0, dur, ease_out)
        return self

    def move(self, t, x=None, y=None, dur=0.8, easing=ease):
        if x is not None:
            self.x.to(t, x, dur, easing)
        if y is not None:
            self.y.to(t, y, dur, easing)
        return self

    def paint(self, ctx, t, alpha):
        x, y, w, h = self.box(t)
        scale = self.scale.at(t)
        ring = self.ring.at(t)
        if 0.0 < ring < 1.0:
            grow = 4 + 18 * ring
            rounded(ctx, x - w / 2 - grow, y - h / 2 - grow, w + 2 * grow,
                    h + 2 * grow, self.radius * scale + grow)
            source(ctx, self.ring_color, alpha * 0.6 * (1 - ring))
            ctx.set_line_width(3.0)
            ctx.stroke()
        rounded(ctx, x - w / 2, y - h / 2, w, h, self.radius * scale)
        source(ctx, self.fill.at(t), alpha)
        ctx.fill_preserve()
        source(ctx, self.line.at(t), alpha)
        ctx.set_line_width(self.line_width.at(t) * scale)
        ctx.stroke()
        shown = self.label_opacity.at(t)
        if self.label and shown > 0.004:
            write(self.stage, ctx, self.label, self.font, x, y,
                  self.ink.at(t), alpha * shown, "c", scale)


def _anchor(node, t, side, shift, gap, other=None):
    x, y, w, h = node.box(t)
    if side == "toward":            # a round node: the point facing the other
        ox, oy = other.box(t)[:2]
        reach = math.hypot(ox - x, oy - y) or 1.0
        return (x + (ox - x) / reach * (h / 2 + gap),
                y + (oy - y) / reach * (h / 2 + gap))
    if side == "top":
        return x + shift, y - h / 2 - gap
    if side == "bottom":
        return x + shift, y + h / 2 + gap
    if side == "left":
        return x - w / 2 - gap, y + shift
    return x + w / 2 + gap, y + shift


class Edge(Thing):
    """An arrow from one node to another, straight or bent, drawn on."""

    def __init__(self, stage, a, b, parent=None, z=5, bend=0.0,
                 out=("bottom", 0.0), into=("top", 0.0), dashed=False, gap=6,
                 head=17.0):
        super().__init__(stage, parent, z)
        self.a, self.b, self.bend = a, b, bend
        self.out, self.into, self.dashed, self.gap = out, into, dashed, gap
        self.head = head
        self.progress = Track(0.0)
        self.line = Track(SLATE)
        self.width = Track(2.25)

    def draw(self, t, dur=0.55):
        self.opacity.to(t, 1.0, 0.12, ease_out)
        self.progress.set(t, 0.0)
        self.progress.to(t, 1.0, dur, ease)
        return self

    def color(self, t, color=None, dur=0.4, width=None):
        self.line.to(t, color or SLATE, dur)
        self.width.to(t, width or (3.0 if color else 2.25), dur)
        return self

    def paint(self, ctx, t, alpha):
        amount = self.progress.at(t)
        if amount <= 0.001:
            return
        x0, y0 = _anchor(self.a, t, *self.out, self.gap, self.b)
        x3, y3 = _anchor(self.b, t, *self.into, self.gap, self.a)
        length = math.hypot(x3 - x0, y3 - y0) or 1.0
        # a curve through one control point, set off sideways by the bend
        cx = (x0 + x3) / 2 - (y3 - y0) * self.bend
        cy = (y0 + y3) / 2 + (x3 - x0) * self.bend

        def point(u):
            return ((1 - u) ** 2 * x0 + 2 * u * (1 - u) * cx + u * u * x3,
                    (1 - u) ** 2 * y0 + 2 * u * (1 - u) * cy + u * u * y3)

        tip = point(amount)
        before = point(max(0.0, amount - 0.02))
        angle = math.atan2(tip[1] - before[1], tip[0] - before[0])
        head = self.head * min(1.0, amount * length / (self.head * 2.5))
        stop = max(0.0, amount - 0.8 * head / length)
        width = self.width.at(t)
        source(ctx, self.line.at(t), alpha)
        ctx.set_line_width(width)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        if self.dashed:
            ctx.set_dash([9, 8])
        ctx.move_to(x0, y0)
        steps = max(2, int(length * stop / 12))
        for step in range(1, steps + 1):
            ctx.line_to(*point(stop * step / steps))
        ctx.stroke()
        ctx.set_dash([])
        spread = 0.42 + 0.04 * (width - 2.25)
        ctx.move_to(*tip)
        ctx.line_to(tip[0] - head * math.cos(angle - spread),
                    tip[1] - head * math.sin(angle - spread))
        ctx.line_to(tip[0] - head * 0.72 * math.cos(angle),
                    tip[1] - head * 0.72 * math.sin(angle))
        ctx.line_to(tip[0] - head * math.cos(angle + spread),
                    tip[1] - head * math.sin(angle + spread))
        ctx.close_path()
        ctx.fill()


class Text(Thing):
    """A line of type (or a paragraph, given a width)."""

    def __init__(self, stage, text, x, y, size=30, weight="", color=INK,
                 anchor="l", parent=None, z=20, family=SANS, markup=False,
                 width=None, align="l", spacing=0.0, middle=True):
        super().__init__(stage, parent, z)
        self.text, self.anchor, self.markup = text, anchor, markup
        self.font = " ".join(part for part in (family, weight, f"{size}px")
                             if part)
        self.width, self.align, self.spacing = width, align, spacing
        self.middle = middle
        self.x, self.y, self.scale = Track(x), Track(y), Track(1.0)
        self.color = Track(color)
        self.reveal = Track(1.0)

    def type(self, t, rate=30.0):
        """Appear a letter at a time, as typed."""
        self.opacity.set(t, 1.0)
        self.reveal.set(t, 0.0)
        self.reveal.to(t, 1.0, len(self.text) / rate, linear)
        return t + len(self.text) / rate

    def rise(self, t, dur=0.6, by=14):
        """Fade in while coming up a little."""
        self.opacity.to(t, 1.0, dur, ease_out)
        self.y.set(t, self.y.at(t) + by)
        self.y.to(t, self.y.at(t) - by, dur, ease_out)
        return self

    def extent(self):
        return self.stage.measure(self.text, self.font, self.markup)

    def paint(self, ctx, t, alpha):
        text = self.text
        shown = self.reveal.at(t)
        if shown < 1.0:
            text = text[:int(len(text) * shown + 0.5)]
            if not text:
                return
        write(self.stage, ctx, text, self.font, self.x.at(t), self.y.at(t),
              self.color.at(t), alpha, self.anchor, self.scale.at(t),
              self.markup, self.middle, self.width, self.align, self.spacing)


class Custom(Thing):
    """Anything else: a function that draws, with tracks of its own."""

    def __init__(self, stage, draw, parent=None, z=0, **tracks):
        super().__init__(stage, parent, z)
        self.draw = draw
        for name, value in tracks.items():
            setattr(self, name, Track(value))

    def paint(self, ctx, t, alpha):
        self.draw(ctx, t, alpha, self)


def hull(points):
    """The convex hull of some points, in order round it."""
    points = sorted(set(points))
    if len(points) < 3:
        return points

    def half(sequence):
        chain = []
        for p in sequence:
            while len(chain) >= 2 and (
                    (chain[-1][0] - chain[-2][0]) * (p[1] - chain[-2][1])
                    - (chain[-1][1] - chain[-2][1]) * (p[0] - chain[-2][0])
            ) <= 0:
                chain.pop()
            chain.append(p)
        return chain[:-1]

    return half(points) + half(reversed(points))


class Region(Thing):
    """A soft shape round some nodes: a cone, an answer."""

    def __init__(self, stage, nodes, color, parent=None, z=1, pad=26,
                 strength=0.16):
        super().__init__(stage, parent, z)
        self.nodes, self.pad = nodes, pad
        self.color = Track(color)
        self.strength = Track(strength)
        self.grow = Track(1.0)          # 0..1: how far down it has come

    def pour(self, t, dur=0.9):
        """Come down from its top node, as a cone falls from its category."""
        self.opacity.to(t, 1.0, 0.15)
        self.grow.set(t, 0.0)
        self.grow.to(t, 1.0, dur, ease)
        return self

    def paint(self, ctx, t, alpha):
        corners = []
        for node in self.nodes:
            x, y, w, h = node.box(t)
            inset = min(w, h) / 2
            for dx in (-(w / 2 - inset), w / 2 - inset):
                for dy in (-h / 2 + inset, h / 2 - inset):
                    corners.append((round(x + dx, 2), round(y + dy, 2)))
        outline = hull(corners)
        if not outline:
            return
        reach = self.pad + min(self.nodes[0].box(t)[2:]) / 2
        top = min(y for _, y in outline) - reach
        bottom = max(y for _, y in outline) + reach
        grown = self.grow.at(t)
        ctx.save()
        if grown < 1.0:
            ctx.rectangle(-10000, top, 20000, (bottom - top) * grown)
            ctx.clip()
        ctx.push_group()
        color = self.color.at(t)
        ctx.set_source_rgb(*color[:3])
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_width(2 * reach)
        ctx.move_to(*outline[0])
        for corner in outline[1:]:
            ctx.line_to(*corner)
        ctx.close_path()
        ctx.fill_preserve()
        ctx.stroke()
        ctx.pop_group_to_source()
        ctx.paint_with_alpha(self.strength.at(t) * alpha)
        ctx.restore()
