"""Appearance settings (sizes + colors) and the application stylesheet."""
from .deps import *


THEME_DEFS = OrderedDict([
    ("ui_font",   ("Interface", "Font size (px)", "int", 12, 9, 22)),
    ("icon_size", ("Interface", "Toolbar icon size (px)", "int", 18, 12, 34)),
    ("ui_window", ("Interface", "Window background", "color", "#0e0e10", None, None)),
    ("ui_panel",  ("Interface", "Panel background", "color", "#1b1b1e", None, None)),
    ("ui_button", ("Interface", "Button background", "color", "#2a2a2e", None, None)),
    ("ui_input",  ("Interface", "Input fields / borders", "color", "#26262a", None, None)),
    ("ui_text",   ("Interface", "Text", "color", "#e6e6e6", None, None)),
    ("ui_text_dim", ("Interface", "Secondary text", "color", "#9fb3d9", None, None)),
    ("ui_accent", ("Interface", "Accent (cyan)", "color", "#22d3ee", None, None)),
    ("ui_accent2", ("Interface", "Accent (blue)", "color", "#2f7bff", None, None)),

    ("tl_head_w",  ("Timeline sizes", "Track header width", "int", 150, 100, 320)),
    ("tl_ruler_h", ("Timeline sizes", "Ruler height", "int", 30, 20, 60)),
    ("tl_video_h", ("Timeline sizes", "Video track height", "int", 66, 30, 200)),
    ("tl_audio_h", ("Timeline sizes", "Audio track height", "int", 48, 24, 160)),
    ("tl_gap",     ("Timeline sizes", "Gap between tracks", "int", 6, 0, 24)),
    ("tl_radius",  ("Timeline sizes", "Clip corner radius", "int", 6, 0, 16)),
    ("tl_handle_w", ("Timeline sizes", "Trim handle width", "int", 4, 2, 12)),
    ("tl_playhead_w", ("Timeline sizes", "Playhead width", "float", 1.5, 1.0, 6.0)),

    ("tl_bg",         ("Timeline colors", "Background", "color", "#0a0f1c", None, None)),
    ("tl_lane_video", ("Timeline colors", "Video track lane", "color", "#0d1424", None, None)),
    ("tl_lane_audio", ("Timeline colors", "Audio track lane", "color", "#0b1420", None, None)),
    ("tl_header_bg",  ("Timeline colors", "Track header", "color", "#111a2e", None, None)),
    ("tl_ruler_bg",   ("Timeline colors", "Ruler", "color", "#0b1222", None, None)),
    ("tl_playhead",   ("Timeline colors", "Playhead line", "color", "#ffffff", None, None)),
    ("tl_playhead_head", ("Timeline colors", "Playhead head", "color", "#2f7bff", None, None)),
    ("tl_snap",       ("Timeline colors", "Snap line", "color", "#00c2ff", None, None)),
    ("tl_select",     ("Timeline colors", "Selected clip outline", "color", "#ffffff", None, None)),
    ("marquee",       ("Timeline colors", "Box selection", "color", "#2f7bff", None, None)),
    ("clip_video",    ("Timeline colors", "Video clip", "color", "#1f4fbf", None, None)),
    ("clip_image",    ("Timeline colors", "Image clip", "color", "#1d6fa5", None, None)),
    ("clip_gif",      ("Timeline colors", "GIF clip", "color", "#3b4fc4", None, None)),
    ("clip_text",     ("Timeline colors", "Text clip", "color", "#6b3fd1", None, None)),
    ("clip_audio",    ("Timeline colors", "Audio clip", "color", "#0f7c8c", None, None)),
    ("tl_wave",       ("Timeline colors", "Waveform", "color", "#4fd1e8", None, None)),
    ("tl_wave_vol",   ("Timeline colors", "Volume line", "color", "#ffd166", None, None)),

    ("key_size",      ("Keyframes", "Keyframe size", "int", 7, 3, 16)),
    ("key_color",     ("Keyframes", "Keyframe", "color", "#c9a24a", None, None)),
    ("key_color_sel", ("Keyframes", "Keyframe (clip selected)", "color", "#ffd166", None, None)),
    ("key_picked",    ("Keyframes", "Box-selected keyframe", "color", "#22d3ee", None, None)),

    ("vp_bg",          ("Viewport", "Background", "color", "#05080f", None, None)),
    ("vp_outline",     ("Viewport", "Selection outline", "color", "#ffffff", None, None)),
    ("vp_handle",      ("Viewport", "Handle border", "color", "#2f7bff", None, None)),
    ("vp_handle_size", ("Viewport", "Handle size", "int", 5, 3, 14)),
    ("vp_outline_w",   ("Viewport", "Outline width", "float", 1.5, 1.0, 6.0)),
    ("vp_guide",       ("Viewport", "Snap guides", "color", "#00c8ff", None, None)),

    ("meter_show", ("Audio meter", "Show level meter in viewport", "bool", True, None, None)),
    ("meter_w",    ("Audio meter", "Meter width (px)", "int", 14, 6, 40)),
    ("meter_low",  ("Audio meter", "Low level", "color", "#2ecc71", None, None)),
    ("meter_mid",  ("Audio meter", "Mid level", "color", "#f1c40f", None, None)),
    ("meter_high", ("Audio meter", "Peak level", "color", "#e74c3c", None, None)),
    ("meter_bg",   ("Audio meter", "Background", "color", "#0a0f1c", None, None)),
    ("nd_canvas",    ("Node editor", "Canvas background", "color", "#2a2d33", None, None)),
    ("nd_grid",      ("Node editor", "Canvas grid dots", "color", "#4a505c", None, None)),
    ("nd_node",      ("Node editor", "Node body", "color", "#3f4551", None, None)),
    ("nd_node_text", ("Node editor", "Node title text", "color", "#ffffff", None, None)),
    ("nd_wire",      ("Node editor", "Wire colour", "color", "#9fb3d9", None, None)),

    ("nd_cat_input",     ("Node categories", "Input", "color", "#2b7fd6", None, None)),
    ("nd_cat_math",      ("Node categories", "Math", "color", "#2fa36b", None, None)),
    ("nd_cat_logic",     ("Node categories", "Logic", "color", "#d98a1f", None, None)),
    ("nd_cat_transform", ("Node categories", "Transform", "color", "#8a5bd6", None, None)),
    ("nd_cat_effect",    ("Node categories", "Effect", "color", "#d65b9a", None, None)),
    ("nd_cat_output",    ("Node categories", "Output", "color", "#d65b4a", None, None)),
])


