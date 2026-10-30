#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MiniCut Patch 32 — Where Performance? (step 1: validated OpenCV/FFmpeg HW decode)

Changes only minicut/render/media.py. GPU decoding remains opt-in through the existing Settings option.
The hardware path is kept only when real frames agree with CPU-decoded reference frames; otherwise the
original CPU VideoCapture path is used. No proxy/effect/UI systems are changed.

Usage from the MiniCut folder or its Patch folder:
  python Patch/apply_32_hw_decode_validation.py --check
  python Patch/apply_32_hw_decode_validation.py
  python Patch/apply_32_hw_decode_validation.py --revert
"""
import datetime, hashlib, json, os, py_compile, shutil, sys

PATCH_NAME = "patch32_hw_decode_validation"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.isfile(os.path.join(SCRIPT_DIR, "minicut", "app.py")):
    ROOT = SCRIPT_DIR
elif os.path.isfile(os.path.join(os.path.dirname(SCRIPT_DIR), "minicut", "app.py")):
    ROOT = os.path.dirname(SCRIPT_DIR)
else:
    ROOT = SCRIPT_DIR
BACKUP_ROOT = os.path.join(ROOT, "_patch_backup")
REL = "minicut/render/media.py"
BASE_HASH = "70692b35b6c85c0608540b6a5c7af356f4dcb9bc224267093fb903cd62764434"
NEW_HASH = "5723f6b9b7852beaca981353368d6611510c6a3896ac965da42ac39994d71928"
OLD = 'def open_capture(path):\n    """Open a video file. With "hw_decode" on (Settings) FFmpeg is asked to decode on the GPU; if that is not\n    supported on this PC, fall back to the normal CPU decoder."""\n    # GPU decoding is switched off for every read. With some drivers the GPU decoder returns frames with a pink /\n    # magenta band at the top, which showed up in the viewport. The CPU decoder is used whatever the setting says.\n    return cv2.VideoCapture(path)\n'
NEW = 'def _hw_frame_matches_cpu(hw_frame, cpu_frame):\n    """Conservatively reject visibly different hardware-decoded frames (including pink/magenta bands)."""\n    if hw_frame is None or cpu_frame is None or hw_frame.shape != cpu_frame.shape:\n        return False\n    # Allow small decoder/color-conversion differences, but reject broad corruption or a bad top band.\n    diff = np.abs(hw_frame.astype(np.int16) - cpu_frame.astype(np.int16))\n    mean_diff = float(diff.mean())\n    severe = float((diff.max(axis=2) > 48).mean())\n    top_h = max(1, diff.shape[0] // 8)\n    top = diff[:top_h]\n    body = diff[top_h:] if top_h < diff.shape[0] else diff\n    top_mean = float(top.mean())\n    body_mean = float(body.mean())\n    top_severe = float((top.max(axis=2) > 48).mean())\n    pink_band = top_mean > max(24.0, body_mean * 3.0) and top_severe > 0.10\n    return mean_diff <= 14.0 and severe <= 0.08 and not pink_band\n\n\ndef open_capture(path):\n    """Open a video with optional FFmpeg hardware decoding, validating real frames against CPU decode.\n\n    Hardware decoding is opt-in. If the OpenCV build/backend cannot enable it, frames cannot be read, decoded\n    frames differ materially from CPU reference frames, or seeking back to frame zero fails, use the original\n    CPU path. This keeps the existing VideoCapture/_Reader interface unchanged.\n    """\n    if not CFG.get("hw_decode"):\n        return cv2.VideoCapture(path)\n\n    cap = None\n    cpu = None\n    try:\n        backend = getattr(cv2, "CAP_FFMPEG", None)\n        hw_prop = getattr(cv2, "CAP_PROP_HW_ACCELERATION", None)\n        hw_any = getattr(cv2, "VIDEO_ACCELERATION_ANY", None)\n        if backend is None or hw_prop is None or hw_any is None:\n            return cv2.VideoCapture(path)\n\n        cap = cv2.VideoCapture(path, backend, [hw_prop, hw_any])\n        if not cap.isOpened() or cap.get(hw_prop) <= 0:\n            cap.release()\n            return cv2.VideoCapture(path)\n\n        # Compare several actual decoded frames; opening the stream alone does not prove its output is valid.\n        cpu = cv2.VideoCapture(path)\n        if not cpu.isOpened():\n            cap.release()\n            return cv2.VideoCapture(path)\n        for _ in range(3):\n            hw_ok, hw_frame = cap.read()\n            cpu_ok, cpu_frame = cpu.read()\n            if not hw_ok or not cpu_ok or not _hw_frame_matches_cpu(hw_frame, cpu_frame):\n                cap.release()\n                cap = None\n                return cv2.VideoCapture(path)\n\n        if not cap.set(cv2.CAP_PROP_POS_FRAMES, 0):\n            cap.release()\n            cap = None\n            return cv2.VideoCapture(path)\n        return cap\n    except Exception:\n        if cap is not None:\n            try: cap.release()\n            except Exception: pass\n        return cv2.VideoCapture(path)\n    finally:\n        if cpu is not None:\n            try: cpu.release()\n            except Exception: pass\n'


def norm_hash(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def target():
    return os.path.join(ROOT, *REL.split("/"))


def latest_backup():
    if not os.path.isdir(BACKUP_ROOT): return None
    ds = sorted(d for d in os.listdir(BACKUP_ROOT)
                if os.path.isfile(os.path.join(BACKUP_ROOT, d, "MANIFEST.json"))
                and json.load(open(os.path.join(BACKUP_ROOT, d, "MANIFEST.json"), encoding="utf-8")).get("patch") == PATCH_NAME)
    return os.path.join(BACKUP_ROOT, ds[-1]) if ds else None


def revert(bdir):
    with open(os.path.join(bdir, "MANIFEST.json"), encoding="utf-8") as f: manifest = json.load(f)
    for rel in manifest.get("replaced", []):
        shutil.copy2(os.path.join(bdir, *rel.split("/")), os.path.join(ROOT, *rel.split("/")))
    for rel in manifest.get("created", []):
        try: os.remove(os.path.join(ROOT, *rel.split("/")))
        except FileNotFoundError: pass
    print("Restored Patch 32 backup:", bdir)


def main():
    p = target()
    if not os.path.isfile(p) or not os.path.isfile(os.path.join(ROOT, "minicut", "app.py")):
        print("ERROR: Could not locate the MiniCut root. Put this script in MiniCut/Patch/ or run it from a folder containing minicut/app.py.")
        return 2
    if "--revert" in sys.argv:
        bdir = latest_backup()
        if not bdir: print("No Patch 32 backup found."); return 1
        revert(bdir); return 0

    with open(p, "rb") as f: current = f.read()
    current_hash = norm_hash(current)
    if current_hash == NEW_HASH:
        print("Patch 32 is already installed."); return 0
    if current_hash != BASE_HASH:
        print("STOPPED: minicut/render/media.py differs from the expected Patch 31 version.")
        print("No files were changed. Inspect the file and create a patch for that exact version.")
        return 3
    else:
        text = current.decode("utf-8")
        if text.count(OLD) != 1:
            print("STOPPED: expected source block was not found exactly once; no files were changed.")
            return 3
        output = text.replace(OLD, NEW, 1).encode("utf-8")
    if norm_hash(output) != NEW_HASH:
        print("STOPPED: generated patch does not match its expected hash; no files were changed.")
        return 3

    if "--check" in sys.argv:
        print("Patch 32 check passed: one file will change:", REL)
        return 0

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bdir = os.path.join(BACKUP_ROOT, stamp)
    os.makedirs(bdir, exist_ok=False)
    backup = os.path.join(bdir, *REL.split("/")); os.makedirs(os.path.dirname(backup), exist_ok=True)
    shutil.copy2(p, backup)
    with open(os.path.join(bdir, "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump({"patch": PATCH_NAME, "created": [], "replaced": [REL]}, f, indent=2)
    try:
        with open(p, "wb") as f: f.write(output)
        py_compile.compile(p, doraise=True)
        with open(p, "rb") as f: written = f.read()
        if norm_hash(written) != NEW_HASH: raise RuntimeError("post-write hash mismatch")
    except Exception as ex:
        shutil.copy2(backup, p)
        print("ERROR: patch validation failed; original file restored:", ex)
        return 1
    print("Patch 32 installed. Changed 1 file:", REL)
    print("Backup:", bdir)
    print("Undo with: python Patch/apply_32_hw_decode_validation.py --revert")
    print("Note: hardware behavior must still be tested on the target PC with the GPU decode setting enabled.")
    return 0


if __name__ == "__main__":
    try: code = main()
    except Exception as ex: print("Unexpected error:", repr(ex)); code = 1
    sys.exit(code)
