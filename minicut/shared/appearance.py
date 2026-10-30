"""Apply the appearance settings to the running application."""
from .deps import *
from .theme import *
from .core import *


def apply_ui(win):
    """Apply UI[...] to the running app (stylesheet, icon size, timeline / viewport)."""
    for k in CLIP_COLORS: CLIP_COLORS[k] = UI.get("clip_" + k, CLIP_COLORS[k])
    qa = QApplication.instance()
    if qa: qa.setStyleSheet(build_qss(QSS))
    n = int(UI["icon_size"])
    for b in win.findChildren(QToolButton):
        if b.property("iconDefault"): b.setIconSize(QSize(n, n))
    tl = getattr(win, "timeline", None)
    if tl is not None and getattr(win, "proj", None): tl.update_scroll(); tl.update()
    vp = getattr(win, "viewport", None)
    if vp is not None: vp.update()