UI = {k: v[3] for k, v in THEME_DEFS.items()}


def load_theme(d):
    for k, v in (d or {}).items():
        if k not in THEME_DEFS: continue
        kind, dflt, lo, hi = THEME_DEFS[k][2:6]
        try:
            if kind == "int": UI[k] = max(lo, min(hi, int(v)))
            elif kind == "float": UI[k] = max(lo, min(hi, float(v)))
            elif kind == "bool": UI[k] = bool(v)
            elif kind == "color" and QColor(v).isValid(): UI[k] = QColor(v).name()
        except Exception: pass


def theme_changes(): return {k: v for k, v in UI.items() if v != THEME_DEFS[k][3]}


QSS_COLOR_MAP = {"ui_window": ("#0e0e10", "#070b14"), "ui_panel": ("#1b1b1e",), "ui_button": ("#2a2a2e",),
                 "ui_input": ("#26262a",), "ui_text": ("#e6e6e6",), "ui_text_dim": ("#9fb3d9", "#8fa6d6"),
                 "ui_accent": ("#22d3ee", "#00c2d1"), "ui_accent2": ("#2f7bff", "#2f6bff")}


def build_qss(base):
    sub = {}
    for key, olds in QSS_COLOR_MAP.items():
        if UI[key].lower() != THEME_DEFS[key][3].lower():
            for o in olds: sub[o] = UI[key]
    q = base
    if sub:
        pat = re.compile("|".join(re.escape(o) for o in sub), re.I)
        q = pat.sub(lambda m: sub[m.group(0).lower()], q)
    d = int(UI["ui_font"]) - 12
    if d: q = re.sub(r"font-size:\s*(\d+)px", lambda m: "font-size:%dpx" % max(6, int(m.group(1)) + d), q)
    return q


