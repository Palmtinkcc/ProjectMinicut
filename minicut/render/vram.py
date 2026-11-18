"""Video memory of the machine MiniCut runs on (render core, step 2).

snapshot() answers, for the card that the OpenGL context of this thread runs on:
    total      the card's own memory (bytes) or None
    budget     what Windows lets this program use right now (DXGI) or None
    usage      what this program uses now (DXGI) or None
    headroom   how many more bytes this program can take now, or None when nothing can tell
    shared     True for a card that uses the system memory (integrated GPU): then the system RAM limit counts too
    source     "dxgi" | "ati" | "nvx" | "none"
Patch 54: DXGI is NOT called inside the program any more. A native call that goes wrong (the access violation of Patch 53, in the render thread) kills the
whole program and no try/except can catch it. A small helper process asks DXGI once a second and prints what it sees; this module only reads those lines.
If the helper crashes, stops or says nothing, the answer is source "none" (the Resource Manager then uses the RAM governor's number and shrinks when the
driver says out of memory) and the program goes on. The helper ends by itself when the program ends. Nothing here can raise.
Switches: MINICUT_NO_DXGI=1 (no helper), MINICUT_VRAM_GL=1 (allow the GL_ATI / GL_NVX memory info inside the program: a native call, off by default).

The DXGI calls are the ones of probe_gpu.py, which ran on a Windows 11 machine with a Radeon RX 580 (DedicatedVideoMemory 4040 MB, budget 3434 MB).
The GL calls (GL_ATI_meminfo, GL_NVX_gpu_memory_info) are NOT verified on a real card.
"""
import os, sys, uuid, threading, json, time, subprocess

NOWIN = 0x08000000 if os.name == "nt" else 0          # CREATE_NO_WINDOW

_GL_ATI_TEXTURE_FREE = 0x87FC          # 4 ints, KB: total free, largest free block, aux free, largest aux free
_GL_NVX_TOTAL = 0x9048                 # KB (dedicated)
_GL_NVX_AVAIL = 0x9049                 # KB (currently available)


def _norm(s):
    return "".join(ch for ch in str(s).lower() if ch.isalnum())


def choose_adapter(found, gl_name):
    """found: list of tuples (name, dedicated bytes, shared bytes, adapter); gl_name: the OpenGL renderer string. Returns (best, others): `best` is the SAME
    tuple object that is in `found` and `others` are all the other tuples, so that exactly the adapters that are not used get released.
    (Patch 53 built a new tuple for the best one, so `f is not best` was true for every adapter and the adapter in use was released as well: it was released
    again later, the COM object was freed and the pointer kept in the program dangled: the access violation in crash.log.)"""
    g = _norm(gl_name); best = None
    for f in found:                                              # the adapter whose name is in (or contains) the GL renderer string
        n = _norm(f[0])
        if n and (n in g or g in n):
            if best is None or f[1] > best[1]: best = f
    if best is None and len(found) == 1: best = found[0]
    if best is None and found: best = max(found, key=lambda f: f[1])          # unknown: the one with the most own memory
    return best, [f for f in found if f is not best]


