"""pixelsort: Pixel sort. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_glitch import *

def fx_pixelsort(img, p, ctx):
    return _sort(img, p["low"] / 100.0, p["high"] / 100.0, p["key"], p["reverse"], p["direction"] == "vertical")

reg("pixelsort", G, "Pixel sort", [F("low", "Sort from (brightness)", 20, 0, 100), F("high", "Sort up to", 85, 0, 100), CH("key", "Sort by", "lum", [("lum", "Brightness"), ("hue", "Hue"), ("red", "Red")]),
                                    CH("direction", "Direction", "vertical", [("horizontal", "Horizontal"), ("vertical", "Vertical")]), B("reverse", "Reverse", False)], fx_pixelsort, "Sorts the pixels of each row or column by brightness, a classic glitch-art look.", "sort glitch art")

ID = "pixelsort"