QSS_BASE = """
* { color:#d6e2ff; font-family:'Segoe UI','Noto Sans Thai','Inter',sans-serif; font-size:12px; }
QFrame#Shell { background:#070b14; border:1px solid #18233d; border-radius:14px; }
QFrame#Shell[flat="true"] { border:none; border-radius:0px; }
QLabel#Logo { color:#5aa2ff; font-weight:800; font-size:14px; }
QLabel#ProjTitle { color:#9fb3d9; font-weight:600; }
QLabel#Dim { color:#6b7a99; }
QLabel#H1 { font-size:24px; font-weight:800; }
QLabel#H2 { font-size:16px; font-weight:700; }
QLabel#PanelTitle { color:#8fa6d6; font-weight:700; }
QLabel#Toast { background:#14244a; border:1px solid #2f7bff; border-radius:10px; padding:8px 16px; color:#e6eeff; }
QFrame#Panel { background:#0d1424; border:1px solid #17223b; border-radius:12px; }
QFrame#Hero { background:qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #10224a, stop:1 #0a1226); border:1px solid #1d2f57; border-radius:16px; }
QFrame#Card { background:#0d1424; border:1px solid #22345c; border-radius:14px; }
QPushButton { background:#141f36; border:1px solid #22314f; border-radius:8px; padding:6px 14px; }
QPushButton:hover { background:#1a2948; border-color:#2f7bff; }
QPushButton:disabled { color:#4a5878; }
QPushButton#Accent { background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #2f6bff, stop:1 #00a8ff); border:none; color:white; font-weight:700; }
QPushButton#Accent:hover { background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #4a80ff, stop:1 #29b8ff); }
QToolButton { background:transparent; border:none; border-radius:6px; padding:4px 7px; color:#b8c7e8; }
QToolButton:hover { background:#18264a; }
QToolButton:checked { background:#16305f; color:#6fb1ff; }
QToolButton#WinClose:hover { background:#c42b3a; color:white; }
QToolButton::menu-indicator { image:none; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QKeySequenceEdit, QFontComboBox {
  background:#0a1020; border:1px solid #1f2d4a; border-radius:6px; padding:3px 6px; selection-background-color:#2f7bff; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QComboBox:focus { border-color:#2f7bff; }
QComboBox::drop-down { border:none; width:18px; }
QDoubleSpinBox#PropSpin::up-button, QDoubleSpinBox#PropSpin::down-button { subcontrol-origin:border; width:0px; border:none; }
QComboBox QAbstractItemView { background:#0d1424; border:1px solid #22314f; selection-background-color:#2f7bff; outline:none; }
QTabWidget::pane { border:none; }
QTabBar::tab { background:transparent; padding:6px 10px; color:#6b7a99; border-bottom:2px solid transparent; }
QTabBar::tab:selected { color:#6fb1ff; border-bottom:2px solid #2f7bff; }
QTabBar::tab:hover { color:#b8c7e8; }
QSplitter::handle { background:transparent; }
QScrollArea { background:transparent; border:none; }
QScrollArea > QWidget > QWidget { background:transparent; }
QScrollBar:vertical { background:transparent; width:10px; margin:2px; }
QScrollBar:horizontal { background:transparent; height:10px; margin:2px; }
QScrollBar::handle { background:#22314f; border-radius:3px; min-height:24px; min-width:24px; }
QScrollBar::handle:hover { background:#2f4a7a; }
QScrollBar::add-line, QScrollBar::sub-line { width:0; height:0; }
QScrollBar::add-page, QScrollBar::sub-page { background:transparent; }
QListWidget { background:transparent; border:none; outline:none; }
QListWidget::item { border-radius:8px; padding:4px; color:#9fb3d9; }
QListWidget::item:hover { background:#121d35; }
QListWidget::item:selected { background:#16305f; color:white; }
QTreeWidget { background:transparent; border:none; outline:none; }
QTreeWidget::item { border-radius:6px; padding:3px; color:#9fb3d9; }
QTreeWidget::item:hover { background:#121d35; }
QTreeWidget::item:selected { background:#16305f; color:white; }
QSlider::groove:horizontal { height:4px; background:#1f2d4a; border-radius:2px; }
QSlider::sub-page:horizontal { background:#2f7bff; border-radius:2px; }
QSlider::handle:horizontal { background:#e6eeff; width:12px; height:12px; margin:-4px 0; border-radius:6px; }
QMenu { background:#0d1424; border:1px solid #22314f; border-radius:10px; padding:5px; }
QMenu::item { padding:6px 22px 6px 14px; border-radius:6px; }
QMenu::item:selected { background:#2f6bff; }
QMenu::separator { height:1px; background:#1f2d4a; margin:4px 8px; }
QHeaderView::section { background:#0d1424; border:none; padding:6px; color:#8fa6d6; }
QTableWidget { background:#0a1020; border:1px solid #1f2d4a; border-radius:8px; gridline-color:#141f36; }
QProgressBar { background:#0a1020; border:1px solid #1f2d4a; border-radius:7px; text-align:center; }
QProgressBar::chunk { background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #2f6bff, stop:1 #00a8ff); border-radius:6px; }
QCheckBox::indicator { width:14px; height:14px; border-radius:4px; border:1px solid #2f4a7a; background:#0a1020; }
QCheckBox::indicator:checked { background:#2f7bff; border-color:#2f7bff; }
QToolTip { background:#0d1424; color:#d6e2ff; border:1px solid #2f7bff; border-radius:6px; padding:4px; }
"""