class _Dxgi:
    """The DXGI adapter that matches the GL renderer name; keeps the IDXGIAdapter3 to ask again and again."""

    def __init__(self, gl_name):
        import ctypes as C
        self.C = C; self.a3 = None; self.a = None; self.fac = None; self.total = None; self.shared_mb = 0; self.name = ""
        dxgi = C.WinDLL("dxgi")

        class GUID(C.Structure): _fields_ = [("d", C.c_ubyte * 16)]

        def guid(s):
            g = GUID(); g.d[:] = uuid.UUID(s).bytes_le; return g

        def com(ptr, idx, restype, *argtypes):
            vt = C.cast(C.cast(ptr, C.POINTER(C.c_void_p))[0], C.POINTER(C.c_void_p))
            return C.WINFUNCTYPE(restype, C.c_void_p, *argtypes)(vt[idx])

        class DESC1(C.Structure):
            _fields_ = [("Description", C.c_uint16 * 128), ("VendorId", C.c_uint), ("DeviceId", C.c_uint), ("SubSysId", C.c_uint), ("Revision", C.c_uint),
                        ("DedicatedVideoMemory", C.c_size_t), ("DedicatedSystemMemory", C.c_size_t), ("SharedSystemMemory", C.c_size_t),
                        ("LuidLow", C.c_uint), ("LuidHigh", C.c_int), ("Flags", C.c_uint)]

        class MEMINFO(C.Structure):
            _fields_ = [("Budget", C.c_uint64), ("CurrentUsage", C.c_uint64), ("AvailableForReservation", C.c_uint64), ("CurrentReservation", C.c_uint64)]
        self._com = com; self._MEMINFO = MEMINFO
        fac = C.c_void_p()
        if dxgi.CreateDXGIFactory1(C.byref(guid("770aae78-f26f-4dba-a829-253c83d1b387")), C.byref(fac)) != 0: raise RuntimeError("no DXGI factory")
        self.fac = fac; found = []; i = 0
        while True:
            a = C.c_void_p()
            if com(fac, 12, C.c_long, C.c_uint, C.POINTER(C.c_void_p))(fac, i, C.byref(a)) != 0: break      # IDXGIFactory1::EnumAdapters1
            d = DESC1()
            if com(a, 10, C.c_long, C.POINTER(DESC1))(a, C.byref(d)) == 0:                                    # IDXGIAdapter1::GetDesc1
                nm = "".join(chr(c) for c in d.Description if c).strip()
                if not (d.Flags & 2): found.append((nm, d.DedicatedVideoMemory, d.SharedSystemMemory, a))      # skip software adapters
                else: com(a, 2, C.c_ulong)(a)
            else: com(a, 2, C.c_ulong)(a)
            i += 1
        if not found: raise RuntimeError("no hardware adapter")
        best, others = choose_adapter(found, gl_name)
        for f in others: com(f[3], 2, C.c_ulong)(f[3])                  # Release the others (only the others)
        self.name, self.total, self.shared_mb = best[0], int(best[1]), int(best[2]) // 2 ** 20
        a3 = C.c_void_p(); iid = guid("645967A4-1392-4310-A798-8053CE3E93FD")                                  # IDXGIAdapter3
        if com(best[3], 0, C.c_long, C.c_void_p, C.POINTER(C.c_void_p))(best[3], C.cast(C.byref(iid), C.c_void_p), C.byref(a3)) != 0: raise RuntimeError("no IDXGIAdapter3")
        self.a = best[3]; self.a3 = a3                                  # both references stay: the adapter is not released here (probe_gpu.py used them in this order)

    def query(self):
        C = self.C; out = {}
        for seg in (0, 1):                                              # 0 = local (the card's memory), 1 = non-local (system memory it may use)
            m = self._MEMINFO()
            if self._com(self.a3, 14, C.c_long, C.c_uint, C.c_uint, C.POINTER(self._MEMINFO))(self.a3, 0, seg, C.byref(m)) != 0: return None  # QueryVideoMemoryInfo
            out[seg] = (int(m.Budget), int(m.CurrentUsage))
        return out

    def close(self):
        C = self.C
        for p in (self.a3, self.a, self.fac):
            try:
                if p: self._com(p, 2, C.c_ulong)(p)
            except Exception: pass
        self.a3 = None; self.a = None; self.fac = None


class _Helper:
    """One helper process per card name (shared by all engines of the program). Its output lines are read by a thread; nothing here ever blocks the renderer."""

    def __init__(self, gl_name):
        cmd = os.environ.get("MINICUT_VRAM_HELPER_CMD")                      # (tests) a different command that prints the same JSON lines
        cmd = json.loads(cmd) if cmd else [sys.executable, os.path.abspath(__file__), "--helper", gl_name]
        self.refs = 1; self.exit = None; self._data = None; self._t = 0.0; self.error = ""
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NOWIN, close_fds=True)
        threading.Thread(target=self._read, name="vram-helper-reader", daemon=True).start()

    def _read(self):
        try:
            for line in self.p.stdout:
                try: d = json.loads(line)
                except Exception: continue
                if isinstance(d, dict) and "error" not in d: self._data = d; self._t = time.monotonic()
                elif isinstance(d, dict): self.error = str(d.get("error"))
        except Exception as ex:
            self.error = "reader: %s" % ex
        try: self.exit = self.p.wait()
        except Exception: self.exit = -1
        if not self.error: self.error = "the helper ended (exit code %s)" % self.exit

    def latest(self):
        """(data or None, seconds since it was read). The helper writes every second: older than 5 s means it is lost."""
        d = self._data
        return (d, time.monotonic() - self._t) if d is not None else (None, 1e9)

    def stop(self):
        try: self.p.stdin.close()                                           # the helper ends when its input closes
        except Exception: pass
        try: self.p.wait(timeout=1.0)
        except Exception:
            try: self.p.kill()
            except Exception: pass


_REG = {}; _REG_LOCK = threading.Lock()


def _acquire(gl_name):
    key = _norm(gl_name)
    with _REG_LOCK:
        h = _REG.get(key)
        if h is not None and h.exit is None and h.p.poll() is None: h.refs += 1; return h
        h = _REG[key] = _Helper(gl_name); return h


def _release(h):
    with _REG_LOCK:
        h.refs -= 1
        if h.refs <= 0:
            for k, v in list(_REG.items()):
                if v is h: del _REG[k]
            h.stop()


