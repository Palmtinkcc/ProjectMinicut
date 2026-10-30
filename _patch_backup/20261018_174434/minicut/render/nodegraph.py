"""Node graph runtime: node types, safe evaluation and application on top of clips (never edits the clip itself)."""
from ..shared.deps import *
from ..shared.core import *
from .media import *


NODE_CATS = OrderedDict([("Input", "#2b7fd6"), ("Math", "#2fa36b"), ("Logic", "#d98a1f"),
                         ("Transform", "#8a5bd6"), ("Effect", "#d65b9a"), ("Output", "#d65b4a")])


OUT_PROPS = OrderedDict([
    ("x", ("Position X", 0.0, -20000, 20000, "prop")), ("y", ("Position Y", 0.0, -20000, 20000, "prop")),
    ("sx", ("Scale X", 100.0, -5000, 5000, "prop")), ("sy", ("Scale Y", 100.0, -5000, 5000, "prop")),
    ("rot", ("Rotation", 0.0, -36000, 36000, "prop")), ("opacity", ("Opacity", 100.0, 0, 100, "prop")),
    ("volume", ("Volume", 100.0, 0, 1000, "prop")),
    ("tint_amt", ("Tint amount", 0.0, 0, 100, "attr")), ("chroma_tolerance", ("Chroma tolerance", 55, 1, 180, "attr")),
    ("mask_feather", ("Mask feather", 0.0, 0, 200, "attr")), ("fsize", ("Text size", 96, 4, 1000, "attr")),
    ("stroke", ("Text stroke", 0, 0, 80, "attr"))])


NODE_MODES = [("replace", "Replace"), ("add", "Add (+)"), ("mul", "Multiply (×)"), ("mulp", "Multiply (÷100, for %)")]


NODE_TYPES = OrderedDict()


def _f(x):
    """Any value -> finite float in a safe range (no NaN / inf / overflow ever leaves a node)."""
    try: x = float(x)
    except Exception: return 0.0
    if x != x or x in (float("inf"), float("-inf")): return 0.0
    return max(-1e9, min(1e9, x))


def _reg(typ, cat, title, ins, outs, params, ev, sink=None):
    NODE_TYPES[typ] = {"cat": cat, "title": title, "ins": ins, "outs": outs, "params": params, "ev": ev, "sink": sink}


class _NCtx:
    __slots__ = ("proj", "t", "clip", "memo", "busy", "err", "cg", "ui", "depth")
    def __init__(self, proj, t, clip, cg, ui=False):
        self.proj, self.t, self.clip, self.cg, self.ui = proj, t, clip, cg, ui
        self.memo, self.busy, self.err, self.depth = {}, set(), set(), 0


_AUDIO_PENDING = set()


def _bg_load_audio(path):
    if path in _AUDIO_PENDING: return
    _AUDIO_PENDING.add(path); threading.Thread(target=lambda: AUDIO.load(path), daemon=True).start()


def _peaks_of(cx, path):
    pk = AUDIO.peaks.get(path)
    if pk is None:
        if cx.ui or threading.current_thread() is threading.main_thread(): _bg_load_audio(path); return None   # never block the UI
        AUDIO.load(path); pk = AUDIO.peaks.get(path)
    return pk if pk is not None and len(pk) else None


def _audio_clips(cx, src):
    P = cx.proj; out = []
    for c in P.clips:
        if c["kind"] not in ("video", "audio") or not c.get("path"): continue
        if src == "*":
            tr = P.track(c["track"])
            if tr is None or tr["muted"]: continue
        elif src.startswith("track:"):
            if c["track"] != src[6:]: continue
        elif src.startswith("clip:"):
            if c["id"] != src[5:]: continue
        elif src == "@target":
            if not cx.clip or c["id"] != cx.clip.get("id"): continue
        out.append(c)
    return out


def _peak_window(cx, c, t, back):
    pk = _peaks_of(cx, c["path"])
    if pk is None: return None, 0.0
    lt = t - c["start"]
    if lt < 0 or lt > c["dur"]: return None, 0.0
    idx = int((c["inp"] + lt) * 100)
    if idx - back >= len(pk): return None, 0.0
    a = max(0, idx - back + 1); b = min(len(pk), idx + 1)
    return (pk[a:b] if b > a else None), lt


