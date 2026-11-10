"""Crash log (Patch 36). A native crash (a driver, a codec, a thread) leaves no Python message at all, so the cause was never visible.
This module writes everything that can still be written into  ~/.minicut/crash.log :

  * faulthandler: on a hard crash (segfault, abort, access violation) the Python stack of EVERY thread is written;
  * every uncaught exception, also in worker threads;
  * Qt warnings / critical / fatal messages (for example 'QThread: Destroyed while thread is still running');
  * a 'started' line at the start and a 'clean exit' line at the end, so the next start knows whether the last run ended by itself.

Nothing here can stop the program: every step is inside try / except. Send crash.log when a crash happens again.
"""
import os, sys, time, threading, traceback, atexit

try:
    APP_DIR = os.path.join(os.path.expanduser("~"), ".minicut")
except Exception:
    APP_DIR = "."
LOG = os.path.join(APP_DIR, "crash.log")
_F = None                       # the open file (kept open for faulthandler)
_MAX = 400_000                  # the log is cut to its last part when it grows beyond this many bytes


def _w(text):
    try:
        if _F is not None:
            _F.write(text); _F.flush()
    except Exception: pass


def _stamp(): return time.strftime("%Y-%m-%d %H:%M:%S")


def previous_run_crashed():
    """True when the last run wrote 'started' but never 'clean exit'."""
    try:
        with open(LOG, "rb") as f:
            f.seek(max(0, os.path.getsize(LOG) - 20000)); tail = f.read().decode("utf-8", "replace")
        i = tail.rfind("== started"); j = tail.rfind("== clean exit")
        return i >= 0 and j < i
    except Exception:
        return False


def _trim():
    try:
        if os.path.getsize(LOG) > _MAX:
            with open(LOG, "rb") as f: f.seek(-_MAX // 2, 2); data = f.read()
            with open(LOG, "wb") as f: f.write(b"... (older lines removed)\n" + data[data.find(b"\n") + 1:])
    except Exception: pass


def install():
    global _F
    try:
        os.makedirs(APP_DIR, exist_ok=True); _trim()
        crashed = previous_run_crashed()
        _F = open(LOG, "a", encoding="utf-8", buffering=1)
        if crashed: _w("\n!! the previous run did not end cleanly (see the lines above this one for what it wrote)\n")
        _w("\n== started %s  python %s  pid %d\n" % (_stamp(), sys.version.split()[0], os.getpid()))
    except Exception:
        return
    try:
        import faulthandler
        faulthandler.enable(file=_F, all_threads=True)
    except Exception: pass

    def _hook(et, ev, tb):
        _w("\n-- uncaught exception %s in main thread\n%s" % (_stamp(), "".join(traceback.format_exception(et, ev, tb))))
        try: sys.__excepthook__(et, ev, tb)
        except Exception: pass
    sys.excepthook = _hook

    def _thook(a):
        _w("\n-- uncaught exception %s in thread %s\n%s" % (_stamp(), getattr(a.thread, "name", "?"), "".join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback))))
    try: threading.excepthook = _thook
    except Exception: pass

    def _unraisable(u):
        _w("\n-- unraisable %s %r in %r\n" % (_stamp(), u.exc_value, u.object))
    try: sys.unraisablehook = _unraisable
    except Exception: pass

    atexit.register(lambda: _w("== clean exit %s\n" % _stamp()))


def install_qt():
    """Call after the Qt modules are imported: Qt's own messages (warnings, critical, fatal) go to the log too."""
    try:
        from PySide6.QtCore import qInstallMessageHandler, QtMsgType
        names = {QtMsgType.QtWarningMsg: "warning", QtMsgType.QtCriticalMsg: "CRITICAL", QtMsgType.QtFatalMsg: "FATAL"}
        def _h(kind, ctx, msg):
            if kind in names: _w("[qt %s] %s %s\n" % (names[kind], _stamp(), msg))
            if kind == QtMsgType.QtFatalMsg:
                _w("".join(traceback.format_stack()))
            try: sys.__stderr__.write(msg + "\n")
            except Exception: pass
        qInstallMessageHandler(_h)
    except Exception: pass