QSS_CAPCUT = """
* { color:#e6e6e6; font-family:'Segoe UI','Noto Sans Thai',sans-serif; font-size:12px; }
QMainWindow, QStackedWidget { background:#0e0e10; }
QFrame#Shell { background:#0e0e10; border:none; border-radius:0; }
QFrame#Panel { background:#1b1b1e; border:1px solid #26262a; border-radius:8px; }
QSplitter::handle { background:#0e0e10; }
QPushButton { background:#2a2a2e; border:1px solid #333338; border-radius:6px; padding:5px 12px; }
QPushButton:hover { background:#34343a; }
QPushButton:disabled { color:#5d6476; }
QToolButton { background:transparent; border:none; border-radius:6px; padding:4px; }
QToolButton:hover { background:#2c2c31; }
QToolButton:checked { background:#12343a; color:#22d3ee; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background:#26262a; border:1px solid #303036;
    border-radius:5px; padding:3px 6px; selection-background-color:#00c2d1; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color:#00c2d1; }
QComboBox QAbstractItemView { background:#2a2a2e; border:1px solid #38383e; selection-background-color:#3a3a40; }
QTabWidget::pane { border:none; border-top:1px solid #2a2a2f; }
QTabBar::tab { background:transparent; color:#9a9aa2; padding:8px 12px; border:none; border-bottom:2px solid transparent; }
QTabBar::tab:selected { color:#ffffff; border-bottom:2px solid #22d3ee; }
QTabBar::tab:hover { color:#ffffff; }
QSlider::groove:horizontal { height:3px; background:#3a3a40; border-radius:1px; }
QSlider::sub-page:horizontal { background:#e6e6e6; border-radius:1px; }
QSlider::handle:horizontal { width:12px; height:12px; margin:-5px 0; border-radius:6px; background:#ffffff; }
QCheckBox::indicator { width:14px; height:14px; border-radius:3px; border:1px solid #55555c; background:#1b1b1e; }
QCheckBox::indicator:checked { background:#22d3ee; border-color:#22d3ee; }
QMenu { background:#2a2a2e; border:1px solid #38383e; border-radius:8px; padding:6px; }
QMenu::item { padding:6px 30px 6px 12px; border-radius:5px; }
QMenu::item:selected { background:#3a3a40; }
QMenu::item:disabled { color:#66666d; }
QMenu::separator { height:1px; background:#3a3a40; margin:5px 6px; }
QScrollBar:vertical { background:transparent; width:8px; }
QScrollBar::handle:vertical { background:#3a3a40; border-radius:4px; min-height:24px; }
QScrollBar:horizontal { background:transparent; height:8px; }
QScrollBar::handle:horizontal { background:#3a3a40; border-radius:4px; min-width:24px; }
QScrollBar::add-line, QScrollBar::sub-line { width:0; height:0; }
QToolTip { background:#2a2a2e; color:#e6e6e6; border:1px solid #38383e; padding:4px 6px; }
QWidget#CapToolbar { background:#1b1b1e; border-bottom:1px solid #26262a; }
"""


QSS_UI23 = """
QSplitter::handle:horizontal { background:#0e0e10; image:none; }
QSplitter::handle:vertical { background:#0e0e10; image:none; }
QSplitter::handle:hover { background:#22d3ee; }
QSplitter::handle:pressed { background:#00c2d1; }
QFrame#Panel { background:#1b1b1e; border:1px solid #26262a; border-radius:10px; }
QLabel#PanelTitle { color:#9a9aa2; font-weight:700; }
QLabel#Logo { color:#22d3ee; font-weight:800; font-size:15px; }
QLabel#ProjTitle { color:#e6e6e6; font-weight:600; }
QToolButton { padding:5px; border-radius:7px; }
QToolButton:hover { background:#2c2c31; }
QToolButton:pressed { background:#34343a; }
QToolButton:checked { background:#12343a; color:#22d3ee; }
QToolButton:disabled { color:#5d6476; }
QPushButton { border-radius:8px; padding:6px 12px; }
QPushButton#Accent { background:#22d3ee; color:#06121a; border:none; font-weight:700; }
QPushButton#Accent:hover { background:#4ae0f5; }
QTabBar::tab { padding:7px 13px; min-width:18px; }
QTabBar::tab:selected { border-bottom:2px solid #22d3ee; }
QTabBar::tab:!selected:hover { background:#232327; border-radius:6px; }
QProgressBar { background:#26262a; border:none; border-radius:3px; }
QProgressBar::chunk { background:#22d3ee; border-radius:3px; }
QFrame#TaskRow { background:#222226; border:1px solid #2e2e34; border-radius:10px; }
QLabel#TaskTitle { font-weight:600; }
QToolTip { background:#2a2a2e; color:#e6e6e6; border:1px solid #38383e; border-radius:6px; padding:4px 8px; }
QCheckBox::indicator:checked { background:#22d3ee; border-color:#22d3ee; }
QSlider::sub-page:horizontal { background:#22d3ee; }
"""


QSS = QSS_BASE + QSS_CAPCUT + QSS_UI23
