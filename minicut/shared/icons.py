"""Icons: Google "Material Icons" (outlined) as an icon FONT, installed once in the fonts/ folder next to file.py.

Everything in the program asks for icons by name (app_icon("play")). The name is turned into a glyph of the font and
drawn in the colour that is asked for, so one font file gives every size and every colour, and nothing has to be
exported as an image. If the font file is missing the program downloads it once (the update patch already copies it
there). If that is not possible either, the old svg/ folder is used so the program never starts without icons.
Browse the icons at https://fonts.google.com/icons - the name shown there (e.g. "content_cut") can be used directly."""
from .deps import *
from .deps import __file__
import urllib.request


FONT_FILE = "MaterialIconsOutlined-Regular.otf"
FONT_URLS = [
    "https://raw.githubusercontent.com/google/material-design-icons/master/font/" + FONT_FILE,
    "https://cdn.jsdelivr.net/gh/google/material-design-icons@master/font/" + FONT_FILE,
    "https://github.com/google/material-design-icons/raw/master/font/" + FONT_FILE,
]
FONT_MIN_BYTES = 150_000


try:
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtSvg import QSvgRenderer
    HAS_SVG = True
except Exception:
    HAS_SVG = False


def _project_root():
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        if os.path.isfile(os.path.join(here, "file.py")): return here
        here = os.path.dirname(here)
    return os.getcwd()


FONT_DIR = os.path.join(_project_root(), "fonts")
FONT_PATH = os.path.join(FONT_DIR, FONT_FILE)


