"""The effect pack. Since Patch 36 every effect is a folder in minicut/fx/ (see fx/README.md); this package only starts the loader so that the
effects are registered when render/effects.py has finished (the name stays: effects.py imports it).
A folder that fails never stops the others (or the program)."""
import traceback

try:
    from ...fx import loader
    loader.load_all()
    from ..effects import FX
    loader.reorder(FX)
except Exception:
    print("[effects] the effect folders could not be loaded"); traceback.print_exc()
