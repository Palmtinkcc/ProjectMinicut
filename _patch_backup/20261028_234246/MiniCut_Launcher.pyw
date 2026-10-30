#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiniCut Launcher  (smart update edition)
========================================
Put this file in the MiniCut folder (next to file.py). Put the update files (apply_*.py) in the folder  Patch/  (it is
created for you). Then double-click this launcher.

  * Start MiniCut (Normal / Debug)   opens the program (uses the .venv the program already uses)
  * Smart Update                     works out by itself which updates are missing and in which order they must go,
                                     then installs them one by one (the newest update is shown at the top of the list)
  * Install Selected                 installs the picked update, plus any earlier update it needs first
  * Undo last update                 puts back the files of the most recent update (one step at a time)

How the status is found (works the same after you copy the folder to another computer):
  every update file carries a fingerprint (hash) of the program files it expects and of the files it writes. The launcher
  compares those fingerprints with the files that are really in the folder, so it does not depend on the _patch_backup
  folder or on anything that was stored on the old computer.
      installed   the files are already at this update (or at a newer one)
      ready       the files are exactly what this update expects: it can be installed now
      queued      needs an earlier update first - Smart Update puts it in the right order
      blocked     an earlier update that it needs is not in the Patch folder
      conflict    a file was changed by hand / is not a version that any update knows
      included    a newer update replaces this one (for example 25.3 includes 25 and 25.2)

The list refreshes by itself when you add / remove an update file in the Patch folder.
Close MiniCut before you install or undo an update.

Command line (for testing):  python MiniCut_Launcher.pyw --cli status | plan | install | undo | start
"""
import ast, datetime, hashlib, json, os, re, shutil, subprocess, sys, threading, queue, time

ROOT = os.environ.get("MINICUT_ROOT") or os.path.dirname(os.path.abspath(__file__))
PATCH_DIR = os.path.join(ROOT, "Patch")
BACKUP_DIR = os.path.join(ROOT, "_patch_backup")
IS_WIN = os.name == "nt"
NOWIN = 0x08000000 if IS_WIN else 0          # CREATE_NO_WINDOW
DETACHED = 0x00000008 | 0x00000200 if IS_WIN else 0   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
NEW_CONSOLE = 0x00000010 if IS_WIN else 0    # CREATE_NEW_CONSOLE (debug launch keeps a console window open)


# ───────────────────────── basic helpers ─────────────────────────
def python_for_minicut():
    """The interpreter the program runs with: the .venv that Run_MiniCut.bat creates, else this Python."""
    for cand in (os.path.join(ROOT, ".venv", "Scripts", "python.exe"), os.path.join(ROOT, ".venv", "bin", "python")):
        if os.path.exists(cand): return cand
    exe = sys.executable
    if IS_WIN and os.path.basename(exe).lower() == "pythonw.exe":
        alt = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.exists(alt): return alt
    return exe


def norm_hash(b):
    """Same fingerprint the update files use (line endings do not matter)."""
    return hashlib.sha256(b.replace(b"\r\n", b"\n")).hexdigest()


def path_of(rel): return os.path.join(ROOT, *rel.split("/"))


def _write_readme():
    try:
        with open(os.path.join(PATCH_DIR, "README.txt"), "w", encoding="utf-8") as f:
            f.write("Put the update files here (apply_*.py). The MiniCut Launcher lists them (newest first) and installs\n"
                    "them in the right order. Do not rename them. The list refreshes by itself.\n")
    except OSError: pass


def patch_files_on_disk():
    """Update files in the Patch folder (unsorted paths)."""
    if not os.path.isdir(PATCH_DIR): os.makedirs(PATCH_DIR, exist_ok=True); _write_readme()
    return [os.path.join(PATCH_DIR, n) for n in os.listdir(PATCH_DIR)
            if n.lower().startswith("apply_") and n.lower().endswith(".py")]


def version_key(name, mtime=0.0):
    """Where an update sits in the history, from its file name. Only used for display order and tie-breaks:
    the real install order comes from the file fingerprints."""
    low = name.lower()
    if "effects" in low: return (0, 0, 0, 0)
    m = re.search(r"perf_gpu_patch(?:_v(\d+))?", low)
    if m: return (1, int(m.group(1) or 1), 0, 0)
    m = re.match(r"apply_(\d+)(?:\.(\d+))?", low)
    if m: return (2, int(m.group(1)), int(m.group(2) or 0), 0)
    m = re.search(r"_v(\d+)", low)
    if m: return (2, int(m.group(1)), 0, 0)
    return (3, 0, 0, mtime)                      # unknown name: treated as the newest, ordered by file date


def short_label(name):
    low = name.lower()
    if "effects" in low: return "Effects"
    m = re.search(r"perf_gpu_patch(?:_v(\d+))?", low)
    if m: return "Perf/GPU v%s" % (m.group(1) or "1")
    m = re.match(r"apply_(\d+(?:\.\d+)?)", low)
    if m: return "Patch " + m.group(1)
    return os.path.splitext(name)[0]


# ───────────────────────── reading an update file (static, nothing is executed) ─────────────────────────
class Patch:
    def __init__(self, path):
        self.path = path; self.name = os.path.basename(path); self.label = short_label(self.name)
        st = os.stat(path); self.mtime = st.st_mtime; self.size = st.st_size
        self.key = version_key(self.name, self.mtime)
        self.pname = None; self.title = self.name; self.body = ""
        self.files = []          # (rel, base_hash|None, new_hash, mode)   mode: edit | new | soft
        self.error = None


def _literal(node):
    try: return ast.literal_eval(node)
    except Exception: return None


def read_patch_notes(src, fallback):
    """Title + bullet list of changes from the update file's own docstring."""
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
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            k = n.targets[0].id
            if k in ("EDITS", "REPLACE", "NEW_FILES", "FILES", "PATCH_NAME"): vals[k] = _literal(n.value)
    p.pname = vals.get("PATCH_NAME") if isinstance(vals.get("PATCH_NAME"), str) else None
    try:
        for rel, i in (vals.get("EDITS") or {}).items(): p.files.append((rel, i["base"], i["new"], "edit"))
        for rel, i in (vals.get("REPLACE") or {}).items(): p.files.append((rel, i["base"], i["new"], "edit"))
        for rel, i in (vals.get("FILES") or {}).items():
            soft = bool(i.get("soft")) or i.get("base") is None
            p.files.append((rel, i.get("base"), i["new"], "soft" if soft else "edit"))
        for rel, s in (vals.get("NEW_FILES") or {}).items():
            p.files.append((rel, None, hashlib.sha256(s.replace("\r\n", "\n").encode("utf-8")).hexdigest(), "new"))
    except Exception as ex:
        p.error = "unknown update format: %r" % (ex,)
    if not p.files and not p.error: p.error = "no file list found in this update"
    if "effects" in p.name.lower() and not p.pname: p.pname = "effects"
    return p


