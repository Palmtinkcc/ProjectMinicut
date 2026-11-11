"""Finds the effect folders and gives their GPU builders to the engine.

A folder  fx/<effect id>/  with an effect.py that defines  ID  and  build(p, c, w, h, opaque)  is an effect: build() returns the GPU passes
(Built) or None when this parameter combination is left to the CPU. One broken effect never stops the others: it is skipped and
written to the crash log, and its CPU version keeps working.
"""
import importlib, os, sys, traceback

_DONE = False
FAILED = {}          # effect id -> error text, for the tests and for the log


def effect_dirs():
    root = os.path.dirname(os.path.abspath(__file__))
    return sorted(d for d in os.listdir(root) if os.path.isfile(os.path.join(root, d, "effect.py")))


def load_all(table):
    """Put every folder effect into `table` (glfx_lib.GL_FX). Runs once."""
    global _DONE
    if _DONE: return
    _DONE = True
    for d in effect_dirs():
        try:
            m = importlib.import_module("%s.%s.effect" % (__package__, d))
            table[m.ID] = m.build
        except Exception:
            FAILED[d] = traceback.format_exc()
            try: sys.stderr.write("effect %s skipped (the CPU version is used):\n%s\n" % (d, FAILED[d]))
            except Exception: pass
