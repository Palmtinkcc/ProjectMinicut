#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniCut Launcher  (optimized edition)
======================================
Put this file in the MiniCut folder (next to file.py). Put update files (apply_*.py)
in the Patch/ folder.

  * Start MiniCut (Normal / Debug)   opens the program using the .venv
  * Smart Update                     detects and installs missing patches in order
  * Install Selected                 installs the selected patch (plus dependencies)
  * Undo Last Update                 reverts the most recent installed patch
  * Official Website                 opens https://bc-minicut.netlify.app/

How status is determined (fingerprint-based, works after folder copy):
  installed   files already at this version (or newer)
  ready       files match exactly what this patch expects
  queued      needs an earlier patch first (Smart Update handles ordering)
  blocked     a required earlier patch is missing from the Patch folder
  conflict    file was manually edited or is an unknown version
  included    a newer patch supersedes this one (started from the same file)

BUG FIXES vs original:
  * REPLACE/FILES/EDITS base field: now correctly handles list-of-hashes
    (patches 50+ declare base as a list of accepted prior versions)

The list auto-refreshes when you add/remove files in the Patch folder.
CLI:  python MiniCut_Launcher.pyw --cli status | plan | install | undo | start
"""
import ast, datetime, hashlib, json, os, re, shutil, subprocess, sys, threading, queue, time, webbrowser

_LAUNCHER_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT       = os.environ.get("MINICUT_ROOT") or os.path.join(_LAUNCHER_DIR, "minicut")
PATCH_DIR  = os.path.join(_LAUNCHER_DIR, "Patch")
BACKUP_DIR = os.path.join(_LAUNCHER_DIR, "_patch_backup")
IS_WIN     = os.name == "nt"
NOWIN      = 0x08000000 if IS_WIN else 0
DETACHED   = (0x00000008 | 0x00000200) if IS_WIN else 0
NEW_CONSOLE= 0x00000010 if IS_WIN else 0
WEBSITE    = "https://bc-minicut.netlify.app/"


# ─────────────────────────── helpers ───────────────────────────
def python_for_minicut():
    for cand in (os.path.join(ROOT, ".venv", "Scripts", "python.exe"),
                 os.path.join(ROOT, ".venv", "bin", "python")):
        if os.path.exists(cand): return cand
    exe = sys.executable
    if IS_WIN and os.path.basename(exe).lower() == "pythonw.exe":
        alt = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.exists(alt): return alt
    return exe


def norm_hash(b):
    return hashlib.sha256(b.replace(b"\r\n", b"\n")).hexdigest()


def path_of(rel): return os.path.join(ROOT, *rel.split("/"))


def _write_readme():
    try:
        with open(os.path.join(PATCH_DIR, "README.txt"), "w", encoding="utf-8") as f:
            f.write("Put update files here (apply_*.py). "
                    "The MiniCut Launcher lists them newest-first and installs in the right order.\n")
    except OSError: pass


def patch_files_on_disk():
    if not os.path.isdir(PATCH_DIR):
        os.makedirs(PATCH_DIR, exist_ok=True); _write_readme()
    return [os.path.join(PATCH_DIR, n) for n in os.listdir(PATCH_DIR)
            if n.lower().startswith("apply_") and n.lower().endswith(".py")]


def version_key(name, mtime=0.0):
    low = name.lower()
    if "effects" in low: return (0, 0, 0, 0)
    m = re.search(r"perf_gpu_patch(?:_v(\d+))?", low)
    if m: return (1, int(m.group(1) or 1), 0, 0)
    m = re.match(r"apply_(\d+)(?:\.(\d+))?", low)
    if m: return (2, int(m.group(1)), int(m.group(2) or 0), 0)
    m = re.search(r"_v(\d+)", low)
    if m: return (2, int(m.group(1)), 0, 0)
    return (3, 0, 0, mtime)


def short_label(name):
    low = name.lower()
    if "effects" in low: return "Effects"
    m = re.search(r"perf_gpu_patch(?:_v(\d+))?", low)
    if m: return "Perf/GPU v%s" % (m.group(1) or "1")
    m = re.match(r"apply_(\d+(?:\.\d+)?)", low)
    if m:
        n = m.group(1)
        try:
            major = int(float(n))
            if major >= 33:
                return "32(V%d)" % (major - 32)
        except (ValueError, TypeError): pass
        return "Patch " + n
    return os.path.splitext(name)[0]


# ─────────────────────────── patch loading ───────────────────────────
class Patch:
    __slots__ = ("path","name","label","mtime","size","key","pname","title","body",
                 "files","error","_sig")
    def __init__(self, path):
        self.path = path; self.name = os.path.basename(path)
        self.label = short_label(self.name)
        st = os.stat(path); self.mtime = st.st_mtime; self.size = st.st_size
        self.key = version_key(self.name, self.mtime)
        self.pname = None; self.title = self.name; self.body = ""
        self.files = []   # (rel, base_hash|None, new_hash, mode)  mode: edit|new|soft
        self.error = None; self._sig = None


def _literal(node):
    try: return ast.literal_eval(node)
    except Exception: return None


def _normalize_base(b):
    """
    BUG FIX: newer patches (50+) declare base as a list of accepted prior hashes.
    The graph only needs one canonical 'base' per (rel, new) edge — we keep the
    list so Graph.parents can store all accepted parents correctly.
    Returns a list (possibly empty/None-containing).
    """
    if b is None: return [None]
    if isinstance(b, list): return b
    return [b]


def read_patch_notes(src, fallback):
    m = re.search(r'"""(.*?)"""', src, re.S)
    if not m: return fallback, ""
    doc_lines = m.group(1).strip("\n").split("\n")
    if not doc_lines: return fallback, ""
    title = doc_lines[0].strip() or fallback
    i = 1
    if i < len(doc_lines) and doc_lines[i].strip() and set(doc_lines[i].strip()) <= set("="): i += 1
    lines = []
    for ln in doc_lines[i:]:
        s = ln.strip()
        if not s: continue
        if s.lower().startswith("files changed") or s.lower().startswith("python "): break
        lines.append(s)
    body, cur = [], None
    for s in lines:
        if s.startswith("*"):
            if cur is not None: body.append("•  " + cur)
            cur = s.lstrip("*").strip()
        elif cur is not None: cur += " " + s
        else: body.append(s)
    if cur is not None: body.append("•  " + cur)
    return title, "\n".join(body)


def load_patch(path):
    p = Patch(path)
    try:
        src = open(path, encoding="utf-8", errors="replace").read()
        p.title, p.body = read_patch_notes(src, p.name)
        tree = ast.parse(src)
    except Exception as ex:
        p.error = "cannot read: %s" % ex; return p
    vals = {}
    KEYS = ("EDITS","REPLACE","NEW_FILES","FILES","PATCH_NAME","REL","BASE_HASH","NEW_HASH")
    for n in tree.body:
        if (isinstance(n, ast.Assign) and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name)
                and n.targets[0].id in KEYS):
            vals[n.targets[0].id] = _literal(n.value)
    p.pname = vals.get("PATCH_NAME") if isinstance(vals.get("PATCH_NAME"), str) else None
    try:
        # EDITS format: base is always a single hash string
        for rel, i in (vals.get("EDITS") or {}).items():
            p.files.append((rel, i["base"], i["new"], "edit"))

        # REPLACE format: base may be string OR list (BUG FIX)
        for rel, i in (vals.get("REPLACE") or {}).items():
            bases = _normalize_base(i["base"])
            for b in bases:
                p.files.append((rel, b, i["new"], "edit"))

        # FILES format: base may be None, string, or list (BUG FIX)
        for rel, i in (vals.get("FILES") or {}).items():
            bases = _normalize_base(i.get("base"))
            soft = bool(i.get("soft")) or (i.get("base") is None)
            mode = "soft" if soft else "edit"
            for b in bases:
                p.files.append((rel, b, i["new"], mode))

        # NEW_FILES format
        for rel, s in (vals.get("NEW_FILES") or {}).items():
            nh = hashlib.sha256(s.replace("\r\n", "\n").encode("utf-8")).hexdigest()
            p.files.append((rel, None, nh, "new"))

        # Standalone REL/BASE_HASH/NEW_HASH format
        rel = vals.get("REL"); bh = vals.get("BASE_HASH"); nh = vals.get("NEW_HASH")
        if isinstance(rel, str) and isinstance(bh, str) and isinstance(nh, str):
            if not any(item[0] == rel for item in p.files):
                p.files.append((rel, bh, nh, "edit"))

    except Exception as ex:
        p.error = "unknown update format: %r" % (ex,)

    if not p.files and not p.error: p.error = "no file list found in this update"
    if "effects" in p.name.lower() and not p.pname: p.pname = "effects"
    return p


_PATCH_CACHE = {}


def load_patches():
    out = []
    for path in patch_files_on_disk():
        try: st = os.stat(path)
        except OSError: continue
        sig = (path, st.st_mtime_ns, st.st_size)
        p = _PATCH_CACHE.get(path)
        if p is None or getattr(p, "_sig", None) != sig:
            p = load_patch(path); p._sig = sig; _PATCH_CACHE[path] = p
        out.append(p)
    for k in [k for k in _PATCH_CACHE if k not in {x.path for x in out}]:
        _PATCH_CACHE.pop(k, None)
    return sorted(out, key=lambda p: (p.key, p.name))


_HASH_CACHE = {}


def disk_hashes(rels):
    res = {}
    for rel in rels:
        p = path_of(rel)
        try: st = os.stat(p)
        except OSError: res[rel] = None; continue
        sig = (st.st_mtime_ns, st.st_size); c = _HASH_CACHE.get(p)
        if c and c[0] == sig: res[rel] = c[1]; continue
        try: h = norm_hash(open(p, "rb").read())
        except OSError: h = None
        _HASH_CACHE[p] = (sig, h); res[rel] = h
    return res


# ─────────────────────────── graph / status ───────────────────────────
class Graph:
    def __init__(self, patches):
        self.parents = {}        # rel -> {new_hash: {base_hash, ...}}
        self.producers = {}      # (rel, new_hash) -> [patch, ...]
        for p in patches:
            if p.error: continue
            for rel, b, n, mode in p.files:
                self.parents.setdefault(rel, {}).setdefault(n, set())
                if b: self.parents[rel][n].add(b)
                self.producers.setdefault((rel, n), []).append(p)
        self.known = {rel: set(d) | {b for bs in d.values() for b in bs}
                      for rel, d in self.parents.items()}
        self._anc = {}

    def ancestors(self, rel, h):
        k = (rel, h)
        if k in self._anc: return self._anc[k]
        seen, stack = set(), [h]; par = self.parents.get(rel, {})
        while stack:
            x = stack.pop()
            for b in par.get(x, ()):
                if b not in seen: seen.add(b); stack.append(b)
        self._anc[k] = seen; return seen


def file_state(G, rel, b, n, mode, c):
    if c is not None and c == n: return "new"
    A = G.ancestors(rel, c) if c is not None else set()
    if n in A: return "new"
    if mode == "soft": return "ready"
    if mode == "new": return "ready" if c is None else "conflict"
    if c is None:
        return "waiting" if (rel, b) in G.producers else "missing"
    if c == b: return "ready"
    if b in A: return "sibling"
    if c in G.ancestors(rel, b): return "waiting"
    if c in G.known.get(rel, ()) and (rel, b) not in G.producers: return "gap"
    return "conflict"


def judge(G, p, cur):
    # Deduplicate by rel+new for multi-base entries (each base entry is a separate row)
    seen_rn = set(); sts = []
    for rel, b, n, mode in p.files:
        key = (rel, n)
        if key in seen_rn: continue
        seen_rn.add(key)
        sts.append((rel, file_state(G, rel, b, n, mode, cur.get(rel))))
    kinds = {s for _, s in sts}
    names = lambda k: ", ".join(r.split("/")[-1] for r, s in sts if s == k)
    if kinds <= {"new"}: return "installed", "All files of this update are in place."
    if kinds <= {"new", "sibling"}: return "included", "A newer update that starts from the same files has replaced this one."
    if "conflict" in kinds: return "conflict", "Not a known version (edited by hand?): " + names("conflict")
    if "gap" in kinds: return "blocked", "An earlier update needed is not in the Patch folder: " + names("gap")
    if "missing" in kinds: return "conflict", "File missing: " + names("missing")
    if "sibling" in kinds: return "conflict", "Mixed versions: " + names("sibling")
    if "waiting" in kinds: return "waiting", "Needs an earlier update first: " + names("waiting")
    return "ready", "Files are exactly what this update expects."


def analyze(patches=None, hashes=None):
    patches = load_patches() if patches is None else patches
    good = [p for p in patches if not p.error]
    G = Graph(good)
    rels = sorted({rel for p in good for rel, *_ in p.files})
    real = disk_hashes(rels) if hashes is None else dict(hashes)
    info = {}
    for p in patches:
        if p.error: info[p.path] = {"status": "error", "reason": p.error, "plan": None, "needs": []}
        else:
            st, why = judge(G, p, real)
            info[p.path] = {"status": st, "reason": why, "plan": None, "needs": []}

    cur = dict(real); producer_of = {}; plan = []
    pending = [p for p in good if info[p.path]["status"] in ("ready", "waiting")]
    while pending:
        cands = [p for p in pending if judge(G, p, cur)[0] == "ready"]
        if not cands: break
        group = {}
        for p in cands:
            for rel, b, n, mode in p.files:
                if mode == "edit" and cur.get(rel) == b:
                    group.setdefault((rel, b), []).append(p)
        loser = {}
        for (_rel, _b), ps in group.items():
            if len(ps) < 2: continue
            def score(q):
                new = {(r, h) for r, _b2, h, _m in q.files}
                used = sum(1 for o in good if o is not q
                           for r, b2, _h, _m in o.files if (r, b2) in new)
                return (used, len(q.files), q.key)
            best = max(ps, key=score)
            for q in ps:
                if q is not best and q.path not in loser: loser[q.path] = best
        for lp, best in loser.items():
            q = next(x for x in cands if x.path == lp)
            if q in pending: pending.remove(q)
            info[lp].update(status="included",
                            reason="Replaced by %s (starts from the same files)." % best.label)
        cands = [p for p in cands if p.path not in loser]
        if not cands: continue
        p = min(cands, key=lambda q: (q.key, q.name))
        needs = []
        for rel, b, n, mode in p.files:
            if mode == "edit" and rel in producer_of and producer_of[rel] is not p:
                if producer_of[rel] not in needs: needs.append(producer_of[rel])
        for rel, b, n, mode in p.files: cur[rel] = n; producer_of[rel] = p
        plan.append(p); pending.remove(p)
        info[p.path]["plan"] = len(plan); info[p.path]["needs"] = needs

    for p in pending:
        rec = info[p.path]
        if rec["status"] == "waiting":
            rec["status"] = "blocked"
            rec["reason"] = ("An earlier update needed is not in the Patch folder. "
                             + rec["reason"].split(": ", 1)[-1])
    for p in plan:
        rec = info[p.path]
        if rec["status"] == "waiting":
            rec["status"] = "queued"
            rec["reason"] = "Will be installed after: " + (
                ", ".join(q.label for q in rec["needs"]) or "earlier updates")

    items = []
    for p in sorted(patches, key=lambda q: (q.key, q.name), reverse=True):
        r = info[p.path]; items.append({"patch": p, **r})
    done = [it["patch"] for it in items if it["status"] in ("installed", "included")]
    current = max(done, key=lambda q: (q.key, q.name)).label if done else None
    count = {}
    for it in items: count[it["status"]] = count.get(it["status"], 0) + 1
    return {"items": items, "plan": plan, "current": current, "count": count,
            "final": cur, "real": real, "graph": G}


def plan_for(result, patch):
    rec = {it["patch"].path: it for it in result["items"]}
    if rec[patch.path]["plan"] is None: return []
    need, stack = set(), [patch]
    while stack:
        q = stack.pop()
        if q.path in need: continue
        need.add(q.path); stack.extend(rec[q.path]["needs"])
    return [p for p in result["plan"] if p.path in need]


# ─────────────────────────── install / undo ───────────────────────────
_last_stamp = {"s": 0}


def _wait_new_second():
    while int(time.time()) == _last_stamp["s"]: time.sleep(0.1)


def _run_patch(patch_path, py, timeout=900):
    tmp = os.path.join(ROOT, "_launcher_run_" + os.path.basename(patch_path))
    shutil.copy2(patch_path, tmp)
    try:
        r = subprocess.run([py, tmp, "--no-pause"], cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=NOWIN)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    finally:
        try: os.remove(tmp)
        except OSError: pass


def install_patch(patch, py, log):
    before = set(os.listdir(BACKUP_DIR)) if os.path.isdir(BACKUP_DIR) else set()
    _wait_new_second(); _last_stamp["s"] = int(time.time())
    rc, out = _run_patch(patch.path, py)
    log(out.strip() or "(no output)")
    if os.path.isdir(BACKUP_DIR):
        for d in set(os.listdir(BACKUP_DIR)) - before:
            try:
                with open(os.path.join(BACKUP_DIR, d, "LAUNCHER.json"), "w", encoding="utf-8") as f:
                    json.dump({"file": patch.name, "label": patch.label}, f)
            except OSError: pass
    return rc == 0


def list_backups():
    if not os.path.isdir(BACKUP_DIR): return []
    out = []
    for d in sorted(os.listdir(BACKUP_DIR), reverse=True):
        mf = os.path.join(BACKUP_DIR, d, "MANIFEST.json")
        if os.path.exists(mf):
            try:
                man = json.load(open(mf, encoding="utf-8"))
                try: man["_launcher"] = json.load(open(os.path.join(BACKUP_DIR, d, "LAUNCHER.json"), encoding="utf-8"))
                except Exception: man["_launcher"] = {}
                out.append((d, man))
            except Exception: pass
    return out


def last_backup_label():
    items = list_backups()
    if not items: return None
    man = items[0][1]
    return man["_launcher"].get("label") or man.get("patch") or items[0][0]


def undo_last(log):
    items = list_backups()
    if not items: log("Nothing to undo."); return False
    stamp, man = items[0]; bdir = os.path.join(BACKUP_DIR, stamp)
    for rel in man.get("replaced", []):
        src = os.path.join(bdir, *rel.split("/")); dst = path_of(rel)
        shutil.copy2(src, dst); log("restored  " + rel)
    for rel in man.get("created", []):
        p = path_of(rel)
        if os.path.exists(p): os.remove(p); log("removed   " + rel)
    os.rename(os.path.join(bdir, "MANIFEST.json"),
              os.path.join(bdir, "MANIFEST.undone.json"))
    log("Undone: %s (%s)" % (man["_launcher"].get("label") or man.get("patch", "?"), stamp))
    return True


def start_minicut(debug=False):
    venv_py = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
    flags = (NEW_CONSOLE if debug else DETACHED) if IS_WIN else 0
    close = not debug
    if os.path.exists(venv_py) and os.path.exists(os.path.join(ROOT, "file.py")):
        subprocess.Popen([venv_py, "file.py"], cwd=ROOT, creationflags=flags, close_fds=close)
        return "started MiniCut (.venv)" + (" [debug]" if debug else "")
    if IS_WIN and os.path.exists(os.path.join(ROOT, "Run_MiniCut.bat")):
        subprocess.Popen(["cmd", "/c", "Run_MiniCut.bat"], cwd=ROOT, creationflags=0x10)
        return "started Run_MiniCut.bat"
    subprocess.Popen([sys.executable, "file.py"], cwd=ROOT, close_fds=close, creationflags=flags)
    return "started with " + sys.executable + (" [debug]" if debug else "")


def folder_signature():
    sig = []
    try:
        for n in sorted(os.listdir(PATCH_DIR)):
            if n.lower().startswith("apply_") and n.lower().endswith(".py"):
                st = os.stat(os.path.join(PATCH_DIR, n))
                sig.append((n, st.st_mtime_ns, st.st_size))
    except OSError: sig.append("nofolder")
    rels = {rel for p in _PATCH_CACHE.values() if not p.error for rel, *_ in p.files}
    for rel in sorted(rels):
        try: st = os.stat(path_of(rel)); sig.append((rel, st.st_mtime_ns, st.st_size))
        except OSError: sig.append((rel, None))
    return hash(tuple(sig))


# ─────────────────────────── colours ───────────────────────────
BG        = "#0e0e10"
PANEL     = "#1b1b1e"
PANEL_HI  = "#26262a"
ROW_SEL   = "#12353d"
BORDER    = "#2e2e33"
TEXT      = "#e6e6e6"
SUBTEXT   = "#9fb3d9"
CYAN      = "#22d3ee"
CYAN_HI   = "#5ee4f7"
BLUE      = "#2f7bff"
BLUE_HI   = "#6ea2ff"
ORANGE    = "#f59e0b"
ORANGE_HI = "#ffb73d"
GREEN     = "#22c55e"
GREEN_HI  = "#54e085"
RED       = "#ef4444"
PURPLE    = "#a855f7"
PURPLE_HI = "#c084fc"
GRAY_BTN  = "#2a2a2e"
GRAY_HI   = "#38383e"

STATUS_STYLE = {
    "ready":     ("Ready",       GREEN_HI),
    "queued":    ("Queued",      BLUE_HI),
    "installed": ("✓ Installed", "#5f7a6a"),
    "included":  ("Included",    SUBTEXT),
    "blocked":   ("Blocked",     ORANGE_HI),
    "conflict":  ("Conflict",    RED),
    "error":     ("Error",       RED),
}


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def lerp_color(c1, c2, t):
    a, b = _hex_to_rgb(c1), _hex_to_rgb(c2)
    return _rgb_to_hex(tuple(a[i] + (b[i]-a[i]) * t for i in range(3)))


def nice_title(p):
    t = p.title or p.name
    t = re.sub(r"^\s*MiniCut\s*(update\s*)?(patch\s*[\d.]*)?[\s:\-–—]*", "", t, flags=re.I)
    t = re.sub(r"\(\s*needs[^)]*\)", "", t, flags=re.I).strip(" :-–—")
    letters = [c for c in t if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.6:
        t = t.capitalize()
    return t or p.label


# ─────────────────────────── GUI ───────────────────────────
def run_gui():
    import tkinter as tk
    from tkinter import ttk, messagebox
    from tkinter import font as tkfont
    import math

    win = tk.Tk()
    win.title("MiniCut Launcher")
    win.geometry("1060x720")
    win.minsize(900, 620)
    win.configure(bg=BG)
    try: win.tk.call("tk", "scaling", 1.15)
    except tk.TclError: pass

    q = queue.Queue()
    busy = {"v": False}
    state = {"result": None, "selected": None, "known": set(), "new_names": set(),
             "auto": True, "sig": None, "analyzing": False, "again": False,
             "show_installed": True, "after_done": None, "checked": None}

    # ── animated particle background ──
    class ParticleBg(tk.Canvas):
        """Floating orbs + drifting grid lines, inspired by bc-minicut.netlify.app"""
        N_ORBS   = 7
        N_LINES  = 9
        FPS      = 30

        def __init__(self, parent):
            tk.Canvas.__init__(self, parent, bg=BG, highlightthickness=0, bd=0)
            import random, math
            self._rng = random.Random(42)
            self._t = 0.0
            self._orbs  = [self._new_orb(i) for i in range(self.N_ORBS)]
            self._lines = [self._new_line(i) for i in range(self.N_LINES)]
            self._job   = None
            self.bind("<Configure>", lambda _e: self._redraw())
            self._tick()

        def _new_orb(self, seed):
            r = self._rng
            return {
                "cx": r.random(), "cy": r.random(),
                "vx": (r.random()-0.5)*0.0004,
                "vy": (r.random()-0.5)*0.0004,
                "r":  r.uniform(60, 160),
                "phase": r.random()*6.28,
                "color": r.choice([CYAN, BLUE, PURPLE, GREEN]),
                "alpha": r.uniform(0.04, 0.12),
            }

        def _new_line(self, seed):
            r = self._rng
            return {
                "y": r.random(),
                "vy": (r.random()-0.5)*0.0002,
                "alpha": r.uniform(0.03, 0.09),
                "color": r.choice([CYAN, BLUE]),
            }

        def _blend(self, hex_color, alpha):
            """Blend color onto BG with given alpha (0–1)."""
            fg = _hex_to_rgb(hex_color)
            bg = _hex_to_rgb(BG)
            return _rgb_to_hex(tuple(bg[i] + (fg[i]-bg[i])*alpha for i in range(3)))

        def _radial_orb(self, cx, cy, r, color, alpha):
            """Draw radial gradient orb using concentric ovals."""
            steps = 8
            for i in range(steps, 0, -1):
                frac  = i / steps
                a_frac = alpha * (1 - frac**2)
                c = self._blend(color, a_frac)
                rr = r * frac
                self.create_oval(cx-rr, cy-rr, cx+rr, cy+rr,
                                 fill=c, outline="", tags="bg")

        def _redraw(self):
            self.delete("bg")
            w, h = self.winfo_width(), self.winfo_height()
            if w < 10 or h < 10: return
            import math
            t = self._t

            # drifting horizontal grid lines
            for ln in self._lines:
                y = (ln["y"] + t*ln["vy"]) % 1.0
                yy = y * h
                c = self._blend(ln["color"], ln["alpha"])
                self.create_line(0, yy, w, yy, fill=c, width=1, tags="bg")

            # glowing orbs
            for orb in self._orbs:
                pulse = 0.85 + 0.15 * math.sin(t * 0.8 + orb["phase"])
                cx = (orb["cx"] + t*orb["vx"]) % 1.0 * w
                cy = (orb["cy"] + t*orb["vy"]) % 1.0 * h
                self._radial_orb(cx, cy, orb["r"]*pulse, orb["color"], orb["alpha"])

            self.tag_lower("bg")

        def _tick(self):
            self._t += 1
            self._redraw()
            self._job = self.after(1000 // self.FPS, self._tick)

        def stop(self):
            if self._job: self.after_cancel(self._job); self._job = None

    # ── drawing helpers ──
    def draw_round_rect(canvas, x1, y1, x2, y2, r, fill, outline="", width=1, tag=None):
        r = max(1, min(r, (x2-x1)/2, (y2-y1)/2)); d = 2*r
        kw = {"tags": tag} if tag else {}
        fi = [
            canvas.create_arc(x1, y1, x1+d, y1+d, start=90,  extent=90,  fill=fill, outline=fill, width=0, **kw),
            canvas.create_arc(x2-d, y1, x2, y1+d, start=0,   extent=90,  fill=fill, outline=fill, width=0, **kw),
            canvas.create_arc(x1, y2-d, x1+d, y2, start=180, extent=90,  fill=fill, outline=fill, width=0, **kw),
            canvas.create_arc(x2-d, y2-d, x2, y2, start=270, extent=90,  fill=fill, outline=fill, width=0, **kw),
            canvas.create_rectangle(x1+r, y1, x2-r, y2, fill=fill, outline=fill, width=0, **kw),
            canvas.create_rectangle(x1, y1+r, x2, y2-r, fill=fill, outline=fill, width=0, **kw),
        ]
        bo = []
        if outline and width > 0:
            bo = [
                canvas.create_arc(x1, y1, x1+d, y1+d, start=90,  extent=90,  style="arc", outline=outline, width=width, **kw),
                canvas.create_arc(x2-d, y1, x2, y1+d, start=0,   extent=90,  style="arc", outline=outline, width=width, **kw),
                canvas.create_arc(x1, y2-d, x1+d, y2, start=180, extent=90,  style="arc", outline=outline, width=width, **kw),
                canvas.create_arc(x2-d, y2-d, x2, y2, start=270, extent=90,  style="arc", outline=outline, width=width, **kw),
                canvas.create_line(x1+r, y1, x2-r, y1, fill=outline, width=width, **kw),
                canvas.create_line(x1+r, y2, x2-r, y2, fill=outline, width=width, **kw),
                canvas.create_line(x1, y1+r, x1, y2-r, fill=outline, width=width, **kw),
                canvas.create_line(x2, y1+r, x2, y2-r, fill=outline, width=width, **kw),
            ]
        return fi, bo

    # ── animated button ──
    class RoundedButton(tk.Canvas):
        def __init__(self, parent, text, command, base, hi, fg="#06161a",
                     w=170, h=40, radius=12, font_size=11, bold=True):
            tk.Canvas.__init__(self, parent, width=w, height=h,
                               bg=parent["bg"], highlightthickness=0, bd=0, cursor="hand2")
            self.command = command
            self.base, self.hi, self.fg = base, hi, fg
            self.w, self.h, self.radius = w, h, radius
            self.enabled = True; self._cur = base; self._job = None
            self.fi, _ = draw_round_rect(self, 1, 1, w-1, h-1, radius, base)
            fam = "Segoe UI" if IS_WIN else "Arial"
            self.lbl = self.create_text(w/2, h/2, text=text, fill=fg,
                                        font=(fam, font_size, "bold" if bold else "normal"))
            self.bind("<Enter>",          self._enter)
            self.bind("<Leave>",          self._leave)
            self.bind("<Button-1>",       self._press)
            self.bind("<ButtonRelease-1>",self._release)

        def set_text(self, t): self.itemconfigure(self.lbl, text=t)

        def _fill(self, c):
            for it in self.fi: self.itemconfigure(it, fill=c, outline=c)
            self._cur = c

        def set_enabled(self, v):
            self.enabled = v
            if self._job: self.after_cancel(self._job); self._job = None
            self._fill(self.base if v else GRAY_BTN)
            self.itemconfigure(self.lbl, fill=(self.fg if v else SUBTEXT))
            self.configure(cursor="hand2" if v else "arrow")

        def _anim(self, target, steps=8, delay=12):
            if self._job: self.after_cancel(self._job)
            start = self._cur
            def step(i=0):
                self._fill(lerp_color(start, target, i/steps))
                if i < steps: self._job = self.after(delay, lambda: step(i+1))
            step()

        def _enter(self, _e):
            if self.enabled: self._anim(self.hi)
        def _leave(self, _e):
            if self.enabled: self._anim(self.base)
        def _press(self, _e):
            if self.enabled:
                for it in self.fi + [self.lbl]: self.move(it, 0, 1)
        def _release(self, e):
            if self.enabled:
                for it in self.fi + [self.lbl]: self.move(it, 0, -1)
                if 0 <= e.x <= self.w and 0 <= e.y <= self.h and self.command:
                    self.command()

    class IconButton(RoundedButton):
        def __init__(self, parent, glyph, command, size=34):
            RoundedButton.__init__(self, parent, glyph, command, GRAY_BTN, GRAY_HI,
                                   fg=TEXT, w=size, h=size, radius=size//2,
                                   font_size=13, bold=False)

    class RoundedPanel(tk.Canvas):
        def __init__(self, parent, radius=16, pad=14, fill=PANEL, outline=BORDER, height=None):
            kw = {"height": height} if height is not None else {}
            tk.Canvas.__init__(self, parent, bg=parent["bg"], highlightthickness=0, bd=0, **kw)
            self.radius, self.pad, self.fill, self.outline = radius, pad, fill, outline
            self.inner = tk.Frame(self, bg=fill)
            self._win = self.create_window(pad, pad, anchor="nw", window=self.inner)
            self.bind("<Configure>", self._redraw)

        def _redraw(self, _e=None):
            w, h = self.winfo_width(), self.winfo_height()
            if w < 4 or h < 4: return
            self.delete("bg")
            draw_round_rect(self, 1, 1, w-1, h-1, self.radius, self.fill, self.outline, 1, tag="bg")
            self.tag_lower("bg")
            self.coords(self._win, self.pad, self.pad)
            self.itemconfigure(self._win, width=max(1, w-2*self.pad), height=max(1, h-2*self.pad))

    class ProgressBar(tk.Canvas):
        def __init__(self, parent, height=6):
            tk.Canvas.__init__(self, parent, height=0, bg=parent["bg"],
                               highlightthickness=0, bd=0)
            self.bh = height; self.running = False; self._pos = 0.0
            self.bind("<Configure>", lambda _e: self._draw())

        def _draw(self):
            self.delete("all")
            if not self.running: return
            w, h = self.winfo_width(), self.bh
            if w < 4: return
            draw_round_rect(self, 0, 0, w, h, h/2, BORDER)
            seg = max(40, w*0.22); x = self._pos*(w+seg)-seg
            draw_round_rect(self, max(0, x), 0, min(w, x+seg), h, h/2, GREEN)

        def start(self):
            if self.running: return
            self.running = True; self.configure(height=self.bh); self._tick()

        def stop(self):
            self.running = False; self.configure(height=0); self.delete("all")

        def _tick(self):
            if not self.running: return
            self._pos = (self._pos + 0.02) % 1.0; self._draw(); self.after(20, self._tick)

    # ── patch list ──
    class PatchList(tk.Frame):
        ROW_H, GAP, PAD = 60, 6, 6

        def __init__(self, parent, on_select):
            tk.Frame.__init__(self, parent, bg=PANEL)
            self.on_select = on_select
            self.items, self.selected, self.new_names = [], None, set()
            self.canvas = tk.Canvas(self, bg=PANEL, highlightthickness=0, bd=0)
            self.vsb   = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
            self.canvas.configure(yscrollcommand=self.vsb.set)
            self.vsb.pack(side="right", fill="y"); self.canvas.pack(side="left", fill="both", expand=True)
            fam = "Segoe UI" if IS_WIN else "Arial"
            self.f_main = tkfont.Font(family=fam, size=11, weight="bold")
            self.f_sub  = tkfont.Font(family=fam, size=9)
            self.f_chip = tkfont.Font(family=fam, size=9, weight="bold")
            self._rows = []; self._hover = None
            self.canvas.bind("<Configure>", lambda _e: self.redraw())
            self.canvas.bind("<Button-1>",  self._click)
            self.canvas.bind("<Motion>",    self._motion)
            self.canvas.bind("<Enter>", lambda _e: self.canvas.bind_all("<MouseWheel>", self._wheel))
            self.canvas.bind("<Leave>", self._leave, add="+")

        def _leave(self, _e):
            self._hover = None
            try: self.canvas.unbind_all("<MouseWheel>")
            except tk.TclError: pass

        def _wheel(self, e):
            self.canvas.yview_scroll(int(-1*(e.delta/120)), "units")

        def set_items(self, items, selected, new_names):
            self.items, self.selected, self.new_names = items, selected, new_names
            self.redraw()

        def _fit(self, text, font, maxw):
            if maxw <= 20 or font.measure(text) <= maxw: return text
            lo, hi = 0, len(text)
            while lo < hi:
                mid = (lo+hi+1)//2
                if font.measure(text[:mid]+"…") <= maxw: lo = mid
                else: hi = mid-1
            return text[:lo].rstrip()+"…"

        def _row_fill(self, i):
            it = self.items[i]
            if it["patch"].path == self.selected: return ROW_SEL
            return GRAY_BTN if i == self._hover else PANEL_HI

        def redraw(self):
            y0 = self.canvas.yview()[0]
            self.canvas.delete("all"); self._rows = []
            w = max(self.canvas.winfo_width(), 200)
            for i, it in enumerate(self.items):
                p, st = it["patch"], it["status"]
                top = self.PAD + i*(self.ROW_H+self.GAP); bot = top+self.ROW_H
                sel = p.path == self.selected
                fills, _ = draw_round_rect(self.canvas, 4, top, w-8, bot, 12,
                                           self._row_fill(i), CYAN if sel else "", 1)
                self._rows.append(fills)
                chip, col = STATUS_STYLE.get(st, (st, TEXT))
                cx = w-8-14; chip_w = self.f_chip.measure(chip)+20
                draw_round_rect(self.canvas, cx-chip_w, top+10, cx, top+30, 10,
                                lerp_color(PANEL_HI, col, 0.22))
                self.canvas.create_text(cx-chip_w/2, top+20, text=chip, fill=col, font=self.f_chip)
                if it["plan"]:
                    self.canvas.create_text(cx, top+43, anchor="e",
                                            text="step %d" % it["plan"], fill=SUBTEXT, font=self.f_sub)
                self.canvas.create_oval(16, top+14, 24, top+22, fill=col, outline="")
                lbl = p.label + ("  NEW" if p.name in self.new_names else "")
                self.canvas.create_text(32, top+18, anchor="w",
                                        text=self._fit(lbl, self.f_main, cx-chip_w-36),
                                        fill=TEXT, font=self.f_main)
                self.canvas.create_text(32, top+42, anchor="w",
                                        text=self._fit(nice_title(p), self.f_sub, cx-40),
                                        fill=SUBTEXT, font=self.f_sub)
            total = self.PAD*2 + len(self.items)*(self.ROW_H+self.GAP)
            self.canvas.configure(scrollregion=(0, 0, w, total))
            self.canvas.yview_moveto(y0)

        def _index_at(self, y):
            yy = self.canvas.canvasy(y)-self.PAD
            if yy < 0: return None
            i = int(yy//(self.ROW_H+self.GAP))
            return i if 0 <= i < len(self.items) and (yy%(self.ROW_H+self.GAP)) <= self.ROW_H else None

        def _set_hover(self, i):
            if i == self._hover: return
            old, self._hover = self._hover, i
            for idx in (old, i):
                if idx is not None and idx < len(self._rows):
                    for it in self._rows[idx]:
                        self.canvas.itemconfigure(it, fill=self._row_fill(idx),
                                                  outline=self._row_fill(idx))

        def _motion(self, e):
            i = self._index_at(e.y)
            self._set_hover(i)
            self.canvas.configure(cursor="hand2" if i is not None else "arrow")

        def _click(self, e):
            i = self._index_at(e.y)
            if i is not None and self.on_select: self.on_select(self.items[i]["patch"].path)

        def scroll_to(self, path):
            for i, it in enumerate(self.items):
                if it["patch"].path == path:
                    total = self.PAD*2 + len(self.items)*(self.ROW_H+self.GAP)
                    self.canvas.yview_moveto(max(0.0, (self.PAD+i*(self.ROW_H+self.GAP)-40)/max(1, total)))
                    return

    # ── layout ──
    # Particle background fills the whole window; everything else floats on top
    bg_canvas = ParticleBg(win)
    bg_canvas.place(x=0, y=0, relwidth=1, relheight=1)

    # Use a real BG frame on top of the canvas
    outer = tk.Frame(win, bg=BG)
    outer.place(x=0, y=0, relwidth=1, relheight=1)
    outer.configure(bg=BG)
    # Make outer semi-transparent (Windows only via attributes)
    try: win.attributes("-transparentcolor", "")
    except Exception: pass

    # Re-do: particle bg drawn on a canvas placed behind a Frame
    tk.Widget.lower(bg_canvas, outer)

    pad_f = tk.Frame(outer, bg=BG)
    pad_f.pack(fill="both", expand=True, padx=18, pady=14)

    fam = "Segoe UI" if IS_WIN else "Arial"

    # Title row
    title_row = tk.Frame(pad_f, bg=BG)
    title_row.pack(fill="x")
    tk.Label(title_row, text="MINICUT", font=(fam, 22, "bold"), fg=CYAN, bg=BG).pack(side="left")
    tk.Label(title_row, text="Launcher", font=(fam, 22), fg=BLUE, bg=BG).pack(side="left", padx=(4,0))
    current_lbl = tk.Label(title_row, text="Current: —", font=(fam, 10, "bold"), fg=GREEN_HI, bg=BG)
    current_lbl.pack(side="right")

    # Location bar
    loc_panel = RoundedPanel(pad_f, radius=10, pad=10, fill=PANEL, height=40)
    loc_panel.pack(fill="x", pady=(8, 12))
    tk.Label(loc_panel.inner, text="Location", font=(fam, 10, "bold"), fg=TEXT, bg=PANEL).pack(side="left")
    tk.Label(loc_panel.inner, text=ROOT, font=(fam, 9), fg=SUBTEXT, bg=PANEL).pack(side="left", padx=(10,0))
    auto_lbl = tk.Label(loc_panel.inner, text="", font=(fam, 9, "bold"), fg=GREEN_HI, bg=PANEL, cursor="hand2")
    auto_lbl.pack(side="right")
    checked_lbl = tk.Label(loc_panel.inner, text="", font=(fam, 9), fg=SUBTEXT, bg=PANEL)
    checked_lbl.pack(side="right", padx=(0, 14))

    # Launch row
    launch_row = tk.Frame(pad_f, bg=BG)
    launch_row.pack(fill="x", pady=(0, 12))
    btn_start = RoundedButton(launch_row, "▶  MiniCut Normal", None, CYAN, CYAN_HI,
                               fg="#042024", w=230, h=46, radius=14, font_size=12)
    btn_start.pack(side="left")
    btn_debug = RoundedButton(launch_row, "MiniCut DEBUG", None, BLUE, BLUE_HI,
                               fg="#0a1430", w=200, h=46, radius=14, font_size=12)
    btn_debug.pack(side="left", padx=(10,0))
    btn_web = RoundedButton(launch_row, "🌐  Official Site", None, PURPLE, PURPLE_HI,
                             fg="#1a0a30", w=180, h=46, radius=14, font_size=12)
    btn_web.pack(side="left", padx=(10,0))
    icon_bar = tk.Frame(launch_row, bg=BG)
    icon_bar.pack(side="right")
    btn_refresh_icon   = IconButton(icon_bar, "⟳", None)
    btn_refresh_icon.pack(side="left", padx=(0,6))
    btn_openfolder_icon = IconButton(icon_bar, "⤴", None)
    btn_openfolder_icon.pack(side="left")

    # Smart update banner
    banner = RoundedPanel(pad_f, radius=14, pad=14, fill=PANEL, height=78)
    banner.pack(fill="x", pady=(0, 12))
    btn_smart = RoundedButton(banner.inner, "⚡  Smart Update", None, GREEN, GREEN_HI,
                               fg="#042a0f", w=210, h=46, radius=14, font_size=12)
    btn_smart.pack(side="right")
    banner_txt = tk.Frame(banner.inner, bg=PANEL)
    banner_txt.pack(side="left", fill="x", expand=True)
    banner_title = tk.Label(banner_txt, text="Checking updates…", font=(fam, 13, "bold"),
                             fg=TEXT, bg=PANEL, anchor="w")
    banner_title.pack(fill="x")
    banner_sub = tk.Label(banner_txt, text="", font=(fam, 9), fg=SUBTEXT, bg=PANEL,
                           anchor="w", justify="left")
    banner_sub.pack(fill="x")

    # Bottom (always visible)
    bottom = tk.Frame(pad_f, bg=BG)
    bottom.pack(side="bottom", fill="x")
    prog = ProgressBar(bottom, height=6)
    prog.pack(fill="x", pady=(10, 0))
    actions = tk.Frame(bottom, bg=BG)
    actions.pack(fill="x", pady=(8, 0))
    status_lbl = tk.Label(actions, text="Ready", font=(fam, 9), fg=SUBTEXT, bg=BG)
    status_lbl.pack(side="right")
    btn_install_one = RoundedButton(actions, "Install Selected", None, GREEN, GREEN_HI,
                                    fg="#042a0f", w=170, h=42, radius=12, font_size=10)
    btn_install_one.pack(side="left")
    btn_undo = RoundedButton(actions, "Undo Last Update", None, ORANGE, ORANGE_HI,
                              fg="#301a00", w=210, h=42, radius=12, font_size=10)
    btn_undo.pack(side="left", padx=10)

    # Middle split
    mid = tk.Frame(pad_f, bg=BG)
    mid.pack(fill="both", expand=True)
    mid.columnconfigure(0, weight=5, uniform="c")
    mid.columnconfigure(1, weight=6, uniform="c")
    mid.rowconfigure(0, weight=1)

    list_panel = RoundedPanel(mid, radius=16, pad=12, fill=PANEL)
    list_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
    right = tk.Frame(mid, bg=BG)
    right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
    right.rowconfigure(0, weight=3); right.rowconfigure(1, weight=2)
    right.columnconfigure(0, weight=1)
    detail_panel = RoundedPanel(right, radius=16, pad=12, fill=PANEL)
    detail_panel.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
    log_panel = RoundedPanel(right, radius=16, pad=12, fill=PANEL)
    log_panel.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

    # Patch list header
    head = tk.Frame(list_panel.inner, bg=PANEL)
    head.pack(fill="x", pady=(0, 6))
    tk.Label(head, text="Updates  ·  newest first", font=(fam, 10, "bold"), fg=TEXT, bg=PANEL).pack(side="left")
    show_lbl = tk.Label(head, text="", font=(fam, 9), fg=SUBTEXT, bg=PANEL, cursor="hand2")
    show_lbl.pack(side="right")

    def on_pick(path):
        state["selected"] = path
        state["new_names"].discard(os.path.basename(path))
        render_list(); render_details()

    plist = PatchList(list_panel.inner, on_pick)
    plist.pack(fill="both", expand=True)

    # Detail panel
    tk.Label(detail_panel.inner, text="Details", font=(fam, 10, "bold"), fg=TEXT, bg=PANEL).pack(anchor="w")
    dwrap = tk.Frame(detail_panel.inner, bg=PANEL)
    dwrap.pack(fill="both", expand=True, pady=(8,0))
    dtext = tk.Text(dwrap, wrap="word", font=(fam, 10), bg=PANEL_HI, fg=TEXT, relief="flat",
                    padx=12, pady=8, state="disabled", cursor="arrow", highlightthickness=0)
    dvsb = ttk.Scrollbar(dwrap, orient="vertical", command=dtext.yview)
    dtext.configure(yscrollcommand=dvsb.set)
    dvsb.pack(side="right", fill="y"); dtext.pack(side="left", fill="both", expand=True)
    dtext.tag_configure("h1",   font=(fam, 13, "bold"), foreground=TEXT,    spacing3=2)
    dtext.tag_configure("file", font=("Consolas", 9),   foreground=SUBTEXT, spacing3=6)
    dtext.tag_configure("chip", font=(fam, 10, "bold"))
    dtext.tag_configure("why",  font=(fam, 10),         foreground=TEXT,    spacing1=4, spacing3=4)
    dtext.tag_configure("sec",  font=(fam, 10, "bold"), foreground=CYAN,    spacing1=10, spacing3=2)
    dtext.tag_configure("body", font=(fam, 9),          foreground=SUBTEXT, lmargin1=6, lmargin2=20, spacing1=2, spacing3=2)
    dtext.tag_configure("mono", font=("Consolas", 9),   foreground=SUBTEXT, lmargin1=6, lmargin2=6)

    # Log panel
    tk.Label(log_panel.inner, text="Log", font=(fam, 10, "bold"), fg=TEXT, bg=PANEL).pack(anchor="w")
    logbox = tk.Text(log_panel.inner, wrap="word", font=("Consolas", 9), bg=PANEL_HI, fg=TEXT,
                     insertbackground=TEXT, relief="flat", padx=8, pady=8, highlightthickness=0)
    logbox.pack(fill="both", expand=True, pady=(8,0))
    logbox.tag_configure("err",  foreground=RED)
    logbox.tag_configure("ok",   foreground=GREEN_HI)
    logbox.tag_configure("info", foreground=CYAN)

    # ── behaviour ──
    def log(msg, kind=None): q.put((kind or "line", msg))
    def result(): return state["result"]

    def selected_item():
        r = result()
        if not r or not state["selected"]: return None
        for it in r["items"]:
            if it["patch"].path == state["selected"]: return it
        return None

    def visible_items():
        r = result()
        if not r: return []
        if state["show_installed"]: return r["items"]
        return [it for it in r["items"]
                if it["status"] not in ("installed","included") or it["patch"].path == state["selected"]]

    def render_list():
        plist.set_items(visible_items(), state["selected"], state["new_names"])
        show_lbl.configure(text=("☑ Show installed" if state["show_installed"] else "☐ Show installed"))

    def render_details():
        it = selected_item()
        dtext.configure(state="normal"); dtext.delete("1.0","end")
        if not it:
            dtext.insert("end", "Pick an update on the left to see its details.\n", ("body",))
            dtext.configure(state="disabled"); return
        p, st = it["patch"], it["status"]
        chip, col = STATUS_STYLE.get(st, (st, TEXT))
        dtext.tag_configure("chip", foreground=col)
        dtext.insert("end", "%s  —  %s\n" % (p.label, nice_title(p)), ("h1",))
        dtext.insert("end", p.name + "\n", ("file",))
        dtext.insert("end", chip + "\n", ("chip",))
        dtext.insert("end", it["reason"] + "\n", ("why",))
        r = result()
        if it["plan"]:
            total = len(r["plan"])
            needs = ", ".join(n.label for n in it["needs"])
            dtext.insert("end", "Install step %d of %d%s\n" % (
                it["plan"], total, ("  ·  needs "+needs) if needs else ""), ("why",))
        if st == "conflict":
            dtext.insert("end", "\nTo force-install (files are backed up first):\n", ("body",))
            dtext.insert("end", 'python "Patch\\%s" --force\n' % p.name, ("mono",))
        if p.body:
            dtext.insert("end", "What changed\n", ("sec",))
            dtext.insert("end", p.body + "\n", ("body",))
        if p.files:
            unique_rels = list(dict.fromkeys(f[0] for f in p.files))
            dtext.insert("end", "Files (%d)\n" % len(unique_rels), ("sec",))
            shown = unique_rels[:14]
            extra = len(unique_rels) - 14
            dtext.insert("end", "\n".join(shown) + ("\n… and %d more" % extra if extra > 0 else "") + "\n", ("mono",))
        dtext.configure(state="disabled"); dtext.yview_moveto(0)

    def render_banner():
        r = result()
        if not r: return
        plan, cnt = r["plan"], r["count"]
        bad = cnt.get("conflict",0) + cnt.get("blocked",0) + cnt.get("error",0)
        if not r["items"]:
            banner_title.configure(text="No update files in the Patch folder", fg=SUBTEXT)
            banner_sub.configure(text="Drop apply_*.py files into the Patch folder — the list refreshes by itself.")
        elif plan:
            names = [p.label for p in plan]
            order = " → ".join(names) if len(names) <= 6 else " → ".join(names[:3]+["…"]+names[-2:])
            banner_title.configure(text="%d update%s ready to install" % (len(plan), "" if len(plan)==1 else "s"), fg=GREEN_HI)
            banner_sub.configure(text="Smart order:  "+order + ("      ·  %d need attention" % bad if bad else ""))
        elif bad:
            banner_title.configure(text="%d update%s need attention" % (bad, "" if bad==1 else "s"), fg=ORANGE_HI)
            first = next((it for it in r["items"] if it["status"] in ("conflict","blocked","error")), None)
            banner_sub.configure(text=("%s: %s" % (first["patch"].label, first["reason"])) if first else "")
        else:
            banner_title.configure(text="You're up to date  ✓", fg=GREEN_HI)
            banner_sub.configure(text="Current: %s   ·   %d update files checked" % (r["current"] or "—", len(r["items"])))
        banner_sub.configure(wraplength=max(300, banner.winfo_width()-300))
        btn_smart.set_text("⚡  Smart Update" + (" (%d)" % len(plan) if plan else ""))

    def render_header():
        r = result()
        current_lbl.configure(text="Current: " + ((r and r["current"]) or "—"))
        lb = last_backup_label()
        btn_undo.set_text("Undo Last Update" + (" (%s)" % lb if lb and len(lb) < 14 else ""))
        auto_lbl.configure(text="● Auto ON" if state["auto"] else "○ Auto OFF",
                           fg=GREEN_HI if state["auto"] else SUBTEXT)
        if state["checked"]: checked_lbl.configure(text="checked " + state["checked"])

    def update_buttons():
        r = result(); idle = not busy["v"]
        for b in (btn_start, btn_debug, btn_web, btn_refresh_icon, btn_openfolder_icon):
            b.set_enabled(idle)
        btn_smart.set_enabled(idle and bool(r and r["plan"]) and not state["analyzing"])
        it = selected_item()
        can_one = bool(idle and r and it and plan_for(r, it["patch"]) and not state["analyzing"])
        btn_install_one.set_enabled(can_one)
        btn_undo.set_enabled(idle and bool(list_backups()))

    def set_busy(v):
        busy["v"] = v
        if v: prog.start(); status_lbl.configure(text="Working...", fg=ORANGE_HI)
        else: prog.stop(); status_lbl.configure(text="Ready", fg=SUBTEXT)
        update_buttons()

    def apply_result(res, sig, silent):
        state["analyzing"] = False; state["sig"] = sig; state["result"] = res
        state["checked"] = time.strftime("%H:%M:%S")
        names = {it["patch"].name for it in res["items"]}
        fresh = names - state["known"]
        if state["known"] and fresh:
            for it in res["items"]:
                if it["patch"].name in fresh:
                    state["new_names"].add(it["patch"].name)
                    log("New file: %s  [%s]" % (it["patch"].name,
                        STATUS_STYLE.get(it["status"], (it["status"],))[0]), "info")
        for n in sorted(state["known"] - names): log("Removed: " + n, "info")
        state["known"] = names
        if state["selected"] not in {it["patch"].path for it in res["items"]}:
            first = next((it for it in res["items"] if it["plan"]), None) or (res["items"][0] if res["items"] else None)
            state["selected"] = first["patch"].path if first else None
        render_list(); render_details(); render_banner(); render_header(); update_buttons()
        if not busy["v"]: status_lbl.configure(text="Ready", fg=SUBTEXT)
        if state["again"]: state["again"] = False; refresh(silent=True)

    def refresh(silent=False):
        if state["analyzing"]: state["again"] = True; return
        state["analyzing"] = True
        if not silent: status_lbl.configure(text="Checking…", fg=ORANGE_HI)
        update_buttons()
        def work():
            try:
                res = analyze(); sig = folder_signature()
                q.put(("analysis", res, sig, silent))
            except Exception as ex:
                q.put(("analysis_fail", repr(ex)))
        threading.Thread(target=work, daemon=True).start()

    def poll():
        try:
            if state["auto"] and not busy["v"] and not state["analyzing"]:
                if folder_signature() != state["sig"]: refresh(silent=True)
        except Exception: pass
        win.after(2000, poll)

    def run_bg(fn):
        def work():
            try: fn()
            except Exception as ex: log("ERROR: %r" % (ex,), "err")
            finally: q.put(("done", None))
        threading.Thread(target=work, daemon=True).start(); set_busy(True)

    def confirm(text):
        return messagebox.askokcancel("MiniCut",
            "Close MiniCut before changing program files.\n\n" + text + "\n\nContinue?")

    def order_text(items):
        lines = ["  %d.  %s" % (i+1, p.label) for i, p in enumerate(items[:12])]
        if len(items) > 12: lines.append("  … and %d more" % (len(items)-12))
        return "\n".join(lines)

    def do_install(items):
        if not items: return
        if not confirm("Install %d update%s in this order:\n%s" % (
                len(items), "" if len(items)==1 else "s", order_text(items))): return
        def work():
            py = python_for_minicut(); ok_all = True
            for i, p in enumerate(items):
                log("== [%d/%d] Installing %s" % (i+1, len(items), p.name), "info")
                ok = install_patch(p, py, log)
                log("== " + ("done" if ok else "FAILED") + ": " + p.label + "\n", "ok" if ok else "err")
                if not ok: ok_all = False; break
            if ok_all: log("All updates installed. Start MiniCut as usual.", "ok")
            state["after_done"] = "refresh"
        run_bg(work)

    def do_smart():
        r = result()
        if r and r["plan"]: do_install(list(r["plan"]))

    def do_one():
        r, it = result(), selected_item()
        if r and it: do_install(plan_for(r, it["patch"]))

    def do_undo():
        lb = last_backup_label()
        if not confirm("Undo the last installed update%s.\nOnly that update's files are restored." %
                       (" (%s)" % lb if lb else "")): return
        def work(): undo_last(log); state["after_done"] = "refresh"
        run_bg(work)

    def do_start(debug=False):
        try: log(start_minicut(debug=debug))
        except Exception as ex: messagebox.showerror("MiniCut", "Could not start MiniCut:\n%s" % ex)

    def do_website():
        webbrowser.open(WEBSITE)
        log("Opened: " + WEBSITE, "info")

    def toggle_auto(_e=None):
        state["auto"] = not state["auto"]; render_header()
        if state["auto"]: refresh(silent=True)

    def toggle_installed(_e=None):
        state["show_installed"] = not state["show_installed"]; render_list()

    def _open_folder(p):
        try:
            if IS_WIN: os.startfile(p)
            else: subprocess.Popen(["xdg-open", p])
        except Exception as ex: messagebox.showinfo("MiniCut", str(ex))

    btn_start.command          = lambda: do_start(False)
    btn_debug.command          = lambda: do_start(True)
    btn_web.command            = do_website
    btn_smart.command          = do_smart
    btn_install_one.command    = do_one
    btn_undo.command           = do_undo
    btn_refresh_icon.command   = lambda: refresh()
    btn_openfolder_icon.command= lambda: (patch_files_on_disk(), _open_folder(PATCH_DIR))
    auto_lbl.bind("<Button-1>",      toggle_auto)
    show_lbl.bind("<Button-1>",      toggle_installed)

    def drain():
        pending = []
        try:
            while True: pending.append(q.get_nowait())
        except queue.Empty: pass
        for m in pending:
            kind = m[0]
            if kind == "analysis": apply_result(m[1], m[2], m[3])
            elif kind == "analysis_fail":
                state["analyzing"] = False
                logbox.insert("end", "Could not read updates: %s\n" % m[1], "err")
                logbox.see("end"); update_buttons()
            elif kind == "done":
                set_busy(False)
                if state["after_done"] == "refresh": state["after_done"] = None; refresh()
            elif kind in ("err","ok","info"):
                logbox.insert("end", str(m[1])+"\n", kind); logbox.see("end")
            else:
                logbox.insert("end", str(m[1])+"\n"); logbox.see("end")
        win.after(100, drain)

    patch_files_on_disk()
    render_header()
    log("MiniCut Launcher ready. Drop apply_*.py files into the Patch folder.")
    drain(); refresh(); poll()
    win.mainloop()
    try: bg_canvas.stop()
    except Exception: pass


# ─────────────────────────── CLI ───────────────────────────
def run_cli(args):
    py = python_for_minicut()
    def log(m): print(m, flush=True)
    cmd = args[0] if args else "status"
    if cmd in ("status","plan"):
        r = analyze()
        for it in r["items"]:
            print("%-14s %-10s %s" % (it["patch"].label, it["status"],
                                       ("step %d" % it["plan"]) if it["plan"] else ""))
        print("current:", r["current"], "| order:",
              " -> ".join(p.label for p in r["plan"]) or "(nothing)")
    elif cmd == "install":
        r = analyze()
        if not r["plan"]: log("Nothing to install."); return 0
        for p in r["plan"]:
            log("== installing " + p.name)
            if not install_patch(p, py, log): log("FAILED"); return 1
    elif cmd == "undo": return 0 if undo_last(log) else 1
    elif cmd == "start": print(start_minicut(debug="--debug" in args))
    return 0


if __name__ == "__main__":
    if "--cli" in sys.argv:
        sys.exit(run_cli(sys.argv[sys.argv.index("--cli")+1:]))
    run_gui()