_PATCH_CACHE = {}


def load_patches():
    """All readable update files, cached by (file, date, size) so a refresh only reads what is new."""
    out = []
    for path in patch_files_on_disk():
        try: st = os.stat(path)
        except OSError: continue
        sig = (path, st.st_mtime_ns, st.st_size)
        p = _PATCH_CACHE.get(path)
        if p is None or getattr(p, "_sig", None) != sig:
            p = load_patch(path); p._sig = sig; _PATCH_CACHE[path] = p
        out.append(p)
    for k in [k for k in _PATCH_CACHE if k not in {x.path for x in out}]: _PATCH_CACHE.pop(k, None)
    return sorted(out, key=lambda p: (p.key, p.name))


_HASH_CACHE = {}


def disk_hashes(rels):
    """rel path -> fingerprint of the file now in the folder (None = file does not exist)."""
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


# ───────────────────────── the smart part: where is every file in the history of updates? ─────────────────────────
class Graph:
    """For every program file: which fingerprint can follow which (base -> new), as told by all the update files."""
    def __init__(self, patches):
        self.parents = {}                      # rel -> {new_hash: {base_hash, ...}}
        self.producers = {}                    # (rel, new_hash) -> [patch, ...]
        for p in patches:
            if p.error: continue
            for rel, b, n, mode in p.files:
                self.parents.setdefault(rel, {}).setdefault(n, set())
                if b: self.parents[rel][n].add(b)
                self.producers.setdefault((rel, n), []).append(p)
        self.known = {}                        # rel -> every fingerprint that any update mentions
        for rel, d in self.parents.items():
            self.known[rel] = set(d) | {b for bs in d.values() for b in bs}
        self._anc = {}

    def ancestors(self, rel, h):
        """Every fingerprint that this file went through before it became h."""
        k = (rel, h)
        if k in self._anc: return self._anc[k]
        seen, stack = set(), [h]; par = self.parents.get(rel, {})
        while stack:
            x = stack.pop()
            for b in par.get(x, ()):
                if b not in seen: seen.add(b); stack.append(b)
        self._anc[k] = seen
        return seen


def file_state(G, rel, b, n, mode, c):
    """new | ready | sibling | waiting | missing | conflict   for one file of one update, given the file's fingerprint c."""
    if c is not None and c == n: return "new"
    A = G.ancestors(rel, c) if c is not None else set()
    if n in A: return "new"                          # a newer update is already on top of this one
    if mode == "soft": return "ready"
    if mode == "new": return "ready" if c is None else "conflict"
    if c is None: return "waiting" if (rel, b) in G.producers else "missing"      # created by an earlier update
    if c == b: return "ready"
    if b in A: return "sibling"                      # another update that started from the same file replaced it
    if c in G.ancestors(rel, b): return "waiting"    # the file is older than this update expects
    if c in G.known.get(rel, ()) and (rel, b) not in G.producers: return "gap"   # an update in between is not in the folder
    return "conflict"


def judge(G, p, cur):
    """(status, reason) of one update against the file state `cur` (rel -> fingerprint)."""
    sts = [(rel, file_state(G, rel, b, n, mode, cur.get(rel))) for rel, b, n, mode in p.files]
    kinds = {s for _, s in sts}
    names = lambda k: ", ".join(r.split("/")[-1] for r, s in sts if s == k)
    if kinds <= {"new"}: return "installed", "All files of this update are in place."
    if kinds <= {"new", "sibling"}: return "included", "A newer update that starts from the same files has replaced this one."
    if "conflict" in kinds: return "conflict", "Not a known version (edited by hand?): " + names("conflict")
    if "gap" in kinds: return "blocked", "An earlier update that this one needs is not in the Patch folder (files: " + names("gap") + ")"
    if "missing" in kinds: return "conflict", "File missing: " + names("missing")
    if "sibling" in kinds: return "conflict", "Mixed versions: " + names("sibling")
    if "waiting" in kinds: return "waiting", "Needs an earlier update first: " + names("waiting")
    return "ready", "Files are exactly what this update expects."