def _ev_audio(cx, p, a):
    gain, rel = max(0.0, a[0]), max(10.0, a[1]) / 1000.0
    sens = _f(p.get("sens", 0.15)); lvl = 0.0; beat = 0.0
    for c in _audio_clips(cx, p.get("src", "*")):
        K = max(1, min(150, int(rel / 0.01) + 1))
        seg, lt = _peak_window(cx, c, cx.t, K)
        if seg is not None and len(seg):
            w = np.exp(-3.0 * 0.01 / rel * np.arange(len(seg) - 1, -1, -1))
            lvl = max(lvl, float((seg * w).max()) * max(0.0, prop_at(c, "volume", lt) / 100.0))
        seg2, _ = _peak_window(cx, c, cx.t, K + 10)
        if seg2 is not None and len(seg2) > 10:           # onset = sudden rise above the previous 80 ms
            cs = np.concatenate(([0.0], np.cumsum(seg2))); s = np.arange(8, len(seg2))
            prev = (cs[s] - cs[s - 8]) / 8.0; on = (seg2[s] - prev > sens) & (seg2[s] > 0.05)
            if on.any(): beat = max(beat, float(np.exp(-3.0 * (len(seg2) - 1 - s[on]) * 0.01 / rel).max()))
    return [max(0.0, min(8.0, lvl * gain)), max(0.0, min(1.0, beat))]


def _ev_math(cx, p, a):
    A, B = a; op = p.get("op", "add")
    try:
        if op == "add": r = A + B
        elif op == "sub": r = A - B
        elif op == "mul": r = A * B
        elif op == "div": r = A / B if abs(B) > 1e-9 else 0.0
        elif op == "min": r = min(A, B)
        elif op == "max": r = max(A, B)
        elif op == "pow": r = math.copysign(abs(A) ** max(-8.0, min(8.0, B)), A) if A != 0 else 0.0
        elif op == "mod": r = math.fmod(A, B) if abs(B) > 1e-9 else 0.0
        elif op == "abs": r = abs(A)
        elif op == "neg": r = -A
        elif op == "inv": r = 1.0 - A
        elif op == "sin": r = math.sin(A)
        elif op == "cos": r = math.cos(A)
        elif op == "sqrt": r = math.sqrt(abs(A))
        elif op == "floor": r = math.floor(A)
        elif op == "round": r = round(A)
        else: r = A
    except Exception: r = 0.0
    return [r]


def _ev_map(cx, p, a):
    v, i0, i1, o0, o1 = a
    r = 0.0 if abs(i1 - i0) < 1e-12 else (v - i0) / (i1 - i0)
    if p.get("clamp", True): r = max(0.0, min(1.0, r))
    return [o0 + r * (o1 - o0)]


def _ev_wave(cx, p, a):
    f, amp, off, ph = a; x = (cx.t * f + ph) % 1.0; sh = p.get("shape", "sine")
    if sh == "triangle": w = 4 * abs(x - 0.5) - 1
    elif sh == "saw": w = 2 * x - 1
    elif sh == "square": w = 1.0 if x < 0.5 else -1.0
    else: w = math.sin(2 * math.pi * x)
    return [off + amp * w]


def _noise_h(i, seed):
    n = (int(i) * 374761393 + int(seed) * 668265263) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFF) / 32767.5 - 1.0


def _ev_noise(cx, p, a):
    sp, amp, seed = a; x = cx.t * sp; i = math.floor(x); fr = x - i; fr = fr * fr * (3 - 2 * fr)
    return [amp * (_noise_h(i, seed) * (1 - fr) + _noise_h(i + 1, seed) * fr)]


def _ev_compare(cx, p, a):
    A, B = a; op = p.get("op", ">"); tol = abs(_f(p.get("tol", 0.001)))
    r = {">": A > B, "<": A < B, ">=": A >= B, "<=": A <= B, "=": abs(A - B) <= tol, "!=": abs(A - B) > tol}.get(op, False)
    return [1.0 if r else 0.0]


