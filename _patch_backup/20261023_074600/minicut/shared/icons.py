"""SVG icons: loads the files in the svg/ folder, tints them and returns QIcon / QPixmap."""
from .deps import *
from .deps import __file__


try:
    from PySide6.QtSvg import QSvgRenderer
    HAS_SVG = True
except Exception:
    HAS_SVG = False
    print("[icons] PySide6.QtSvg not found -> icons will be blank. Try: pip install --upgrade PySide6")


def _find_svg_dir():
    """The svg/ folder sits next to file.py (the project root); search upwards from this file, then the working dir."""
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        if os.path.isdir(os.path.join(here, "svg")): return os.path.join(here, "svg")
        here = os.path.dirname(here)
    return os.path.join(os.getcwd(), "svg")


SVG_DIR = _find_svg_dir()


ICON_ALIASES = {
    "undo": ("undo", "rotate-left"), "redo": ("redo", "rotate-right"),
    "split": ("scissors",), "cut": ("scissors",), "duplicate": ("copy-alt", "copy"), "delete": ("trash",),
    "play": ("play",), "pause": ("pause",), "previous": ("step-backward", "rewind"), "next": ("step-forward", "forward"),
    "folder": ("folder",), "folder_open": ("folder-open", "folder"), "refresh": ("refresh", "rotate-right"),
    "import": ("plus", "add"), "plus": ("plus",), "minus": ("minus",), "text": ("text", "letter-case"),
    "keyframe": ("diamond",), "zoom_fit": ("expand",), "zoom_in": ("zoom-in",), "zoom_out": ("zoom-out",),
    "save": ("disk",), "export": ("upload", "file-export"), "settings": ("settings",),
    "video": ("film", "video-camera"), "image": ("picture",), "audio": ("music-alt", "music"),
    "gif": ("gif", "picture"), "search": ("search",), "close": ("cross", "cross-small"),
    "add_audio": ("music-alt",), "magnet": ("magnet",), "group": ("object-group", "layers"),
    "compound": ("layers", "copy"), "extract": ("waveform-path", "music-alt"), "replace": ("refresh",),
    "trim_left": ("arrow-to-left", "angle-double-left"), "trim_right": ("arrow-to-right", "angle-double-right"),
    "mask": ("circle",), "home": ("home",), "check": ("check",), "keyboard": ("keyboard",),
    "angle_left": ("angle-left",), "angle_right": ("angle-right",), "nodes": ("circle-nodes", "workflow", "sitemap"), "project": ("film", "clapperboard-play"),
}


_SVG_WARNED = set()


_ICON_CACHE = {}


def _svg_path(name):
    for n in ICON_ALIASES.get(name, (name,)):
        for fn in ("fi-br-%s.svg" % n, "%s.svg" % n):
            p = os.path.join(SVG_DIR, fn)
            if os.path.isfile(p): return p
    return None


def svg_pixmap(name, color="#ffffff", size=24):
    """Render svg/<name>.svg as a square pixmap tinted with `color`."""
    pm = QPixmap(size, size); pm.fill(Qt.transparent)
    path = _svg_path(name) if HAS_SVG else None
    if not path:
        if name not in _SVG_WARNED:
            _SVG_WARNED.add(name); print("[icons] missing svg for '%s' (looked in %s)" % (name, SVG_DIR))
        return pm
    r = QSvgRenderer(path)
    if not r.isValid(): return pm
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.SmoothPixmapTransform)
    r.render(p, QRectF(0, 0, size, size))
    p.setCompositionMode(QPainter.CompositionMode_SourceIn); p.fillRect(pm.rect(), QColor(color)); p.end()
    return pm


def svg_icon(name, color="#ffffff", on="#22d3ee", off="#5d6476"):
    """QIcon from svg/: normal=color, checked(On)=cyan, disabled=grey."""
    key = (name, color, on, off)
    if key in _ICON_CACHE: return _ICON_CACHE[key]
    ic = QIcon()
    for px in (16, 20, 24, 32, 48, 64):
        ic.addPixmap(svg_pixmap(name, color, px), QIcon.Normal, QIcon.Off)
        ic.addPixmap(svg_pixmap(name, on, px), QIcon.Normal, QIcon.On)
        ic.addPixmap(svg_pixmap(name, off, px), QIcon.Disabled, QIcon.Off)
    _ICON_CACHE[key] = ic
    return ic


def svg_combo_icon(names, color="#ffffff"):
    """Several svg icons side by side in one QIcon (e.g. previous/next keyframe)."""
    key = ("combo", tuple(names), color)
    if key in _ICON_CACHE: return _ICON_CACHE[key]
    ic = QIcon()
    for s in (16, 20, 24, 32, 48):
        step = int(s * 0.8); w = step * (len(names) - 1) + s
        for mode, col in ((QIcon.Normal, color), (QIcon.Disabled, "#5d6476")):
            pm = QPixmap(w, s); pm.fill(Qt.transparent); p = QPainter(pm)
            for i, n in enumerate(names): p.drawPixmap(i * step, 0, svg_pixmap(n, col, s))
            p.end(); ic.addPixmap(pm, mode, QIcon.Off)
    _ICON_CACHE[key] = ic
    return ic


def app_icon(name):
    """Icon used everywhere in the app."""
    return svg_icon(name)


def set_play_icon(btn, playing):
    btn.setText(""); btn.setIcon(app_icon("pause" if playing else "play"))