def analyze(patches=None, hashes=None):
    """Work out the status of every update, and the install order for the ones that are missing.
    Returns dict: items (list, newest first), plan (list of Patch in install order), current (label), summary counts."""
    patches = load_patches() if patches is None else patches
    good = [p for p in patches if not p.error]
    G = Graph(good)
    rels = sorted({rel for p in good for rel, *_ in p.files})
    real = disk_hashes(rels) if hashes is None else dict(hashes)
    info = {}
    for p in patches:
        if p.error: info[p.path] = {"status": "error", "reason": p.error, "plan": None, "needs": []}
        else:
            st, why = judge(G, p, real); info[p.path] = {"status": st, "reason": why, "plan": None, "needs": []}

    # --- simulate the installation: apply what can be applied, again and again, until nothing more can ---
    cur = dict(real); producer_of = {}; plan = []
    pending = [p for p in good if info[p.path]["status"] in ("ready", "waiting")]
    while pending:
        cands = [p for p in pending if judge(G, p, cur)[0] == "ready"]
        if not cands: break
        # rivals: updates that start from the same file version but write different things (25 / 25.2 / 25.3).
        # Only the best one is installed; the others are "included".
        group = {}
        for p in cands:
            for rel, b, n, mode in p.files:
                if mode == "edit" and cur.get(rel) == b: group.setdefault((rel, b), []).append(p)
        loser = {}
        for (_rel, _b), ps in group.items():
            if len(ps) < 2: continue
            def score(q):
                new = {(r, h) for r, _b2, h, _m in q.files}
                used = sum(1 for o in good if o is not q for r, b2, _h, _m in o.files if (r, b2) in new)
                return (used, len(q.files), q.key)
            best = max(ps, key=score)
            for q in ps:
                if q is not best and q.path not in loser: loser[q.path] = best
        for lp, best in loser.items():
            q = next(x for x in cands if x.path == lp)
            if q in pending: pending.remove(q)
            info[lp].update(status="included", reason="Replaced by %s, which starts from the same files and includes it." % best.label)
        cands = [p for p in cands if p.path not in loser]
        if not cands: continue
        p = min(cands, key=lambda q: (q.key, q.name))
        needs = []
        for rel, b, n, mode in p.files:
            if mode == "edit" and rel in producer_of and producer_of[rel] is not p:
                if producer_of[rel] not in needs: needs.append(producer_of[rel])
        for rel, b, n, mode in p.files: cur[rel] = n; producer_of[rel] = p
        plan.append(p); pending.remove(p); info[p.path]["plan"] = len(plan); info[p.path]["needs"] = needs
    for p in pending:                                              # could not be placed in the plan
        rec = info[p.path]
        if rec["status"] == "waiting":
            rec["status"] = "blocked"
            rec["reason"] = "An earlier update that this one needs is not in the Patch folder. " + rec["reason"].split(": ", 1)[-1]
    for p in plan:
        rec = info[p.path]
        if rec["status"] == "waiting": rec["status"] = "queued"; rec["reason"] = "Will be installed after: " + (", ".join(q.label for q in rec["needs"]) or "earlier updates")

    items = []
    for p in sorted(patches, key=lambda q: (q.key, q.name), reverse=True):      # newest first
        r = info[p.path]; items.append({"patch": p, **r})
    done = [it["patch"] for it in items if it["status"] in ("installed", "included")]
    current = max(done, key=lambda q: (q.key, q.name)).label if done else None
    count = {}
    for it in items: count[it["status"]] = count.get(it["status"], 0) + 1
    return {"items": items, "plan": plan, "current": current, "count": count, "final": cur, "real": real, "graph": G}


def plan_for(result, patch):
    """The updates to install so that `patch` can be installed: the ones it needs (and what they need), then itself."""
    rec = {it["patch"].path: it for it in result["items"]}
    if rec[patch.path]["plan"] is None: return []
    need, stack = set(), [patch]
    while stack:
        q = stack.pop()
        if q.path in need: continue
        need.add(q.path); stack.extend(rec[q.path]["needs"])
    return [p for p in result["plan"] if p.path in need]


# ───────────────────────── installing / undoing ─────────────────────────
_last_stamp = {"s": 0}


def _wait_new_second():
    """Each install names its backup folder by the second: make sure two installs never share one."""
    while int(time.time()) == _last_stamp["s"]: time.sleep(0.1)


def _run_patch(patch_path, args, py, timeout=900):
    """Run an update file as if it were in the MiniCut folder (copy it there for the run, then delete the copy)."""
    tmp = os.path.join(ROOT, "_launcher_run_" + os.path.basename(patch_path))
    shutil.copy2(patch_path, tmp)
    try:
        r = subprocess.run([py, tmp, "--no-pause"] + list(args), cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, creationflags=NOWIN)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    finally:
        try: os.remove(tmp)
        except OSError: pass


def install_patch(patch, py, log):
    before = set(os.listdir(BACKUP_DIR)) if os.path.isdir(BACKUP_DIR) else set()
    _wait_new_second()
    _last_stamp["s"] = int(time.time())
    rc, out = _run_patch(patch.path, [], py)
    log(out.strip() or "(no output)")
    if os.path.isdir(BACKUP_DIR):                          # remember which update file made the newest backup (for Undo)
        for d in set(os.listdir(BACKUP_DIR)) - before:
            try:
                with open(os.path.join(BACKUP_DIR, d, "LAUNCHER.json"), "w", encoding="utf-8") as f:
                    json.dump({"file": patch.name, "label": patch.label}, f)
            except OSError: pass
    return rc == 0


def list_backups():
    """Installed updates that can still be undone, newest first (undone ones are marked MANIFEST.undone.json)."""
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
    """Put back the files of the newest installed update. Only the newest one can be undone, so the order stays right."""
    items = list_backups()
    if not items: log("Nothing to undo."); return False
    stamp, man = items[0]
    bdir = os.path.join(BACKUP_DIR, stamp)
    for rel in man.get("replaced", []):
        src = os.path.join(bdir, *rel.split("/")); dst = path_of(rel)
        shutil.copy2(src, dst); log("restored  " + rel)
    for rel in man.get("created", []):
        p = path_of(rel)
        if os.path.exists(p): os.remove(p); log("removed   " + rel)
    os.rename(os.path.join(bdir, "MANIFEST.json"), os.path.join(bdir, "MANIFEST.undone.json"))
    log("Undone: %s (%s)" % (man["_launcher"].get("label") or man.get("patch", "?"), stamp))
    return True


def start_minicut(debug=False):
    """Start MiniCut. With the .venv from Run_MiniCut.bat it starts directly (no package check, so it is fast).
    debug=True keeps a console window open so you can see MiniCut's own output while it runs."""
    venv_py = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
    flags = (NEW_CONSOLE if debug else DETACHED) if IS_WIN else 0
    close = not debug
    if os.path.exists(venv_py) and os.path.exists(os.path.join(ROOT, "file.py")):
        subprocess.Popen([venv_py, "file.py"], cwd=ROOT, creationflags=flags, close_fds=close)
        return "started MiniCut (.venv)" + (" [debug console]" if debug else "")
    if IS_WIN and os.path.exists(os.path.join(ROOT, "Run_MiniCut.bat")):
        subprocess.Popen(["cmd", "/c", "Run_MiniCut.bat"], cwd=ROOT, creationflags=0x00000010)   # new console
        return "started Run_MiniCut.bat (it creates the .venv the first time)"
    subprocess.Popen([sys.executable, "file.py"], cwd=ROOT, close_fds=close, creationflags=flags)
    return "started with " + sys.executable + (" [debug console]" if debug else "")


