"""dirsmear: Directional smear. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_warp import *

def fx_dirsmear(img, p, ctx):
    h, w = img.shape[:2]; a = np.deg2rad(p["angle"]); n = int(max(1, p["length"] * ctx.k)); f = f3(img); L = lum(f); m = np.clip((L - p["threshold"] / 100.0) / max(0.01, 1 - p["threshold"] / 100.0), 0, 1)[..., None]; acc = (f * m).astype(np.float32) if p["only_bright"] else f.copy(); covered = 1; step = 1.0; d = np.array([np.cos(a), np.sin(a)])
    while covered < n:
        s = min(step, n - covered); Mt = np.float32([[1, 0, d[0] * s], [0, 1, d[1] * s]]); acc = np.maximum(acc, cv2.warpAffine(acc, Mt, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE) * (p["decay"] / 100.0) ** (s / max(n, 1) * 3)); covered += s; step *= 2
    return pack(np.clip(np.maximum(f, acc) * (p["amount"] / 100.0) + f * (1 - p["amount"] / 100.0), 0, 1), like=img)

reg("dirsmear", LN, "Directional smear", [F("length", "Length", 80, 1, 500), F("angle", "Direction", 0, -180, 180), F("decay", "Fade along the smear", 85, 10, 100), F("threshold", "Bright from", 55, 0, 95), B("only_bright", "Smear only the bright parts", True), F("amount", "Amount", 100, 0, 100)], fx_dirsmear, "Bright parts are dragged into long streaks, like light trails.", "streak trails")

ID = "dirsmear"
