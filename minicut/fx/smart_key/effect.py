"""Better Chroma Key on the GPU: matte from the chroma distance, despill, choke / feather, edge colour.
Same steps and constants as render/smartkey.fx_smart_key. Targets: col = colour, A = matte, inner / z0 / cn / cd = edge-colour helpers."""
import math

from ..pool.gl import Pass, Built, gauss_chain, shaders

ID = "smart_key"
SH = shaders(__file__)          # every *.frag in this folder, ready to use as SH["name"]


def _sk_bgr(s):
    s = str(s or "#00ff00").lstrip("#")
    if len(s) == 8: s = s[2:]
    try: return (int(s[4:6], 16), int(s[2:4], 16), int(s[0:2], 16))
    except Exception: return (0, 255, 0)


def _blur_to(passes, src, w, h, sigma, prefix, dt="f1"):
    """Gaussian blur of target `src` (grey or colour); returns the name of the result target. dt="f2": 16-bit float targets."""
    if sigma < 0.3: return src
    ps, cur, _ = gauss_chain(w, h, sigma, sigma, src=src, prefix=prefix)
    for q in ps: q.dt = dt
    passes.extend(ps)
    return cur


def build(p, c, w, h, opaque):
    mode = p.get("mode", "color"); view = p.get("view", "result"); k = max(1e-3, float(c.k)); passes = []
    if mode == "object":
        if opaque: return Built([])                                    # nothing rendered (yet): the picture is left alone (as on the CPU)
        passes.append(Pass(SH["obj"], {}, {"u_in": "in"}, "A")); colsrc = "in"
    else:
        kb = _sk_bgr(p["color"]); kd = [v / 255.0 for v in kb]; mx = max(kd); amt = float(p.get("spill", 60.0)) / 100.0
        dom = [1.0 if kd[i] >= 0.7 * mx else 0.0 for i in range(3)]; oth = [1.0 - d for d in dom]; cnt = sum(oth)
        if amt <= 0 or mx < 0.12 or cnt == 0: amt = 0.0
        R, G, B = kb[2], kb[1], kb[0]; Y = math.floor(0.299 * R + 0.587 * G + 0.114 * B + 0.5)
        kc = (float(min(255, max(0, math.floor((R - Y) * 0.713 + 128.5)))), float(min(255, max(0, math.floor((B - Y) * 0.564 + 128.5)))))
        t0 = float(p["tolerance"]) * 1.1 + 1.5; wd = 1.5 + float(p["softness"]) * 1.1
        passes.append(Pass(SH["col"], {"u_dom": tuple(dom), "u_oth": tuple(oth), "u_cnt": cnt, "u_amt": amt}, {"u_in": "in"}, "col"))
        passes.append(Pass(SH["matte"], {"u_kc": kc, "u_t0": t0, "u_wd": wd}, {"u_in": "in"}, "A"))
        colsrc = "col"
    A = "A"
    r = float(p.get("choke", 0.0)) * k
    if abs(r) >= 0.5:
        n = int(round(abs(r)))
        if n > 12: return None                                         # a very big choke: the CPU does it
        passes.append(Pass(SH["morph"], {"u_n": n, "u_grow": 0 if r > 0 else 1}, {"u_in": A}, "A1")); A = "A1"
    f = float(p.get("feather", 0.0)) * k
    if f > 0.3: A = _blur_to(passes, A, w, h, f * 0.5, "kf")
    emode = p.get("edge_mode", "auto"); eamt = float(p.get("edge_amount", 70.0)) / 100.0; wpx = float(p.get("edge_width", 3.0)) * k
    edge_on = not (emode == "off" or eamt <= 0 or wpx <= 0.0)
    zname = A; cn = A; cd = A
    if edge_on or view == "edge":
        wz = wpx if edge_on else max(1.0, float(p.get("edge_width", 3.0)) * k); n = max(1, int(round(wz)))
        if n > 12: return None
        passes.append(Pass(SH["inner"], {"u_n": n}, {"u_in": A}, "inner"))
        passes.append(Pass(SH["zone"], {}, {"u_in": A, "u_inner": "inner"}, "z0"))
        zname = _blur_to(passes, "z0", w, h, max(0.7, wz * 0.35), "kz")
        if edge_on and emode != "custom":
            sig = max(3.0, wz * 2.0 + 3.0)
            passes.append(Pass(SH["cn"], {}, {"u_col": colsrc, "u_inner": "inner"}, "cn0", dt="f2"))
            cn = _blur_to(passes, "cn0", w, h, sig, "kn", "f2"); cd = _blur_to(passes, "inner", w, h, sig, "kd", "f2")
    ec = tuple(v / 255.0 for v in _sk_bgr(p.get("edge_color", "#303030")))
    passes.append(Pass(SH["final"], {"u_amt": eamt, "u_ecol": ec, "u_mode": (0 if not edge_on else (2 if emode == "custom" else 1)),
                                 "u_view": {"result": 0, "matte": 1, "edge": 2}.get(view, 0)},
                       {"u_col": colsrc, "u_A": A, "u_z": zname, "u_cn": cn, "u_cd": cd}, "main"))
    return Built(passes, alpha=True)
