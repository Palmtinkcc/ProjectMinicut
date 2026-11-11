"""The effect pack: about 150 more effects in the groups Color, Opacity, Glitch, VHS, Background, Repeat, Particle, 3D object,
Wipes & shatter, Shake & transform, Strokes & shadows, Distortion & warp, Procedural, Move, Blur, Lens, Water & glass, Ink & paint.
Every module registers its effects when it is imported; a module that fails never stops the others (or the program)."""
import importlib, traceback

for _m in ("color", "glitch", "vhs", "background", "repeat", "particle", "wipes", "strokes", "warp", "motion"):
    try: importlib.import_module("." + _m, __name__)
    except Exception:
        print("[effects] pack module", _m, "could not be loaded"); traceback.print_exc()