# ---- name -> glyph (code point in the font) of every icon the program uses ----
GLYPHS = {
    'account_tree': 0xe97a,
    'add': 0xe145,
    'flag': 0xe153,
    'bookmark': 0xe866,
    'add_circle': 0xe147,
    'align_horizontal_center': 0xe00f,
    'animation': 0xe71c,
    'aspect_ratio': 0xe85b,
    'audiotrack': 0xe3a1,
    'auto_awesome_motion': 0xe661,
    'auto_fix_high': 0xe663,
    'auto_fix_normal': 0xe664,
    'blur_on': 0xe3a5,
    'bolt': 0xea0b,
    'brightness_6': 0xe3ab,
    'call_split': 0xe0b6,
    'cancel': 0xe5c9,
    'center_focus_strong': 0xe3b4,
    'change_history': 0xe86b,
    'check': 0xe5ca,
    'check_circle': 0xe86c,
    'chevron_left': 0xe5cb,
    'chevron_right': 0xe5cc,
    'circle': 0xef4a,
    'close': 0xe5cd,
    'close_fullscreen': 0xf1cf,
    'content_copy': 0xf08a,
    'content_cut': 0xf08b,
    'content_paste': 0xf098,
    'contrast': 0xeb37,
    'crop_16_9': 0xe3bc,
    'crop_free': 0xe3c2,
    'crop_square': 0xe3c6,
    'delete': 0xe872,
    'delete_sweep': 0xe16c,
    'diamond': 0xead5,
    'done': 0xe876,
    'download_done': 0xf091,
    'downloading': 0xf001,
    'drag_indicator': 0xe945,
    'expand_less': 0xe5ce,
    'expand_more': 0xe5cf,
    'fast_forward': 0xe01f,
    'fiber_manual_record': 0xe061,
    'file_download': 0xe2c4,
    'filter_center_focus': 0xe3dc,
    'find_replace': 0xe881,
    'first_page': 0xe5dc,
    'fit_screen': 0xea10,
    'flip': 0xe3e8,
    'flip_camera_android': 0xea37,
    'folder': 0xe2c7,
    'folder_open': 0xe2c8,
    'folder_special': 0xe617,
    'format_bold': 0xe238,
    'format_color_fill': 0xe23a,
    'fullscreen': 0xe5d0,
    'fullscreen_exit': 0xe5d1,
    'gif': 0xe908,
    'gradient': 0xe3e9,
    'graphic_eq': 0xe1b8,
    'help_outline': 0xe8fd,
    'home': 0xe88a,
    'horizontal_rule': 0xf108,
    'hourglass_empty': 0xe88b,
    'hub': 0xe9f4,
    'image': 0xe3f4,
    'info': 0xe88e,
    'ios_share': 0xe6b8,
    'keyboard': 0xe312,
    'keyboard_arrow_down': 0xe313,
    'keyboard_arrow_left': 0xe314,
    'keyboard_arrow_right': 0xe315,
    'keyboard_arrow_up': 0xe316,
    'last_page': 0xe5dd,
    'layers': 0xe53b,
    'library_add': 0xe02e,
    'library_music': 0xe030,
    'link': 0xe157,
    'link_off': 0xe16f,
    'lock': 0xe897,
    'lock_open': 0xe898,
    'mic': 0xe029,
    'more_horiz': 0xeae1,
    'more_vert': 0xe5d4,
    'movie': 0xe02c,
    'music_note': 0xe405,
    'music_video': 0xe063,
    'opacity': 0xe91c,
    'open_in_full': 0xf1ce,
    'open_with': 0xe89f,
    'pan_tool': 0xe925,
    'panorama_fish_eye': 0xe40c,
    'pause': 0xe034,
    'photo_library': 0xe413,
    'play_arrow': 0xe037,
    'play_circle': 0xe1c4,
    'queue': 0xe03c,
    'redo': 0xe15a,
    'refresh': 0xe5d5,
    'remove': 0xe15b,
    'restart_alt': 0xf053,
    'rotate_right': 0xe41a,
    'save': 0xe161,
    'schedule': 0xe8b5,
    'search': 0xe8b6,
    'select_all': 0xe162,
    'settings': 0xe8b8,
    'skip_next': 0xe044,
    'skip_previous': 0xe045,
    'speed': 0xe9e4,
    'splitscreen': 0xf06d,
    'stop': 0xe047,
    'stop_circle': 0xef71,
    'subtitles': 0xe048,
    'swap_vert': 0xe8d5,
    'task_alt': 0xe2e6,
    'text_fields': 0xe262,
    'timeline': 0xe922,
    'title': 0xe264,
    'tune': 0xe429,
    'undo': 0xe166,
    'vertical_align_center': 0xe259,
    'vertical_split': 0xe949,
    'videocam': 0xe04b,
    'vignette': 0xe435,
    'visibility': 0xe8f4,
    'visibility_off': 0xe8f5,
    'volume_off': 0xe04f,
    'volume_up': 0xe050,
    'workspaces': 0xe1a0,
    'zoom_in': 0xe8ff,
    'zoom_out': 0xe900,
    'zoom_out_map': 0xe56b,
}


