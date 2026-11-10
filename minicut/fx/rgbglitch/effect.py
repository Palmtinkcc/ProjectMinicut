"""rgbglitch: RGB glitch. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_glitch import *

def fx_rgbglitch(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = _r(p, ctx); chans = [img[..., i].copy() for i in range(4)]
    for ci in (0, 2):
        sh = np.zeros(h, np.float32)
        for y0, y1 in _rows(r, h, a): sh[y0:y1] = r.normal(0, w * 0.04 * a) + (w * 0.006 * a if ci == 0 else -w * 0.006 * a)
        chans[ci] = shift_rows(chans[ci][..., None], sh)[..., 0] if False else cv2.remap(chans[ci], *( (coords(h, w)[0] - sh[:, None]) % w, coords(h, w)[1]), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return np.dstack(chans)

reg("rgbglitch", G, "RGB glitch", GP(), fx_rgbglitch, "The red and blue channels jump sideways in bands, like a broken video signal.", "channel split")

ID = "rgbglitch"