def _ev_logic(cx, p, a):
    A, B = a[0] > 0.5, a[1] > 0.5; op = p.get("op", "and")
    return [1.0 if {"and": A and B, "or": A or B, "xor": A != B, "not": not A}.get(op, False) else 0.0]


def _clip_ref(cx, ref):
    if ref in (None, "", "@target"): return cx.clip
    return next((c for c in cx.proj.clips if c["id"] == ref), None)


def _ev_get_transform(cx, p, a):
    c = _clip_ref(cx, p.get("clip", "@target"))
    if not c: return [OUT_PROPS[k][1] for k in ("x", "y", "sx", "sy", "rot", "opacity", "volume")]
    lt = cx.t - c["start"]; return [prop_at(c, k, lt) for k in ("x", "y", "sx", "sy", "rot", "opacity", "volume")]


def _ev_get_effect(cx, p, a):
    c = _clip_ref(cx, p.get("clip", "@target")); ks = ("tint_amt", "chroma_tolerance", "mask_feather", "fsize", "stroke")
    return [_f((c or {}).get(k, OUT_PROPS[k][1])) for k in ks]


def _ev_clipinfo(cx, p, a):
    c = _clip_ref(cx, p.get("clip", "@target"))
    return [0.0, 0.0, 0.0] if not c else [c["start"], c["dur"], c["start"] + c["dur"]]


def _ev_time(cx, p, a):
    c = cx.clip
    if not c: return [cx.t, cx.t, 0.0]
    lt = cx.t - c["start"]; return [cx.t, lt, max(0.0, min(1.0, lt / max(1e-6, c["dur"])))]


_cmp_ops = [(">", "A > B"), ("<", "A < B"), ("=", "A = B"), (">=", "A ≥ B"), ("<=", "A ≤ B"), ("!=", "A ≠ B")]


_reg("number", "Input", "Number", [], ["Value"], [("value", "Value", "float", 1.0, None)], lambda cx, p, a: [p.get("value", 1.0)])


_reg("time", "Input", "Time", [], ["Time", "Clip time", "Progress"], [], _ev_time)


_reg("audio", "Input", "Audio Level", [("Gain", 1.0), ("Release", 150.0)], ["Level", "Beat"],
     [("src", "Source", "choice", "*", "audiosrc"), ("sens", "Beat sens.", "float", 0.15, None)], _ev_audio)


_reg("clipinfo", "Input", "Clip Info", [], ["Start", "Duration", "End"], [("clip", "Clip", "choice", "@target", "clips@")], _ev_clipinfo)


_reg("math", "Math", "Math", [("A", 0.0), ("B", 1.0)], ["Value"],
     [("op", "Operation", "choice", "add", [("add", "A + B"), ("sub", "A − B"), ("mul", "A × B"), ("div", "A ÷ B"), ("min", "Min"), ("max", "Max"),
       ("pow", "Power"), ("mod", "Modulo"), ("abs", "Abs A"), ("neg", "−A"), ("inv", "1 − A"), ("sin", "Sin A"), ("cos", "Cos A"),
       ("sqrt", "Sqrt A"), ("floor", "Floor A"), ("round", "Round A")])], _ev_math)


_reg("maprange", "Math", "Map Range", [("Value", 0.0), ("In min", 0.0), ("In max", 1.0), ("Out min", 100.0), ("Out max", 120.0)], ["Value"],
     [("clamp", "Clamp", "bool", True, None)], _ev_map)


_reg("clamp", "Math", "Clamp", [("Value", 0.0), ("Min", 0.0), ("Max", 1.0)], ["Value"], [],
     lambda cx, p, a: [max(min(a[1], a[2]), min(max(a[1], a[2]), a[0]))])


_reg("wave", "Math", "Wave", [("Freq Hz", 1.0), ("Amp", 1.0), ("Offset", 0.0), ("Phase", 0.0)], ["Value"],
     [("shape", "Shape", "choice", "sine", [("sine", "Sine"), ("triangle", "Triangle"), ("saw", "Saw"), ("square", "Square")])], _ev_wave)


