"""What this computer is: CPU / GPU names, load, memory, disk. Everything is best effort and never raises (a missing value is None)."""
import os, re, sys, shutil, subprocess, threading, time, platform

NOWIN = 0x08000000 if os.name == "nt" else 0


def _run(cmd, timeout=8):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=NOWIN)
        return r.stdout.decode("utf-8", "replace").strip()
    except Exception: return ""


def cpu_name():
    n = ""
    try:
        if os.name == "nt":
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k: n = winreg.QueryValueEx(k, "ProcessorNameString")[0]
        elif sys.platform == "darwin": n = _run(["sysctl", "-n", "machdep.cpu.brand_string"])
        else:
            for ln in open("/proc/cpuinfo", encoding="utf-8", errors="replace"):
                if ln.lower().startswith("model name"): n = ln.split(":", 1)[1].strip(); break
    except Exception: pass
    return (n or platform.processor() or "CPU").strip()


def short_cpu(n):
    """'Intel(R) Core(TM) i3-10100F CPU @ 3.60GHz' -> 'i3 10100F'; 'AMD Ryzen 5 5600X 6-Core Processor' -> 'Ryzen 5 5600X'."""
    s = re.sub(r"\((R|TM|tm|r)\)", "", n); s = re.sub(r"@.*$", "", s)
    s = re.sub(r"\b(Intel|AMD|Core|CPU|Processor|with.*|\d+-Core|APU)\b", "", s, flags=re.I)
    s = re.sub(r"(i[3579])-", r"\1 ", s); s = re.sub(r"\s+", " ", s).strip()
    return s or n


def gpu_names():
    """Names of the video adapters (the real GPU first)."""
    names = []
    try:
        if os.name == "nt":
            out = _run(["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name"])
            names = [x.strip() for x in out.splitlines() if x.strip()]
            if not names:
                out = _run(["wmic", "path", "win32_VideoController", "get", "name"])
                names = [x.strip() for x in out.splitlines()[1:] if x.strip()]
        else:
            out = _run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
            names = [x.strip() for x in out.splitlines() if x.strip()]
            if not names:
                out = _run(["sh", "-c", "lspci 2>/dev/null | grep -Ei 'vga|3d|display'"])
                names = [re.sub(r"^.*?: ", "", x).strip() for x in out.splitlines() if x.strip()]
    except Exception: pass
    names = [n for n in names if not re.search(r"basic render|remote|virtual|parsec|displaylink", n, re.I)]
    names.sort(key=lambda n: 0 if re.search(r"nvidia|geforce|rtx|gtx|radeon rx|\brx ?\d|arc a", n, re.I) else 1)
    return names


def short_gpu(n):
    s = re.sub(r"\((R|TM|tm|r)\)", "", n)
    s = re.sub(r"\b(NVIDIA|AMD|ATI|GeForce|Radeon|Series|Graphics|Intel|Corporation)\b", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s or n


def vendor(n):
    n = (n or "").lower()
    if "nvidia" in n or "geforce" in n or "rtx" in n or "gtx" in n: return "nvidia"
    if "amd" in n or "radeon" in n or "ati " in n: return "amd"
    if "intel" in n or "uhd" in n or "iris" in n or "arc" in n: return "intel"
    return "other"


def is_discrete(n):
    return bool(re.search(r"nvidia|geforce|rtx|gtx|radeon rx|\brx ?\d{3}|radeon pro|arc a\d", n or "", re.I))


def ram_gb():
    try:
        if os.name == "nt":
            import ctypes
            class MS(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                            ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong), ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ae", ctypes.c_ulonglong)]
            m = MS(); m.l = ctypes.sizeof(MS); ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)); return m.total / 1073741824.0
        for ln in open("/proc/meminfo"):
            if ln.startswith("MemTotal"): return int(ln.split()[1]) / 1048576.0
    except Exception: pass
    return None


def disk(path):
    """(used_bytes, total_bytes) of the drive that holds path, or None."""
    try:
        p = path
        while p and not os.path.exists(p):
            q = os.path.dirname(p)
            if q == p: break
            p = q
        u = shutil.disk_usage(p or "."); return u.total - u.free, u.total
    except Exception: return None


def dir_size(path):
    total = 0
    try:
        for root, _d, files in os.walk(path):
            for f in files:
                try: total += os.path.getsize(os.path.join(root, f))
                except OSError: pass
    except Exception: pass
    return total


def fmt_bytes(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB": return ("%.0f %s" % (n, u)) if u == "B" else ("%.1f %s" % (n, u))
        n /= 1024.0


_cpu_prev = [None]
def cpu_usage():
    """Load of the whole CPU in percent since the last call (None the first time)."""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            i, k, u = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
            ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(i), ctypes.byref(k), ctypes.byref(u))
            f = lambda x: (x.dwHighDateTime << 32) | x.dwLowDateTime
            idle, tot = f(i), f(k) + f(u)
        else:
            v = [int(x) for x in open("/proc/stat").readline().split()[1:]]; idle, tot = v[3] + v[4], sum(v)
        prev = _cpu_prev[0]; _cpu_prev[0] = (idle, tot)
        if prev is None or tot <= prev[1]: return None
        return max(0.0, min(100.0, 100.0 * (1.0 - (idle - prev[0]) / float(tot - prev[1]))))
    except Exception: return None


def gpu_usage():
    """3D load of the GPU in percent (NVIDIA: nvidia-smi; Windows: the 3D engine counters, any vendor). Takes about a second: call it off the GUI thread."""
    try:
        out = _run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"], 4)
        if out and out.splitlines()[0].strip().isdigit(): return float(out.splitlines()[0])
        if os.name == "nt":
            out = _run(["powershell", "-NoProfile", "-Command",
                        "(Get-Counter '\\GPU Engine(*engtype_3D)\\Utilization Percentage' -ErrorAction SilentlyContinue).CounterSamples | Measure-Object CookedValue -Sum | ForEach-Object Sum"], 8)
            if out: return max(0.0, min(100.0, float(out.replace(",", "."))))
    except Exception: pass
    return None


class Hardware:
    """Static info (read once, in a background thread) + a live load that is refreshed every couple of seconds while start() is on."""
    def __init__(self):
        self.cpu = None; self.cpu_short = ""; self.gpus = []; self.gpu = ""; self.gpu_short = ""; self.cores = os.cpu_count() or 4; self.ram = None
        self.cpu_load = None; self.gpu_load = None; self.ready = False; self._run = False
    def _read(self):
        try:
            self.cpu = cpu_name(); self.cpu_short = short_cpu(self.cpu); self.gpus = gpu_names(); self.gpu = self.gpus[0] if self.gpus else ""
            self.gpu_short = short_gpu(self.gpu) if self.gpu else "No GPU found"; self.ram = ram_gb()
        finally: self.ready = True
    def start(self):
        if self._run: return
        self._run = True
        def loop():
            self._read(); cpu_usage()
            while self._run:
                time.sleep(1.0); self.cpu_load = cpu_usage()
                if not self._run: break
                self.gpu_load = gpu_usage()
        threading.Thread(target=loop, name="MiniCutHW", daemon=True).start()
    def stop(self): self._run = False
