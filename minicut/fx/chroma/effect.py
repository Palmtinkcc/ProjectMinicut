"""chroma: Chroma Key. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import register

def fx_chroma(img, p, ctx):
    try:
        key = QColor(p["color"]); hsv = cv2.cvtColor(np.ascontiguousarray(img[..., :3]), cv2.COLOR_BGR2HSV)
        khsv = cv2.cvtColor(np.uint8([[[key.blue(), key.green(), key.red()]]]), cv2.COLOR_BGR2HSV)[0, 0]; tol = int(p["tolerance"])
        h16 = hsv[..., 0].astype(np.int16); dh = np.minimum(np.abs(h16 - int(khsv[0])), 180 - np.abs(h16 - int(khsv[0])))
        dsat = np.abs(hsv[..., 1].astype(np.int16) - int(khsv[1])); ka = np.clip((np.maximum(dh * 2, dsat) - tol) / max(1, tol), 0, 1)
        out = img.copy(); out[..., 3] = (img[..., 3].astype(np.float32) * ka).astype(np.uint8); return out
    except Exception as ex:
        print("chroma key error:", ex); return img

register("chroma", "Key", "Chroma Key",
         [("color",     "Key color",  "color", "#00ff00", None, None),
          ("tolerance", "Tolerance",  "int",   55, 1, 180)],
         fx_chroma)

ID = "chroma"