# the program's own short names -> the Material name (anything else is looked up as a Material name directly)
ICON_ALIASES = {
    "undo": "undo", "redo": "redo", "split": "content_cut", "cut": "content_cut", "duplicate": "content_copy", "copy": "content_copy",
    "paste": "content_paste", "delete": "delete", "play": "play_arrow", "pause": "pause", "previous": "skip_previous", "next": "skip_next",
    "folder": "folder", "folder_open": "folder_open", "refresh": "refresh", "import": "library_add", "plus": "add", "minus": "remove",
    "text": "title", "keyframe": "diamond", "zoom_fit": "fit_screen", "zoom_in": "zoom_in", "zoom_out": "zoom_out", "save": "save",
    "export": "file_download", "settings": "settings", "video": "movie", "image": "image", "audio": "music_note", "gif": "gif",
    "search": "search", "close": "close", "add_audio": "library_music", "magnet": "align_horizontal_center", "snap": "align_horizontal_center",
    "group": "workspaces", "ungroup": "link_off", "compound": "auto_awesome_motion", "extract": "graphic_eq", "replace": "find_replace",
    "trim_left": "first_page", "trim_right": "last_page", "mask": "vignette", "home": "home", "check": "check", "keyboard": "keyboard",
    "angle_left": "chevron_left", "angle_right": "chevron_right", "angle-up": "expand_less", "angle-down": "expand_more",
    "nodes": "hub", "project": "movie", "hide": "visibility_off", "show": "visibility", "mute": "volume_off", "sound": "volume_up",
    "lock": "lock", "unlock": "lock_open", "record": "fiber_manual_record", "stop": "stop", "effects": "auto_fix_high", "adjust": "tune",
    "move": "open_with", "scale": "zoom_out_map", "rotate": "rotate_right", "opacity": "opacity", "flip": "flip", "reset": "restart_alt",
    "fit": "crop_free", "fill": "aspect_ratio", "center": "filter_center_focus", "cancel": "cancel", "done": "task_alt",
    "tasks": "downloading", "link": "link", "unlink": "link_off", "more": "more_horiz", "keys": "animation", "volume": "volume_up",
    "up": "keyboard_arrow_up", "down": "keyboard_arrow_down", "left": "keyboard_arrow_left", "right": "keyboard_arrow_right",
    "info": "info", "help": "help_outline", "expand": "open_in_full", "collapse": "close_fullscreen", "wait": "hourglass_empty",
    "track_add": "add_circle", "all": "select_all", "inspector": "tune", "timeline": "view_timeline" if False else "timeline",
}

_ICON_CACHE = {}
_STATE = {"family": None, "tried": False}
_SVG_WARNED = set()


def _download_font():
    """One-time download of the icon font into fonts/. Returns True when the file is there afterwards."""
    os.makedirs(FONT_DIR, exist_ok=True)
    for url in FONT_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "MiniCut"})
            with urllib.request.urlopen(req, timeout=20) as r: data = r.read()
            if len(data) >= FONT_MIN_BYTES:
                with open(FONT_PATH + ".part", "wb") as f: f.write(data)
                os.replace(FONT_PATH + ".part", FONT_PATH); return True
        except Exception as ex: print("[icons] download failed (%s): %s" % (url, ex))
    return False


def icon_family():
    """Name of the loaded icon font (None when it could not be loaded). Loads / downloads it on the first call."""
    if _STATE["tried"]: return _STATE["family"]
    _STATE["tried"] = True
    try:
        if not (os.path.isfile(FONT_PATH) and os.path.getsize(FONT_PATH) >= FONT_MIN_BYTES): _download_font()
        if os.path.isfile(FONT_PATH):
            fid = QFontDatabase.addApplicationFont(FONT_PATH)
            fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
            if fams: _STATE["family"] = fams[0]
    except Exception as ex: print("[icons] could not load the icon font:", ex)
    if _STATE["family"] is None: print("[icons] icon font not available -> falling back to the svg/ folder")
    return _STATE["family"]


def glyph_of(name):
    """The character (code point) of an icon name, or None."""
    mat = ICON_ALIASES.get(name, name)
    cp = GLYPHS.get(mat)
    return chr(cp) if cp else None


def glyph_font(px):
    f = QFont(icon_family() or "Material Icons Outlined"); f.setPixelSize(int(px)); f.setStyleStrategy(QFont.PreferAntialias); return f


# ---- legacy svg fallback (only used when the font is missing and cannot be downloaded) ----
def _find_svg_dir():
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        if os.path.isdir(os.path.join(here, "svg")): return os.path.join(here, "svg")
        here = os.path.dirname(here)
    return os.path.join(os.getcwd(), "svg")


