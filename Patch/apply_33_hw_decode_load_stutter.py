#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MiniCut Patch 33 — Reduce repeated GPU-decode validation cost during clip loading.

Only modifies minicut/render/media.py. Requires Patch 32 to be installed.
Run from MiniCut root or Patch folder:
  python Patch/apply_33_hw_decode_load_stutter.py --check
  python Patch/apply_33_hw_decode_load_stutter.py
  python Patch/apply_33_hw_decode_load_stutter.py --revert
"""
import datetime, hashlib, json, os, shutil, sys

PATCH_NAME = "patch33_hw_decode_load_stutter"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.isfile(os.path.join(SCRIPT_DIR, "minicut", "app.py")):
    ROOT = SCRIPT_DIR
elif os.path.isfile(os.path.join(os.path.dirname(SCRIPT_DIR), "minicut", "app.py")):
    ROOT = os.path.dirname(SCRIPT_DIR)
else:
    ROOT = SCRIPT_DIR
BACKUP_ROOT = os.path.join(ROOT, "_patch_backup")
REL = "minicut/render/media.py"
BASE_HASH = "5723f6b9b7852beaca981353368d6611510c6a3896ac965da42ac39994d71928"
NEW_HASH = "3e9bc3e1da0e5afac8eca1afc7167a05bd3dde1cc9d9a155c77a95bb457612f4"
OLD = 'def _hw_frame_matches_cpu(hw_frame, cpu_frame):\n    """Conservatively reject visibly different hardware-decoded frames (including pink/magenta bands)."""\n    if hw_frame is None or cpu_frame is None or hw_frame.shape != cpu_frame.shape:\n        return False\n    # Allow small decoder/color-conversion differences, but reject broad corruption or a bad top band.\n    diff = np.abs(hw_frame.astype(np.int16) - cpu_frame.astype(np.int16))\n    mean_diff = float(diff.mean())\n    severe = float((diff.max(axis=2) > 48).mean())\n    top_h = max(1, diff.shape[0] // 8)\n    top = diff[:top_h]\n    body = diff[top_h:] if top_h < diff.shape[0] else diff\n    top_mean = float(top.mean())\n    body_mean = float(body.mean())\n    top_severe = float((top.max(axis=2) > 48).mean())\n    pink_band = top_mean > max(24.0, body_mean * 3.0) and top_severe > 0.10\n    return mean_diff <= 14.0 and severe <= 0.08 and not pink_band\n\n\ndef open_capture(path):\n    """Open a video with optional FFmpeg hardware decoding, validating real frames against CPU decode.\n\n    Hardware decoding is opt-in. If the OpenCV build/backend cannot enable it, frames cannot be read, decoded\n    frames differ materially from CPU reference frames, or seeking back to frame zero fails, use the original\n    CPU path. This keeps the existing VideoCapture/_Reader interface unchanged.\n    """\n    if not CFG.get("hw_decode"):\n        return cv2.VideoCapture(path)\n\n    cap = None\n    cpu = None\n    try:\n        backend = getattr(cv2, "CAP_FFMPEG", None)\n        hw_prop = getattr(cv2, "CAP_PROP_HW_ACCELERATION", None)\n        hw_any = getattr(cv2, "VIDEO_ACCELERATION_ANY", None)\n        if backend is None or hw_prop is None or hw_any is None:\n            return cv2.VideoCapture(path)\n\n        cap = cv2.VideoCapture(path, backend, [hw_prop, hw_any])\n        if not cap.isOpened() or cap.get(hw_prop) <= 0:\n            cap.release()\n            return cv2.VideoCapture(path)\n\n        # Compare several actual decoded frames; opening the stream alone does not prove its output is valid.\n        cpu = cv2.VideoCapture(path)\n        if not cpu.isOpened():\n            cap.release()\n            return cv2.VideoCapture(path)\n        for _ in range(3):\n            hw_ok, hw_frame = cap.read()\n            cpu_ok, cpu_frame = cpu.read()\n            if not hw_ok or not cpu_ok or not _hw_frame_matches_cpu(hw_frame, cpu_frame):\n                cap.release()\n                cap = None\n                return cv2.VideoCapture(path)\n\n        if not cap.set(cv2.CAP_PROP_POS_FRAMES, 0):\n            cap.release()\n            cap = None\n            return cv2.VideoCapture(path)\n        return cap\n    except Exception:\n        if cap is not None:\n            try: cap.release()\n            except Exception: pass\n        return cv2.VideoCapture(path)\n    finally:\n        if cpu is not None:\n            try: cpu.release()\n            except Exception: pass\n'
NEW = '_HW_DECODE_VALIDATION_CACHE = {}\n\n\ndef _hw_frame_matches_cpu(hw_frame, cpu_frame):\n    """Conservatively reject visibly different hardware-decoded frames (including pink/magenta bands)."""\n    if hw_frame is None or cpu_frame is None or hw_frame.shape != cpu_frame.shape:\n        return False\n    # Compare reduced copies: full-resolution per-pixel comparisons were expensive during clip loading.\n    def sample(frame):\n        h, w = frame.shape[:2]\n        scale = min(1.0, 320.0 / max(1, w), 180.0 / max(1, h))\n        if scale < 1.0:\n            frame = cv2.resize(frame, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)\n        return frame.astype(np.int16)\n    hw = sample(hw_frame)\n    cpu = sample(cpu_frame)\n    if hw.shape != cpu.shape:\n        return False\n    diff = np.abs(hw - cpu)\n    mean_diff = float(diff.mean())\n    severe = float((diff.max(axis=2) > 48).mean())\n    top_h = max(1, diff.shape[0] // 8)\n    top = diff[:top_h]\n    body = diff[top_h:] if top_h < diff.shape[0] else diff\n    top_mean = float(top.mean())\n    body_mean = float(body.mean())\n    top_severe = float((top.max(axis=2) > 48).mean())\n    pink_band = top_mean > max(24.0, body_mean * 3.0) and top_severe > 0.10\n    return mean_diff <= 14.0 and severe <= 0.08 and not pink_band\n\n\ndef _hw_validation_key(path):\n    """Cache validation only for the exact file version that was checked."""\n    try:\n        st = os.stat(path)\n        return (os.path.normcase(os.path.abspath(path)), st.st_size, st.st_mtime_ns)\n    except OSError:\n        return None\n\n\ndef open_capture(path):\n    """Open optional FFmpeg hardware decoding with real-frame validation and CPU fallback.\n\n    Successful/failed validation is cached per file version so opening the same clip repeatedly does not decode\n    and compare reference frames every time. The first open still validates actual frames against CPU decoding.\n    """\n    if not CFG.get("hw_decode"):\n        return cv2.VideoCapture(path)\n\n    key = _hw_validation_key(path)\n    cached = _HW_DECODE_VALIDATION_CACHE.get(key) if key is not None else None\n    if cached is False:\n        return cv2.VideoCapture(path)\n\n    cap = None\n    cpu = None\n    try:\n        backend = getattr(cv2, "CAP_FFMPEG", None)\n        hw_prop = getattr(cv2, "CAP_PROP_HW_ACCELERATION", None)\n        hw_any = getattr(cv2, "VIDEO_ACCELERATION_ANY", None)\n        if backend is None or hw_prop is None or hw_any is None:\n            if key is not None: _HW_DECODE_VALIDATION_CACHE[key] = False\n            return cv2.VideoCapture(path)\n\n        cap = cv2.VideoCapture(path, backend, [hw_prop, hw_any])\n        if not cap.isOpened() or cap.get(hw_prop) <= 0:\n            if cap is not None: cap.release()\n            if key is not None: _HW_DECODE_VALIDATION_CACHE[key] = False\n            return cv2.VideoCapture(path)\n\n        # A prior successful real-frame test is valid for this unchanged file and backend setting.\n        if cached is True:\n            return cap\n\n        cpu = cv2.VideoCapture(path)\n        if not cpu.isOpened():\n            cap.release(); cap = None\n            if key is not None: _HW_DECODE_VALIDATION_CACHE[key] = False\n            return cv2.VideoCapture(path)\n\n        # Two frames give a modest safety check while reducing first-open CPU work vs. three full-size compares.\n        for _ in range(2):\n            hw_ok, hw_frame = cap.read()\n            cpu_ok, cpu_frame = cpu.read()\n            if not hw_ok or not cpu_ok or not _hw_frame_matches_cpu(hw_frame, cpu_frame):\n                cap.release(); cap = None\n                if key is not None: _HW_DECODE_VALIDATION_CACHE[key] = False\n                return cv2.VideoCapture(path)\n\n        if not cap.set(cv2.CAP_PROP_POS_FRAMES, 0):\n            cap.release(); cap = None\n            if key is not None: _HW_DECODE_VALIDATION_CACHE[key] = False\n            return cv2.VideoCapture(path)\n        if key is not None:\n            _HW_DECODE_VALIDATION_CACHE[key] = True\n            # Bound memory when projects contain many distinct media files.\n            while len(_HW_DECODE_VALIDATION_CACHE) > 256:\n                _HW_DECODE_VALIDATION_CACHE.pop(next(iter(_HW_DECODE_VALIDATION_CACHE)))\n        return cap\n    except Exception:\n        if cap is not None:\n            try: cap.release()\n            except Exception: pass\n        if key is not None: _HW_DECODE_VALIDATION_CACHE[key] = False\n        return cv2.VideoCapture(path)\n    finally:\n        if cpu is not None:\n            try: cpu.release()\n            except Exception: pass\n'

def norm_hash(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()

def target():
    return os.path.join(ROOT, *REL.split("/"))

def latest_backup():
    if not os.path.isdir(BACKUP_ROOT): return None
    found=[]
    for d in os.listdir(BACKUP_ROOT):
        mf=os.path.join(BACKUP_ROOT,d,"MANIFEST.json")
        if os.path.isfile(mf):
            try:
                with open(mf,encoding="utf-8") as f: data=json.load(f)
                if data.get("patch")==PATCH_NAME: found.append(d)
            except Exception: pass
    return os.path.join(BACKUP_ROOT, sorted(found)[-1]) if found else None

def revert(bdir):
    with open(os.path.join(bdir,"MANIFEST.json"),encoding="utf-8") as f: manifest=json.load(f)
    for rel in manifest.get("replaced",[]): shutil.copy2(os.path.join(bdir,*rel.split("/")),os.path.join(ROOT,*rel.split("/")))
    for rel in manifest.get("created",[]):
        try: os.remove(os.path.join(ROOT,*rel.split("/")))
        except FileNotFoundError: pass
    print("Patch 33 reverted; restored:", bdir)

def main():
    p=target()
    if not os.path.isfile(p) or not os.path.isfile(os.path.join(ROOT,"minicut","app.py")):
        print("ERROR: MiniCut root not found. Put this script in MiniCut/Patch/."); return 2
    if "--revert" in sys.argv:
        b=latest_backup()
        if not b: print("No Patch 33 backup found."); return 1
        revert(b); return 0
    with open(p,"rb") as f: current=f.read()
    h=norm_hash(current)
    if h==NEW_HASH: print("Patch 33 is already installed."); return 0
    if h!=BASE_HASH:
        print("STOPPED: minicut/render/media.py is not the expected Patch 32 version.")
        print("No files changed. Install/verify Patch 32 first, or provide the exact current file."); return 3
    text=current.decode("utf-8")
    if text.count(OLD)!=1:
        print("STOPPED: expected Patch 32 source block not found exactly once; no files changed."); return 3
    output=text.replace(OLD,NEW,1).encode("utf-8")
    if norm_hash(output)!=NEW_HASH:
        print("STOPPED: generated hash mismatch; no files changed."); return 3
    try: compile(output.decode("utf-8"),p,"exec")
    except Exception as ex: print("STOPPED: syntax check failed; no files changed:",ex); return 3
    if "--check" in sys.argv:
        print("Patch 33 check passed. One file will change:",REL); return 0
    stamp=datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bdir=os.path.join(BACKUP_ROOT,stamp); os.makedirs(bdir,exist_ok=False)
    backup=os.path.join(bdir,*REL.split("/")); os.makedirs(os.path.dirname(backup),exist_ok=True); shutil.copy2(p,backup)
    with open(os.path.join(bdir,"MANIFEST.json"),"w",encoding="utf-8") as f:
        json.dump({"patch":PATCH_NAME,"created":[],"replaced":[REL]},f,indent=2)
    try:
        with open(p,"wb") as f: f.write(output)
        with open(p,"rb") as f: written=f.read()
        if norm_hash(written)!=NEW_HASH: raise RuntimeError("post-write hash mismatch")
        compile(written.decode("utf-8"),p,"exec")
    except Exception as ex:
        shutil.copy2(backup,p); print("ERROR: validation failed; original restored:",ex); return 1
    print("Patch 33 installed. Changed only:",REL)
    print("Backup:",bdir)
    print("Undo: python Patch/apply_33_hw_decode_load_stutter.py --revert")
    print("Note: the first open of each new file still validates real frames; repeated opens reuse that validation.")
    return 0

if __name__=="__main__":
    try: rc=main()
    except Exception as ex: print("Unexpected error:",repr(ex)); rc=1
    sys.exit(rc)
