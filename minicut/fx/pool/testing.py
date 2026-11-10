"""Compares every effect folder's GPU version with its CPU version on the same picture.

    python -m minicut.fx.pool.testing              all effects
    python -m minicut.fx.pool.testing mirror emboss  only these

Each effect folder has a cases.json  {"cases": [ {parameter overrides}, ... ]}.  Every case runs on an opaque picture and on one with
see-through pixels. What is compared is what you SEE (colour weighted by alpha) plus the alpha itself, on a 0-255 scale.
A case passes when the mean difference is at most MEAN_MAX. A case the GPU version leaves to the CPU (build() returned None) is listed
as 'cpu' and is not an error. On a machine with only software OpenGL the engine refuses to start: set MINICUT_GLFX_SOFT=1 to test anyway.
"""
import json, os, sys, time
import numpy as np

MEAN_MAX = 0.5


def test_image(w=480, h=270, alpha=False, seed=3):
    """A green screen with a coloured 'person' (soft edge, green fringe, noise) and optionally see-through areas."""
    import cv2                                   # the tests may use OpenCV: they are not part of the program
    rng = np.random.default_rng(seed); img = np.zeros((h, w, 3), np.uint8); img[:] = (40, 200, 30)
    yy, xx = np.mgrid[0:h, 0:w]
    img[..., 1] = np.clip(200 + 25 * np.sin(xx / 17.0) + rng.normal(0, 6, (h, w)), 0, 255)
    d = (xx - w * 0.5) ** 2 / (w * 0.22) ** 2 + (yy - h * 0.5) ** 2 / (h * 0.38) ** 2
    m = d < 1
    sk = np.zeros_like(img); sk[..., 0] = 120 + yy // 4; sk[..., 1] = 150 + (xx // 5) % 40; sk[..., 2] = 210 - xx // 8
    img = np.where(m[..., None], sk, img)
    rim = (d > 0.8) & m; img[rim, 1] = np.clip(img[rim, 1].astype(int) + 40, 0, 255)
    img = cv2.GaussianBlur(img, (0, 0), 0.8)
    a = np.full((h, w, 1), 255, np.uint8)
    if alpha: a[:, :w // 5] = 120; a[h // 4:h // 2, w - w // 4:] = 0
    return np.concatenate([img, a], -1)


def _visible(x):
    a = x[..., 3:4].astype(np.float32) / 255
    return np.concatenate([x[..., :3] * a, x[..., 3:4]], -1)


def run_case(effect_id, params=None, k=1.0, alpha=False):
    """('ok'|'cpu', max, mean, p99.9) for one parameter set."""
    from ...render import effects as E, glfx
    from ...render import fxpack                                   # noqa: F401  (registers the CPU effects)
    spec = E.FX[effect_id]; e = {"id": "x", "type": effect_id, "on": True, "p": dict(params or {})}
    cleaned = E._effect_params(e, spec, 0.5); img = test_image(alpha=alpha)
    ref = E._run_fx({"id": "c", "effects": [e]}, img.copy(), e, spec, k, 0.5, False, None, None)
    plan = glfx.build_chain(img, [(effect_id, cleaned)], E._Ctx(k, 0.5, False))
    if plan is None: return ("cpu", 0.0, 0.0, 0.0)
    out = glfx.execute(img, plan)
    if out.shape[2] == 3: out = np.concatenate([out, np.full(out.shape[:2] + (1,), 255, np.uint8)], -1)
    d = np.abs(_visible(out) - _visible(ref))
    return ("ok", float(d.max()), float(d.mean()), float(np.percentile(d, 99.9)))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    from ...render import glfx
    from .. import loader
    glfx.enable_current_thread(); glfx.set_export_mode(True)
    if not glfx.active():
        print("OpenGL is not available here:", glfx.status()); return 2
    print("GPU:", glfx.status())
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    loader.load_all()
    ids = argv or [d for d in loader.effect_dirs() if d in loader.BUILDERS]          # only the effects that have a GPU version
    bad = 0; t0 = time.perf_counter()
    for eid in ids:
        try:
            cases = json.load(open(os.path.join(root, eid, "cases.json"), encoding="utf-8"))["cases"]
        except Exception as ex:
            print("%-14s no cases.json (%s)" % (eid, ex)); bad += 1; continue
        for c in cases:
            for al in (False, True):
                try: r = run_case(eid, c, alpha=al)
                except Exception as ex: r = ("ERROR %s" % ex, 0, 0, 0)
                passed = r[0] in ("ok", "cpu") and r[2] <= MEAN_MAX
                bad += 0 if passed else 1
                print("%-4s %-14s %-46s alpha=%-5s %-4s max %6.1f  mean %.4f  p99.9 %6.1f" % ("PASS" if passed else "FAIL", eid, json.dumps(c)[:46], al, r[0], r[1], r[2], r[3]))
    for d, err in loader.FAILED.items(): print("FAIL", d, "did not load:\n", err); bad += 1
    print("%s  (%.1f s)" % ("ALL PASSED" if not bad else "%d PROBLEM(S)" % bad, time.perf_counter() - t0))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
