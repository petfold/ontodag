"""Stills side by side on one sheet, to look a scene over at a glance.

    python3 sheet.py out/sheet.png 61.2 66 70.5 ...
"""
import sys

import cairo

import anim
import scenes


def main(path, times, columns=2, size=0.5):
    if len(times) > 12:                 # many: a small grid, to see the pace
        columns, size = 4, 0.25
    stage = scenes.build()
    w, h = int(anim.W * size), int(anim.H * size)
    rows = (len(times) + columns - 1) // columns
    sheet = cairo.ImageSurface(cairo.FORMAT_RGB24, columns * (w + 6) - 6,
                               rows * (h + 6) - 6)
    ctx = cairo.Context(sheet)
    ctx.set_source_rgb(0.25, 0.25, 0.25)
    ctx.paint()
    for k, t in enumerate(times):
        frame = stage.paint(t)
        ctx.save()
        ctx.translate(k % columns * (w + 6), k // columns * (h + 6))
        ctx.scale(size, size)
        ctx.set_source_surface(frame)
        ctx.get_source().set_filter(cairo.FILTER_BEST)
        ctx.paint()
        ctx.restore()
        ctx.set_source_rgb(0.75, 0.2, 0.2)
        ctx.select_font_face("monospace")
        ctx.set_font_size(15)
        ctx.move_to(k % columns * (w + 6) + w - 70, k // columns * (h + 6) + 20)
        ctx.show_text("%.2f" % t)
    sheet.write_to_png(path)


if __name__ == "__main__":
    main(sys.argv[1], [float(t) for t in sys.argv[2:]])
