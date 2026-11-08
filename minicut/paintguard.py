"""Paint guard (Patch 38). An exception inside a paintEvent keeps the QPainter alive (the traceback holds the frame), and Qt then prints
"QBackingStore::endPaint() called with active painter". This wraps every paintEvent of MiniCut's widgets: the error is written once per
place to minicut_paint_errors.txt (with the full traceback, so the real bug can be fixed) and the painter is released at once."""
import sys, os, traceback, inspect, functools
LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "minicut_paint_errors.txt")
_seen = set()


def _wrap(cls, fn):
    @functools.wraps(fn)
    def paintEvent(self, e):
        try:
            return fn(self, e)
        except Exception:
            tb = traceback.format_exc()
            key = tb.strip().splitlines()[-3:] and "".join(tb.strip().splitlines()[-3:])
            if key not in _seen:
                _seen.add(key)
                try:
                    with open(LOG, "a", encoding="utf-8") as f: f.write("--- %s.%s\n%s\n" % (cls.__module__, cls.__name__, tb))
                except Exception: pass
            del tb
    paintEvent._pg = True
    return paintEvent


def install():
    from PySide6.QtWidgets import QWidget
    n = 0
    for mn, mod in list(sys.modules.items()):
        if not mn.startswith("minicut") or mod is None: continue
        for cls in list(vars(mod).values()):
            if inspect.isclass(cls) and cls.__module__ == mn and issubclass(cls, QWidget):
                fn = cls.__dict__.get("paintEvent")
                if fn is not None and not getattr(fn, "_pg", False):
                    try: cls.paintEvent = _wrap(cls, fn); n += 1
                    except Exception: pass
    return n