def folder_signature():
    """Cheap fingerprint of the Patch folder + the program files the updates touch. Changes -> the list refreshes itself."""
    sig = []
    try:
        for n in sorted(os.listdir(PATCH_DIR)):
            if n.lower().startswith("apply_") and n.lower().endswith(".py"):
                st = os.stat(os.path.join(PATCH_DIR, n)); sig.append((n, st.st_mtime_ns, st.st_size))
    except OSError: sig.append("nofolder")
    rels = {rel for p in _PATCH_CACHE.values() if not p.error for rel, *_ in p.files}
    for rel in sorted(rels):
        try: st = os.stat(path_of(rel)); sig.append((rel, st.st_mtime_ns, st.st_size))
        except OSError: sig.append((rel, None))
    return hash(tuple(sig))


# ───────────────────────── window ─────────────────────────
BG        = "#07080a"
PANEL     = "#17191c"
PANEL_HI  = "#1e2024"
ROW_SEL   = "#18323a"
BORDER    = "#2a2d31"
TEXT      = "#e8e9eb"
SUBTEXT   = "#8a8f98"
CYAN      = "#22d3ee"
CYAN_HI   = "#5ee4f7"
BLUE      = "#3b82f6"
BLUE_HI   = "#6ea2ff"
ORANGE    = "#f59e0b"
ORANGE_HI = "#ffb73d"
GREEN     = "#22c55e"
GREEN_HI  = "#54e085"
RED       = "#ef4444"
GRAY_BTN  = "#2b2e33"
GRAY_HI   = "#383c42"

# status -> (chip text, colour)
STATUS_STYLE = {
    "ready":     ("Ready",      GREEN_HI),
    "queued":    ("Queued",     BLUE_HI),
    "installed": ("✓ Installed", "#5f7a6a"),
    "included":  ("Included",   SUBTEXT),
    "blocked":   ("Blocked",    ORANGE_HI),
    "conflict":  ("Conflict",   RED),
    "error":     ("Error",      RED),
}


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def lerp_color(c1, c2, t):
    a, b = _hex_to_rgb(c1), _hex_to_rgb(c2)
    return _rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


