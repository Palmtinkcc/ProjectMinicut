"""Finds the effect folders and loads them.

A folder  fx/<effect id>/  with an effect.py is an effect. Importing effect.py registers the CPU effect (the register / reg call in the file)
and, when the file defines  build(p, c, w, h, opaque), the GPU version: build() returns the GPU passes (Built) or None when this
parameter combination is left to the CPU. One broken effect never stops the others: it is skipped and written to the log.

order.txt lists the effect ids in the order the effects panel shows them (the folders are loaded alphabetically, so the order is put right
afterwards by reorder()). An effect that is not in order.txt goes to the end.
"""
import importlib, os, sys, traceback

_DONE = False
BUILDERS = {}        # effect id -> GPU builder
FAILED = {}          # effect folder -> error text, for the tests and for the log


def effect_dirs():
    root = os.path.dirname(os.path.abspath(__file__))
    return sorted(d for d in os.listdir(root) if os.path.isfile(os.path.join(root, d, "effect.py")))


def load_all(table=None):
    """Import every effect folder once (this registers the CPU effects). `table` (glfx_lib.GL_FX) gets the GPU builders."""
    global _DONE
    if not _DONE:
        _DONE = True
        for d in effect_dirs():
            try:
                m = importlib.import_module("%s.%s.effect" % (__package__, d))
                if hasattr(m, "build"): BUILDERS[getattr(m, "ID", d)] = m.build
            except Exception:
                FAILED[d] = traceback.format_exc()
                try: sys.stderr.write("[effects] %s could not be loaded:\n%s\n" % (d, FAILED[d]))
                except Exception: pass
    if table is not None: table.update(BUILDERS)


def order_ids():
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "order.txt"), encoding="utf-8") as f:
            return [l.strip() for l in f if l.strip()]
    except OSError:
        return []


def reorder(FX):
    """Put the registry in the order of order.txt (what the effects panel shows)."""
    ids = order_ids(); items = {k: FX[k] for k in ids if k in FX}
    for k, v in FX.items():
        if k not in items: items[k] = v
    FX.clear(); FX.update(items)