_reg("noise", "Math", "Noise", [("Speed", 1.0), ("Amp", 1.0), ("Seed", 0.0)], ["Value"], [], _ev_noise)


_reg("compare", "Logic", "Compare", [("A", 0.0), ("B", 0.5)], ["Result"],
     [("op", "Operation", "choice", ">", _cmp_ops), ("tol", "Tolerance", "float", 0.001, None)], _ev_compare)


_reg("logic", "Logic", "Logic", [("A", 0.0), ("B", 0.0)], ["Result"],
     [("op", "Operation", "choice", "and", [("and", "AND"), ("or", "OR"), ("xor", "XOR"), ("not", "NOT A")])], _ev_logic)


_reg("ifelse", "Logic", "If / Else", [("If", 0.0), ("Then", 1.0), ("Else", 0.0)], ["Value"], [],
     lambda cx, p, a: [a[1] if a[0] > 0.5 else a[2]])


_reg("get_transform", "Transform", "Get Transform", [], ["Position X", "Position Y", "Scale X", "Scale Y", "Rotation", "Opacity", "Volume"],
     [("clip", "Clip", "choice", "@target", "clips@")], _ev_get_transform)


_reg("get_effect", "Effect", "Get Effect", [], ["Tint amount", "Chroma tol.", "Mask feather", "Text size", "Text stroke"],
     [("clip", "Clip", "choice", "@target", "clips@")], _ev_get_effect)


_SINK_P = [("clip", "Clip", "choice", "*", "clips*"), ("mode", "Mode", "choice", "replace", NODE_MODES)]


_reg("set_transform", "Transform", "Set Transform",
     [("Position X", 0.0), ("Position Y", 0.0), ("Scale", 100.0), ("Scale X", 100.0), ("Scale Y", 100.0), ("Rotation", 0.0), ("Opacity", 100.0)], [],
     _SINK_P, lambda cx, p, a: [], sink=[("x",), ("y",), ("sx", "sy"), ("sx",), ("sy",), ("rot",), ("opacity",)])


_reg("set_effect", "Effect", "Set Effect", [("Tint amount", 0.0), ("Chroma tol.", 0.0), ("Mask feather", 0.0), ("Text size", 0.0), ("Text stroke", 0.0)], [],
     _SINK_P, lambda cx, p, a: [], sink=[("tint_amt",), ("chroma_tolerance",), ("mask_feather",), ("fsize",), ("stroke",)])


_reg("set_volume", "Output", "Set Volume", [("Volume", 100.0)], [], _SINK_P, lambda cx, p, a: [], sink=[("volume",)])


_reg("set_prop", "Output", "Set Property", [("Value", 0.0)], [],
     [("prop", "Property", "choice", "x", "props")] + _SINK_P, lambda cx, p, a: [], sink=[("@prop",)])


class CGraph:
    """Immutable snapshot of a graph (safe to read from the render / audio / export threads)."""
    def __init__(self, g):
        self.nodes = {}; self.links = {}
        for n in list(g.get("nodes", [])):
            if n.get("type") in NODE_TYPES and n.get("id"): self.nodes[n["id"]] = {"type": n["type"], "p": dict(n.get("p") or {})}
        for l in list(g.get("links", [])):
            if l.get("from") in self.nodes and l.get("to") in self.nodes: self.links[(l["to"], l.get("ti", 0))] = (l["from"], l.get("fo", 0))
        self.live = []
        for nid, n in self.nodes.items():
            sp = NODE_TYPES[n["type"]]
            if sp["sink"] is not None and not n["p"].get("mute") and any((nid, i) in self.links for i in range(len(sp["ins"]))): self.live.append(nid)