def nice_title(p):
    """'MiniCut Patch 30: MEDIA FILTER GALLERY ...   (needs patch 29)'  ->  'Media filter gallery ...'"""
    t = p.title or p.name
    t = re.sub(r"^\s*MiniCut\s*(update\s*)?(patch\s*[\d.]*)?\s*[:\-–—]?\s*", "", t, flags=re.I)
    t = re.sub(r"\(\s*needs[^)]*\)", "", t, flags=re.I).strip(" :-–—")
    letters = [c for c in t if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.6: t = t.capitalize()
    return t or p.label


def run_gui():
    import tkinter as tk
    from tkinter import ttk, messagebox
    from tkinter import font as tkfont

    win = tk.Tk()
    win.title("MiniCut Launcher")
    win.geometry("1060x720")
    win.minsize(900, 620)
    win.configure(bg=BG)
    try: win.tk.call("tk", "scaling", 1.15)
    except tk.TclError: pass

    q = queue.Queue()
    busy = {"v": False}
    state = {"result": None, "selected": None, "known": set(), "new_names": set(), "auto": True, "sig": None,
             "analyzing": False, "again": False, "show_installed": True, "after_done": None, "checked": None}

    # ---- true rounded rectangle from 4 quarter-circle arcs + 2 rects ----
    def draw_round_rect(canvas, x1, y1, x2, y2, r, fill, outline="", width=1, tag=None):
        r = max(1, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
        d = 2 * r
        kw = {"tags": tag} if tag else {}
        fill_items = [
            canvas.create_arc(x1, y1, x1 + d, y1 + d, start=90, extent=90, fill=fill, outline=fill, width=0, **kw),
            canvas.create_arc(x2 - d, y1, x2, y1 + d, start=0, extent=90, fill=fill, outline=fill, width=0, **kw),
            canvas.create_arc(x1, y2 - d, x1 + d, y2, start=180, extent=90, fill=fill, outline=fill, width=0, **kw),
            canvas.create_arc(x2 - d, y2 - d, x2, y2, start=270, extent=90, fill=fill, outline=fill, width=0, **kw),
            canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=fill, width=0, **kw),
            canvas.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=fill, width=0, **kw),
        ]
        border_items = []
        if outline and width > 0:
            border_items = [
                canvas.create_arc(x1, y1, x1 + d, y1 + d, start=90, extent=90, style="arc", outline=outline, width=width, **kw),
                canvas.create_arc(x2 - d, y1, x2, y1 + d, start=0, extent=90, style="arc", outline=outline, width=width, **kw),
                canvas.create_arc(x1, y2 - d, x1 + d, y2, start=180, extent=90, style="arc", outline=outline, width=width, **kw),
                canvas.create_arc(x2 - d, y2 - d, x2, y2, start=270, extent=90, style="arc", outline=outline, width=width, **kw),
                canvas.create_line(x1 + r, y1, x2 - r, y1, fill=outline, width=width, **kw),
                canvas.create_line(x1 + r, y2, x2 - r, y2, fill=outline, width=width, **kw),
                canvas.create_line(x1, y1 + r, x1, y2 - r, fill=outline, width=width, **kw),
                canvas.create_line(x2, y1 + r, x2, y2 - r, fill=outline, width=width, **kw),
            ]
        return fill_items, border_items

    # ---- rounded, animated button ----
    class RoundedButton(tk.Canvas):
        def __init__(self, parent, text, command, base, hi, fg="#06161a", w=170, h=40, radius=12, font_size=11, bold=True):
            tk.Canvas.__init__(self, parent, width=w, height=h, bg=parent["bg"], highlightthickness=0, bd=0, cursor="hand2")
            self.command = command
            self.base, self.hi, self.fg = base, hi, fg
            self.w, self.h, self.radius = w, h, radius
            self.enabled = True
            self._cur = base
            self._anim_job = None
            self.fill_items, _ = draw_round_rect(self, 1, 1, w - 1, h - 1, radius, base)
            self.label = self.create_text(w / 2, h / 2, text=text, fill=fg, font=("Segoe UI", font_size, "bold" if bold else "normal"))
            self.bind("<Enter>", self._enter); self.bind("<Leave>", self._leave)
            self.bind("<Button-1>", self._press); self.bind("<ButtonRelease-1>", self._release)

        def set_text(self, text): self.itemconfigure(self.label, text=text)

        def _set_fill(self, color):
            for it in self.fill_items: self.itemconfigure(it, fill=color, outline=color)
            self._cur = color

        def set_enabled(self, v):
            self.enabled = v
            if self._anim_job: self.after_cancel(self._anim_job); self._anim_job = None
            self._set_fill(self.base if v else GRAY_BTN)
            self.itemconfigure(self.label, fill=(self.fg if v else SUBTEXT))
            self.configure(cursor="hand2" if v else "arrow")

        def _animate_to(self, color, steps=8, delay=12):
            if self._anim_job: self.after_cancel(self._anim_job)
            start = self._cur
            def step(i=0):
                self._set_fill(lerp_color(start, color, i / steps))
                if i < steps: self._anim_job = self.after(delay, lambda: step(i + 1))
            step()

        def _enter(self, _e):
            if self.enabled: self._animate_to(self.hi)

        def _leave(self, _e):
            if self.enabled: self._animate_to(self.base)

        def _press(self, _e):
            if self.enabled:
                for it in self.fill_items + [self.label]: self.move(it, 0, 1)

        def _release(self, e):
            if self.enabled:
                for it in self.fill_items + [self.label]: self.move(it, 0, -1)
                if 0 <= e.x <= self.w and 0 <= e.y <= self.h and self.command: self.command()

    class IconButton(RoundedButton):
        def __init__(self, parent, glyph, command, size=34):
            RoundedButton.__init__(self, parent, glyph, command, GRAY_BTN, GRAY_HI, fg=TEXT, w=size, h=size,
                                   radius=size // 2, font_size=13, bold=False)

    # ---- rounded panel: a rounded "card" that embeds a real child frame ----
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
            draw_round_rect(self, 1, 1, w - 1, h - 1, self.radius, self.fill, self.outline, 1, tag="bg")
            self.tag_lower("bg")
            self.coords(self._win, self.pad, self.pad)
            self.itemconfigure(self._win, width=max(1, w - 2 * self.pad), height=max(1, h - 2 * self.pad))

    class ProgressBar(tk.Canvas):
        """Moving bar: only takes space while something is running."""
        def __init__(self, parent, height=6):
            tk.Canvas.__init__(self, parent, height=0, bg=parent["bg"], highlightthickness=0, bd=0)
            self.bar_height = height; self.running = False; self._pos = 0.0
            self.bind("<Configure>", lambda _e: self._draw())

        def _draw(self):
            self.delete("all")
            if not self.running: return
            w, h = self.winfo_width(), self.bar_height
            if w < 4: return
            draw_round_rect(self, 0, 0, w, h, h / 2, BORDER)
            seg = max(40, w * 0.22); x = self._pos * (w + seg) - seg
            draw_round_rect(self, max(0, x), 0, min(w, x + seg), h, h / 2, GREEN)

        def start(self):
            if self.running: return
            self.running = True; self.configure(height=self.bar_height); self._tick()

        def stop(self):
            self.running = False; self.configure(height=0); self.delete("all")

        def _tick(self):
            if not self.running: return
            self._pos = (self._pos + 0.02) % 1.0; self._draw(); self.after(20, self._tick)

    # ---- the update list: one canvas, rounded cards, newest on top ----
    class PatchList(tk.Frame):
        ROW_H, GAP, PAD = 60, 6, 6

        def __init__(self, parent, on_select):
            tk.Frame.__init__(self, parent, bg=PANEL)
            self.on_select = on_select
            self.items, self.selected, self.new_names = [], None, set()
            self.canvas = tk.Canvas(self, bg=PANEL, highlightthickness=0, bd=0)
            self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
            self.canvas.configure(yscrollcommand=self.vsb.set)
            self.vsb.pack(side="right", fill="y"); self.canvas.pack(side="left", fill="both", expand=True)
            self.f_main = tkfont.Font(family="Segoe UI", size=11, weight="bold")
            self.f_sub = tkfont.Font(family="Segoe UI", size=9)
            self.f_chip = tkfont.Font(family="Segoe UI", size=9, weight="bold")
            self._rows = []                       # per row: list of fill items
            self._hover = None
            self.canvas.bind("<Configure>", lambda _e: self.redraw())
            self.canvas.bind("<Button-1>", self._click)
            self.canvas.bind("<Motion>", self._motion)
            self.canvas.bind("<Leave>", lambda _e: self._set_hover(None))
            self.canvas.bind("<Enter>", lambda _e: self.canvas.bind_all("<MouseWheel>", self._wheel))
            self.canvas.bind("<Leave>", self._leave, add="+")

        def _leave(self, _e):
            self._set_hover(None)
            try: self.canvas.unbind_all("<MouseWheel>")
            except tk.TclError: pass

        def _wheel(self, e):
            self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        def set_items(self, items, selected, new_names):
            self.items, self.selected, self.new_names = items, selected, new_names
            self.redraw()

        def _fit(self, text, font, maxw):
            if maxw <= 20 or font.measure(text) <= maxw: return text
            lo, hi = 0, len(text)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if font.measure(text[:mid] + "…") <= maxw: lo = mid
                else: hi = mid - 1
            return text[:lo].rstrip() + "…"

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
                top = self.PAD + i * (self.ROW_H + self.GAP); bot = top + self.ROW_H
                sel = p.path == self.selected
                fills, _ = draw_round_rect(self.canvas, 4, top, w - 8, bot, 12, self._row_fill(i), CYAN if sel else "", 1)
                self._rows.append(fills)
                chip, col = STATUS_STYLE.get(st, (st, TEXT))
                cx = w - 8 - 14
                chip_w = self.f_chip.measure(chip) + 20
                draw_round_rect(self.canvas, cx - chip_w, top + 10, cx, top + 30, 10, lerp_color(PANEL_HI, col, 0.22))
                self.canvas.create_text(cx - chip_w / 2, top + 20, text=chip, fill=col, font=self.f_chip)
                tail_x = cx - chip_w - 10
                if it["plan"]:
                    self.canvas.create_text(cx, top + 43, anchor="e", text="install step %d" % it["plan"], fill=SUBTEXT, font=self.f_sub)
                self.canvas.create_oval(16, top + 14, 24, top + 22, fill=col, outline="")
                label = p.label + ("   NEW" if p.name in self.new_names else "")
                self.canvas.create_text(32, top + 18, anchor="w", text=self._fit(label, self.f_main, tail_x - 36),
                                         fill=TEXT, font=self.f_main)
                self.canvas.create_text(32, top + 42, anchor="w", text=self._fit(nice_title(p), self.f_sub, cx - 40),
                                         fill=SUBTEXT, font=self.f_sub)
                if p.name in self.new_names:
                    pass
            total = self.PAD * 2 + len(self.items) * (self.ROW_H + self.GAP)
            self.canvas.configure(scrollregion=(0, 0, w, total))
            self.canvas.yview_moveto(y0)

        def _index_at(self, y):
            yy = self.canvas.canvasy(y) - self.PAD
            if yy < 0: return None
            i = int(yy // (self.ROW_H + self.GAP))
            return i if 0 <= i < len(self.items) and (yy % (self.ROW_H + self.GAP)) <= self.ROW_H else None

        def _set_hover(self, i):
            if i == self._hover: return
            old, self._hover = self._hover, i
            for idx in (old, i):
                if idx is not None and idx < len(self._rows):
                    for it in self._rows[idx]: self.canvas.itemconfigure(it, fill=self._row_fill(idx), outline=self._row_fill(idx))

        def _motion(self, e):
            i = self._index_at(e.y)
            self._set_hover(i); self.canvas.configure(cursor="hand2" if i is not None else "arrow")

        def _click(self, e):
            i = self._index_at(e.y)
            if i is not None and self.on_select: self.on_select(self.items[i]["patch"].path)

        def scroll_to(self, path):
            for i, it in enumerate(self.items):
                if it["patch"].path == path:
                    total = self.PAD * 2 + len(self.items) * (self.ROW_H + self.GAP)
                    self.canvas.yview_moveto(max(0.0, (self.PAD + i * (self.ROW_H + self.GAP) - 40) / max(1, total)))
                    return

    # ───────────────────────── layout ─────────────────────────
    outer = tk.Frame(win, bg=BG)
    outer.pack(fill="both", expand=True, padx=18, pady=14)

    title_row = tk.Frame(outer, bg=BG)
    title_row.pack(fill="x")
    tk.Label(title_row, text="MINICUT", font=("Segoe UI", 22, "bold"), fg=CYAN, bg=BG).pack(side="left")
    tk.Label(title_row, text="Launcher", font=("Segoe UI", 22), fg=BLUE, bg=BG).pack(side="left", padx=(4, 0))
    current_lbl = tk.Label(title_row, text="Current: —", font=("Segoe UI", 10, "bold"), fg=GREEN_HI, bg=BG)
    current_lbl.pack(side="right")

    # location + auto refresh
    loc_panel = RoundedPanel(outer, radius=10, pad=10, fill=PANEL, height=40)
    loc_panel.pack(fill="x", pady=(8, 12))
    tk.Label(loc_panel.inner, text="Location", font=("Segoe UI", 10, "bold"), fg=TEXT, bg=PANEL).pack(side="left")
    tk.Label(loc_panel.inner, text=ROOT, font=("Segoe UI", 9), fg=SUBTEXT, bg=PANEL).pack(side="left", padx=(10, 0))
    auto_lbl = tk.Label(loc_panel.inner, text="", font=("Segoe UI", 9, "bold"), fg=GREEN_HI, bg=PANEL, cursor="hand2")
    auto_lbl.pack(side="right")
    checked_lbl = tk.Label(loc_panel.inner, text="", font=("Segoe UI", 9), fg=SUBTEXT, bg=PANEL)
    checked_lbl.pack(side="right", padx=(0, 14))

    # launch row
    launch_row = tk.Frame(outer, bg=BG)
    launch_row.pack(fill="x", pady=(0, 12))
    btn_start = RoundedButton(launch_row, "▶  Minicut Normal", None, CYAN, CYAN_HI, fg="#042024", w=230, h=46, radius=14, font_size=12)
    btn_start.pack(side="left")
    btn_debug = RoundedButton(launch_row, "Minicut DEBUG", None, BLUE, BLUE_HI, fg="#0a1430", w=200, h=46, radius=14, font_size=12)
    btn_debug.pack(side="left", padx=(10, 0))
    icon_bar = tk.Frame(launch_row, bg=BG)
    icon_bar.pack(side="right")
    btn_refresh_icon = IconButton(icon_bar, "⟳", None)
    btn_refresh_icon.pack(side="left", padx=(0, 6))
    btn_openfolder_icon = IconButton(icon_bar, "⤴", None)
    btn_openfolder_icon.pack(side="left")

    # smart banner
    banner = RoundedPanel(outer, radius=14, pad=14, fill=PANEL, height=78)
    banner.pack(fill="x", pady=(0, 12))
    btn_smart = RoundedButton(banner.inner, "⚡  Smart Update", None, GREEN, GREEN_HI, fg="#042a0f", w=210, h=46, radius=14, font_size=12)
    btn_smart.pack(side="right")
    banner_txt = tk.Frame(banner.inner, bg=PANEL)
    banner_txt.pack(side="left", fill="x", expand=True)
    banner_title = tk.Label(banner_txt, text="Checking updates…", font=("Segoe UI", 13, "bold"), fg=TEXT, bg=PANEL, anchor="w")
    banner_title.pack(fill="x")
    banner_sub = tk.Label(banner_txt, text="", font=("Segoe UI", 9), fg=SUBTEXT, bg=PANEL, anchor="w", justify="left")
    banner_sub.pack(fill="x")

    # bottom area is packed first (so it never gets pushed out), then the middle expands
    bottom = tk.Frame(outer, bg=BG)
    bottom.pack(side="bottom", fill="x")
    prog = ProgressBar(bottom, height=6)
    prog.pack(fill="x", pady=(10, 0))
    actions = tk.Frame(bottom, bg=BG)
    actions.pack(fill="x", pady=(8, 0))
    status_lbl = tk.Label(actions, text="Ready", font=("Segoe UI", 9), fg=SUBTEXT, bg=BG)
    status_lbl.pack(side="right")
    btn_install_one = RoundedButton(actions, "Install Selected", None, GREEN, GREEN_HI, fg="#042a0f", w=170, h=42, radius=12, font_size=10)
    btn_install_one.pack(side="left")
    btn_undo = RoundedButton(actions, "Undo Last Update", None, ORANGE, ORANGE_HI, fg="#301a00", w=210, h=42, radius=12, font_size=10)
    btn_undo.pack(side="left", padx=10)

    mid = tk.Frame(outer, bg=BG)
    mid.pack(fill="both", expand=True)
    mid.columnconfigure(0, weight=5, uniform="c")
    mid.columnconfigure(1, weight=6, uniform="c")
    mid.rowconfigure(0, weight=1)

    list_panel = RoundedPanel(mid, radius=16, pad=12, fill=PANEL)
    list_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
    right = tk.Frame(mid, bg=BG)
    right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
    right.rowconfigure(0, weight=3); right.rowconfigure(1, weight=2); right.columnconfigure(0, weight=1)
    detail_panel = RoundedPanel(right, radius=16, pad=12, fill=PANEL)
    detail_panel.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
    log_panel = RoundedPanel(right, radius=16, pad=12, fill=PANEL)
    log_panel.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

    head = tk.Frame(list_panel.inner, bg=PANEL)
    head.pack(fill="x", pady=(0, 6))
    tk.Label(head, text="Updates  ·  newest first", font=("Segoe UI", 10, "bold"), fg=TEXT, bg=PANEL).pack(side="left")
    show_lbl = tk.Label(head, text="", font=("Segoe UI", 9), fg=SUBTEXT, bg=PANEL, cursor="hand2")
    show_lbl.pack(side="right")

    def on_pick(path):
        state["selected"] = path
        state["new_names"].discard(os.path.basename(path))
        render_list(); render_details()

    plist = PatchList(list_panel.inner, on_pick)
    plist.pack(fill="both", expand=True)

    tk.Label(detail_panel.inner, text="Details", font=("Segoe UI", 10, "bold"), fg=TEXT, bg=PANEL).pack(anchor="w")
    dwrap = tk.Frame(detail_panel.inner, bg=PANEL)
    dwrap.pack(fill="both", expand=True, pady=(8, 0))
    dtext = tk.Text(dwrap, wrap="word", font=("Segoe UI", 10), bg=PANEL_HI, fg=TEXT, relief="flat", padx=12, pady=8,
                    state="disabled", cursor="arrow", highlightthickness=0)
    dvsb = ttk.Scrollbar(dwrap, orient="vertical", command=dtext.yview)
    dtext.configure(yscrollcommand=dvsb.set)
    dvsb.pack(side="right", fill="y"); dtext.pack(side="left", fill="both", expand=True)
    dtext.tag_configure("h1", font=("Segoe UI", 13, "bold"), foreground=TEXT, spacing3=2)
    dtext.tag_configure("file", font=("Consolas", 9), foreground=SUBTEXT, spacing3=6)
    dtext.tag_configure("chip", font=("Segoe UI", 10, "bold"))
    dtext.tag_configure("why", font=("Segoe UI", 10), foreground=TEXT, spacing1=4, spacing3=4, lmargin1=0, lmargin2=0)
    dtext.tag_configure("sec", font=("Segoe UI", 10, "bold"), foreground=CYAN, spacing1=10, spacing3=2)
    dtext.tag_configure("body", font=("Segoe UI", 9), foreground=SUBTEXT, lmargin1=6, lmargin2=20, spacing1=2, spacing3=2)
    dtext.tag_configure("mono", font=("Consolas", 9), foreground=SUBTEXT, lmargin1=6, lmargin2=6)

    tk.Label(log_panel.inner, text="Log", font=("Segoe UI", 10, "bold"), fg=TEXT, bg=PANEL).pack(anchor="w")
    logbox = tk.Text(log_panel.inner, wrap="word", font=("Consolas", 9), bg=PANEL_HI, fg=TEXT, insertbackground=TEXT,
                     relief="flat", padx=8, pady=8, highlightthickness=0)
    logbox.pack(fill="both", expand=True, pady=(8, 0))
    logbox.tag_configure("err", foreground=RED)
    logbox.tag_configure("ok", foreground=GREEN_HI)
    logbox.tag_configure("info", foreground=CYAN)

    all_buttons = [btn_start, btn_debug, btn_smart, btn_install_one, btn_undo, btn_refresh_icon, btn_openfolder_icon]

    # ───────────────────────── behaviour ─────────────────────────
    def log(msg, kind=None):
        q.put((kind or "line", msg))

    def result():
        return state["result"]

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
        keep = [it for it in r["items"] if it["status"] not in ("installed", "included") or it["patch"].path == state["selected"]]
        return keep

    def render_list():
        plist.set_items(visible_items(), state["selected"], state["new_names"])
        show_lbl.configure(text=("☑ Show installed" if state["show_installed"] else "☐ Show installed"))

    def render_details():
        it = selected_item()
        dtext.configure(state="normal"); dtext.delete("1.0", "end")
        if not it:
            dtext.insert("end", "Pick an update on the left to see what it changes.\n", ("body",))
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
            dtext.insert("end", "Install step %d of %d%s\n" % (it["plan"], total, ("  ·  needs " + needs) if needs else ""), ("why",))
        if st == "conflict":
            dtext.insert("end", "\nTo install it anyway (the files are backed up first), run in the MiniCut folder:\n", ("body",))
            dtext.insert("end", 'python "Patch\\%s" --force\n' % p.name, ("mono",))
        if p.body:
            dtext.insert("end", "What changed\n", ("sec",)); dtext.insert("end", p.body + "\n", ("body",))
        if p.files:
            dtext.insert("end", "Files (%d)\n" % len(p.files), ("sec",))
            shown = [f[0] for f in p.files][:14]
            dtext.insert("end", "\n".join(shown) + ("\n… and %d more" % (len(p.files) - 14) if len(p.files) > 14 else "") + "\n", ("mono",))
        dtext.configure(state="disabled"); dtext.yview_moveto(0)

    def render_banner():
        r = result()
        if not r: return
        plan, cnt = r["plan"], r["count"]
        bad = cnt.get("conflict", 0) + cnt.get("blocked", 0) + cnt.get("error", 0)
        if not r["items"]:
            banner_title.configure(text="No update files in the Patch folder", fg=SUBTEXT)
            banner_sub.configure(text="Drop apply_*.py files into the Patch folder (⤴) - the list refreshes by itself.")
        elif plan:
            names = [p.label for p in plan]
            order = " → ".join(names) if len(names) <= 6 else " → ".join(names[:3] + ["…"] + names[-2:])
            banner_title.configure(text="%d update%s ready to install" % (len(plan), "" if len(plan) == 1 else "s"), fg=GREEN_HI)
            banner_sub.configure(text="Smart order:  " + order + ("      ·  %d need attention" % bad if bad else ""))
        elif bad:
            banner_title.configure(text="%d update%s need attention" % (bad, "" if bad == 1 else "s"), fg=ORANGE_HI)
            first = next((it for it in r["items"] if it["status"] in ("conflict", "blocked", "error")), None)
            banner_sub.configure(text=("%s: %s" % (first["patch"].label, first["reason"])) if first else "")
        else:
            banner_title.configure(text="You're up to date", fg=GREEN_HI)
            banner_sub.configure(text="Current: %s   ·   %d update files checked" % (r["current"] or "—", len(r["items"])))
        banner_sub.configure(wraplength=max(300, banner.winfo_width() - 300))
        btn_smart.set_text("⚡  Smart Update" + (" (%d)" % len(plan) if plan else ""))

    def render_header():
        r = result()
        current_lbl.configure(text="Current: " + ((r and r["current"]) or "—"))
        lb = last_backup_label()
        btn_undo.set_text("Undo Last Update" + (" (%s)" % lb if lb and len(lb) < 14 else ""))
        auto_lbl.configure(text="● Auto-refresh ON" if state["auto"] else "○ Auto-refresh OFF", fg=GREEN_HI if state["auto"] else SUBTEXT)
        if state["checked"]: checked_lbl.configure(text="checked " + state["checked"])

    def update_buttons():
        r = result(); idle = not busy["v"]
        for b in (btn_start, btn_debug, btn_refresh_icon, btn_openfolder_icon): b.set_enabled(idle)
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
                    log("New update file found: %s  [%s]" % (it["patch"].name, STATUS_STYLE.get(it["status"], (it["status"],))[0]), "info")
        gone = state["known"] - names
        for n in sorted(gone): log("Update file removed: " + n, "info")
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
        return messagebox.askokcancel("MiniCut", "Close MiniCut before you change the program files.\n\n" + text + "\n\nContinue?")

    def order_text(items):
        lines = ["  %d.  %s" % (i + 1, p.label) for i, p in enumerate(items[:12])]
        if len(items) > 12: lines.append("  … and %d more" % (len(items) - 12))
        return "\n".join(lines)

    def do_install(items):
        if not items: return
        if not confirm("Install %d update%s in this order:\n%s" % (len(items), "" if len(items) == 1 else "s", order_text(items))): return

        def work():
            py = python_for_minicut(); ok_all = True
            for i, p in enumerate(items):
                log("== [%d/%d] Installing %s" % (i + 1, len(items), p.name), "info")
                ok = install_patch(p, py, log)
                log("== " + ("done" if ok else "FAILED") + ": " + p.label + "\n", "ok" if ok else "err")
                if not ok: ok_all = False; break
            if ok_all: log("All selected updates are installed. Start MiniCut as usual.", "ok")
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
        if not confirm("Undo the last installed update%s.\nOnly files of that update are put back." % (" (%s)" % lb if lb else "")): return
        def work():
            undo_last(log); state["after_done"] = "refresh"
        run_bg(work)

    def do_start(debug=False):
        try: log(start_minicut(debug=debug))
        except Exception as ex: messagebox.showerror("MiniCut", "Could not start MiniCut:\n%s" % ex)

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

    btn_start.command = lambda: do_start(False)
    btn_debug.command = lambda: do_start(True)
    btn_smart.command = do_smart
    btn_install_one.command = do_one
    btn_undo.command = do_undo
    btn_refresh_icon.command = lambda: refresh()
    btn_openfolder_icon.command = lambda: (patch_files_on_disk(), _open_folder(PATCH_DIR))
    auto_lbl.bind("<Button-1>", toggle_auto)
    show_lbl.bind("<Button-1>", toggle_installed)

    def drain():
        pending = []
        try:
            while True: pending.append(q.get_nowait())
        except queue.Empty: pass
        for m in pending:
            kind = m[0]
            if kind == "analysis": apply_result(m[1], m[2], m[3])
            elif kind == "analysis_fail":
                state["analyzing"] = False; logbox.insert("end", "Could not read the updates: %s\n" % m[1], "err"); logbox.see("end"); update_buttons()
            elif kind == "done":
                set_busy(False)
                if state["after_done"] == "refresh": state["after_done"] = None; refresh()
            elif kind in ("err", "ok", "info"):
                logbox.insert("end", str(m[1]) + "\n", kind); logbox.see("end")
            else:
                logbox.insert("end", str(m[1]) + "\n"); logbox.see("end")
        win.after(100, drain)

    patch_files_on_disk()           # creates the Patch folder and its README on first start
    render_header()
    log("Put update files (apply_*.py) in the Patch folder - the list refreshes by itself.")
    drain(); refresh(); poll()
    win.mainloop()


# ───────────────────────── command line (testing) ─────────────────────────
def run_cli(args):
    py = python_for_minicut()
    def log(m): print(m, flush=True)
    cmd = args[0] if args else "status"
    if cmd in ("status", "plan"):
        r = analyze()
        for it in r["items"]:
            print("%-14s %-10s %s" % (it["patch"].label, it["status"], ("step %d" % it["plan"]) if it["plan"] else ""))
        print("current:", r["current"], "| install order:", " -> ".join(p.label for p in r["plan"]) or "(nothing to install)")
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
        sys.exit(run_cli(sys.argv[sys.argv.index("--cli") + 1:]))
    run_gui()