SVG_DIR = _find_svg_dir()
_SVG_NAMES = {"split": ("scissors",), "cut": ("scissors",), "duplicate": ("copy-alt", "copy"), "delete": ("trash",), "play": ("play",), "pause": ("pause",),
              "previous": ("step-backward", "rewind"), "next": ("step-forward", "forward"), "import": ("plus", "add"), "text": ("text", "letter-case"),
              "keyframe": ("diamond",), "zoom_fit": ("expand",), "save": ("disk",), "export": ("upload", "file-export"), "video": ("film", "video-camera"),
              "image": ("picture",), "audio": ("music-alt", "music"), "close": ("cross", "cross-small"), "group": ("object-group", "layers"),
              "compound": ("layers", "copy"), "extract": ("waveform-path", "music-alt"), "trim_left": ("arrow-to-left",), "trim_right": ("arrow-to-right",),
              "angle_left": ("angle-left",), "nodes": ("circle-nodes", "workflow", "sitemap"), "folder_open": ("folder-open", "folder")}


def _svg_path(name):
    for n in _SVG_NAMES.get(name, (name,)):
        for fn in ("fi-br-%s.svg" % n, "%s.svg" % n):
            p = os.path.join(SVG_DIR, fn)
            if os.path.isfile(p): return p
    return None


def _svg_pixmap_legacy(name, color, size):
    pm = QPixmap(size, size); pm.fill(Qt.transparent)
    path = _svg_path(name) if HAS_SVG else None
    if not path:
        if name not in _SVG_WARNED: _SVG_WARNED.add(name); print("[icons] no icon for '%s'" % name)
        return pm
    r = QSvgRenderer(path)
    if not r.isValid(): return pm
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.SmoothPixmapTransform)
    r.render(p, QRectF(0, 0, size, size)); p.setCompositionMode(QPainter.CompositionMode_SourceIn); p.fillRect(pm.rect(), QColor(color)); p.end()
    return pm


# ---- public API (same names as before, so nothing else in the program changes) ----
def svg_pixmap(name, color="#ffffff", size=24, dpr=1.0):
    """The icon `name` as a square pixmap in `color`."""
    px = max(1, int(round(size * dpr)))
    fam = icon_family(); ch = glyph_of(name)
    if not fam or not ch: return _svg_pixmap_legacy(name, color, px)
    pm = QPixmap(px, px); pm.fill(Qt.transparent); p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing); p.setRenderHint(QPainter.TextAntialiasing)
    p.setFont(glyph_font(px)); p.setPen(QColor(color)); p.drawText(QRectF(0, 0, px, px), Qt.AlignCenter, ch); p.end()
    pm.setDevicePixelRatio(dpr); return pm


def svg_icon(name, color="#dfe3ea", on="#22d3ee", off="#5d6476"):
    """QIcon: normal = color, checked = cyan, disabled = grey."""
    key = (name, color, on, off)
    if key in _ICON_CACHE: return _ICON_CACHE[key]
    ic = QIcon()
    for px in (16, 20, 24, 32, 48, 64):
        ic.addPixmap(svg_pixmap(name, color, px), QIcon.Normal, QIcon.Off)
        ic.addPixmap(svg_pixmap(name, on, px), QIcon.Normal, QIcon.On)
        ic.addPixmap(svg_pixmap(name, off, px), QIcon.Disabled, QIcon.Off)
    _ICON_CACHE[key] = ic
    return ic


def svg_combo_icon(names, color="#dfe3ea"):
    """Several icons side by side in one QIcon."""
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


def app_icon(name, color=None):
    """Icon used everywhere in the app (an optional colour overrides the default light grey)."""
    return svg_icon(name, color) if color else svg_icon(name)


def icon_label(name, color="#9aa4b8", size=16):
    """A small QLabel that shows one icon (for row labels, so a row says what it is without words)."""
    l = QLabel(); l.setPixmap(svg_pixmap(name, color, size)); l.setFixedSize(size + 2, size + 2); l.setAlignment(Qt.AlignCenter); return l


def set_play_icon(btn, playing):
    if hasattr(btn, "setIconName"): btn.setIconName("pause" if playing else "play"); return
    btn.setText(""); btn.setIcon(app_icon("pause" if playing else "play"))