def _node_out(cx, nid):
    if nid in cx.memo: return cx.memo[nid]
    n = cx.cg.nodes.get(nid)
    if n is None: return None
    if nid in cx.busy or cx.depth > 150: cx.err.add(nid); return None        # loop / too deep -> ignore this branch
    sp = NODE_TYPES[n["type"]]; cx.busy.add(nid); cx.depth += 1
    try:
        a = []
        for i, (lab, dflt) in enumerate(sp["ins"]):
            v = None; src = cx.cg.links.get((nid, i))
            if src:
                o = _node_out(cx, src[0])
                if o is not None and src[1] < len(o): v = o[src[1]]
            a.append(_f(n["p"].get("i%d" % i, dflt) if v is None else v))
        res = [_f(x) for x in sp["ev"](cx, n["p"], a)]
    except Exception:
        res = [0.0] * len(sp["outs"]); cx.err.add(nid)
    cx.busy.discard(nid); cx.depth -= 1; cx.memo[nid] = res
    return res


def _overrides(cx, c):
    """[(key, mode, value)] produced by every live Set-node that targets clip c."""
    out = []
    for nid in cx.cg.live:
        n = cx.cg.nodes[nid]; p = n["p"]
        if p.get("clip", "*") not in ("*", c["id"]): continue
        sp = NODE_TYPES[n["type"]]
        for i, keys in enumerate(sp["sink"]):
            src = cx.cg.links.get((nid, i))
            if not src: continue
            o = _node_out(cx, src[0])
            if o is None or src[1] >= len(o): continue
            for k in keys: out.append((p.get("prop", "x") if k == "@prop" else k, p.get("mode", "replace"), o[src[1]]))
    return out


def node_apply(proj, c, t, ui=False):
    """Return clip c with all node outputs applied (a shadow copy), or c itself when no node drives it."""
    g = getattr(proj, "graph", None)
    if not g or not g.get("links") or g.get("on", True) is False: return c
    try:
        cg = CGraph(g)
        if not cg.live: return c
        cx = _NCtx(proj, t, c, cg, ui); ov = _overrides(cx, c)
        if not ov: return c
        s = dict(c); props = dict(c["props"]); lt = t - c["start"]; cur = {}
        for k, mode, val in ov:
            spec = OUT_PROPS.get(k)
            if spec is None: continue
            if k not in cur: cur[k] = _f(prop_at(c, k, lt)) if spec[4] == "prop" else _f(c.get(k, spec[1]))
            b = cur[k]
            v = {"replace": val, "add": b + val, "mul": b * val, "mulp": b * val / 100.0}.get(mode, val)
            cur[k] = max(spec[2], min(spec[3], _f(v)))
        for k, v in cur.items():
            if OUT_PROPS[k][4] == "prop": props[k] = {"v": round(v, 4), "k": []}
            else: s[k] = int(round(v)) if k in ("fsize", "stroke", "chroma_tolerance") else v
        s["props"] = props
        return s
    except Exception as ex:
        print("[nodes]", ex); return c


def node_drives(proj, c, key):
    g = getattr(proj, "graph", None)
    if not g or not g.get("links") or g.get("on", True) is False: return False
    try:
        cg = CGraph(g)
        for nid in cg.live:
            n = cg.nodes[nid]; p = n["p"]
            if p.get("clip", "*") not in ("*", c["id"]): continue
            sp = NODE_TYPES[n["type"]]
            for i, keys in enumerate(sp["sink"]):
                if (nid, i) in cg.links and any((p.get("prop", "x") if k == "@prop" else k) == key for k in keys): return True
    except Exception: pass
    return False


def node_debug(proj, t, clip):
    """{node id: [output values]} for the live read-outs in the node editor."""
    g = getattr(proj, "graph", None)
    if not g: return {}, set()
    cg = CGraph(g)
    if clip is None:
        clip = {"id": "", "start": 0.0, "dur": 1.0, "kind": "video", "track": "", "inp": 0.0, "props": {k: {"v": v[1], "k": []} for k, v in OUT_PROPS.items() if v[4] == "prop"}}
    cx = _NCtx(proj, t, clip, cg, True)
    for nid in cg.nodes: _node_out(cx, nid)
    return cx.memo, cx.err


def default_graph(): return {"nodes": [], "links": [], "on": True}
