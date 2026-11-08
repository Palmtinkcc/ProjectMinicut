#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MiniCut launcher.  Run:  python minicut/file.py   (or Run_MiniCut.bat).  The code lives in this minicut/ folder."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.getcwd()) != HERE]     # this folder itself must not shadow other modules
sys.path.insert(0, os.path.dirname(HERE))                                           # the folder that contains the minicut package
try:
    from minicut import crashlog; crashlog.install()                                # Patch 36: crash log in ~/.minicut/crash.log
except Exception:
    pass
from minicut.app import main

if __name__ == "__main__":
    if os.environ.get("MINICUT_PROFILE"):
        from minicut import profiler; profiler.start()
    main()