class VramInfo:
    def __init__(self, gl_name="", gl_extensions=()):
        self.gl_name = gl_name; self.source = "none"; self.total = None; self.shared = False; self._gl = None; self._h = None; self.error = ""
        helper_ok = (os.name == "nt" or os.environ.get("MINICUT_VRAM_HELPER_CMD")) and not os.environ.get("MINICUT_NO_DXGI") and not getattr(sys, "frozen", False)
        if helper_ok:
            try: self._h = _acquire(gl_name)
            except Exception as ex: self._h = None; self.error = "helper: %s" % ex
        elif os.environ.get("MINICUT_VRAM_GL"):                           # opt in: a native call in the program, never verified on a real card
            ext = set(gl_extensions or ())
            for name, src in (("GL_NVX_gpu_memory_info", "nvx"), ("GL_ATI_meminfo", "ati")):
                if name in ext:
                    try:
                        self._gl_open(); self.source = src
                        if src == "nvx":
                            v = self._gl_int(_GL_NVX_TOTAL, 1); self.total = v[0] * 1024 if v else None
                        break
                    except Exception as ex:
                        self.error += " | %s: %s" % (src, ex)

    # ───────────── OpenGL memory info (opt in; needs the context to be current on this thread)
    def _gl_open(self):
        import ctypes as C
        lib = C.WinDLL("opengl32") if os.name == "nt" else C.CDLL("libGL.so.1")
        f = lib.glGetIntegerv; f.argtypes = [C.c_uint, C.POINTER(C.c_int)]; f.restype = None; self._gl = f

    def _gl_int(self, enum, n):
        import ctypes as C
        buf = (C.c_int * 4)(); self._gl(enum, buf); return [int(buf[i]) for i in range(n)]

    def snapshot(self):
        out = {"total": self.total, "budget": None, "usage": None, "headroom": None, "shared": self.shared, "source": "none"}
        try:
            if self._h is not None:
                d, age = self._h.latest()
                if d is not None and age < 5.0:
                    q0 = d.get("local"); q1 = d.get("nonlocal"); self.total = d.get("total"); sh = d.get("shared_mb") or 0
                    self.shared = bool(self.total is not None and self.total < 1024 * 2 ** 20 and sh > self.total / 2 ** 20)
                    if q0 and q1:
                        b0, u0 = q0; b1, u1 = q1
                        if self.shared: b0, u0 = max(b0, b1), max(u0, u1)           # an integrated GPU lives in system memory
                        if 0 <= b0 <= 2 ** 46 and 0 <= u0 <= 2 ** 46:               # (a wrong answer would look like garbage)
                            out["budget"], out["usage"] = b0, u0; out["headroom"] = max(0, b0 - u0)
                    out["total"] = self.total; out["shared"] = self.shared; out["source"] = "dxgi"; self.source = "dxgi"
                else:
                    self.source = "none"; self.error = self._h.error or ("no data from the helper yet" if age >= 1e9 else "the helper is silent")
            elif self._gl is not None:
                if self.source == "nvx":
                    v = self._gl_int(_GL_NVX_AVAIL, 1)
                    if v and v[0] > 0: out["headroom"] = v[0] * 1024; out["source"] = "nvx"
                elif self.source == "ati":
                    v = self._gl_int(_GL_ATI_TEXTURE_FREE, 4)
                    if v and v[0] > 0: out["headroom"] = v[0] * 1024; out["source"] = "ati"
        except Exception as ex:
            self.error = "query: %s" % ex
        return out

    def close(self):
        h, self._h = self._h, None
        if h is not None: _release(h)


def _helper_main(gl_name):
    """The helper process: ask DXGI once a second, print one JSON line each time. Ends when its input closes (the program is gone). A crash here
    is harmless to the program; what it leaves is written to %TEMP%/minicut_vram_helper.txt."""
    import tempfile, traceback, faulthandler
    log = os.path.join(tempfile.gettempdir(), "minicut_vram_helper.txt")
    try: faulthandler.enable(file=open(log, "w"))
    except Exception: pass

    def watch():
        try: sys.stdin.buffer.read()
        except Exception: pass
        os._exit(0)
    threading.Thread(target=watch, daemon=True).start()
    try:
        d = _Dxgi(gl_name)
        while True:
            q = d.query()
            if q: print(json.dumps({"name": d.name, "total": d.total, "shared_mb": d.shared_mb, "local": list(q[0]), "nonlocal": list(q[1])}), flush=True)
            else: print(json.dumps({"error": "QueryVideoMemoryInfo failed"}), flush=True)
            time.sleep(1.0)
    except Exception:
        try: print(json.dumps({"error": traceback.format_exc()[-300:]}), flush=True)
        except Exception: pass
        os._exit(3)


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--helper": _helper_main(sys.argv[2])
