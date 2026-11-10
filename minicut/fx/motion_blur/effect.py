"""motion_blur: Motion Blur. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import _premul, _unpremul, register

def fx_motion_blur(img, p, ctx):
    n = int(p["length"] * ctx.k)
    if n < 2: return img
    h, w = img.shape[:2]; n = min(n, max(h, w) // 2)
    bidirectional = p.get("bidirectional", False)
    sc = max(1.0, n / 14.0)
    pm, a = _premul(img)
    if sc > 1:
        sw, sh = max(1, int(w / sc)), max(1, int(h / sc))
        pm = cv2.resize(pm, (sw, sh), interpolation=cv2.INTER_AREA)
        a  = cv2.resize(a,  (sw, sh), interpolation=cv2.INTER_AREA)
    m = max(3, int(round(n / sc))) | 1; ker = np.zeros((m, m), np.float32)
    if bidirectional:
        ker[m // 2, :] = 1   # already symmetric
    else:
        ker[m // 2, m // 2:] = 1    # trailing blur only (direction of motion)
    ker = cv2.warpAffine(ker, cv2.getRotationMatrix2D((m / 2 - .5, m / 2 - .5), -p["angle"], 1), (m, m))
    ker /= max(float(ker.sum()), 1e-6)
    pad = m // 2
    def run(x): return cv2.filter2D(cv2.copyMakeBorder(x, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0), -1, ker)[pad:-pad, pad:-pad]
    pm, a = run(pm), run(a)
    if sc > 1:
        pm = cv2.resize(pm, (w, h), interpolation=cv2.INTER_LINEAR)
        a  = cv2.resize(a,  (w, h), interpolation=cv2.INTER_LINEAR)
    return _unpremul(pm, a)

register("motion_blur", "Blur", "Motion Blur",
         [("length",        "Length",        "float", 40.0, 0.0, 300.0),
          ("angle",         "Angle",         "float", 0.0, -180.0, 180.0),
          ("bidirectional", "Bidirectional", "bool",  False, None, None)],
         fx_motion_blur,
         help="Directional motion blur. Bidirectional mode blurs in both directions for a centered look.")

ID = "motion_blur"
