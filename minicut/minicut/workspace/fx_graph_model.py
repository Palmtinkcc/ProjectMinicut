"""FX graph document (Patch 52) - everything the FX node editor does to a graph, with no Qt in it.

The editor window only draws this document and forwards the user's actions to it, so the rules (what can be linked,
undo / redo, copy / paste, search) can be tested without a screen.

A graph is  {"nodes": [{"id", "type", "x", "y", "p": {param: value}, "ex": {param: label}, "mute": bool}],
             "links": [{"from": node id, "fo": output slot, "to": node id, "ti": input socket}]}
"ti" is a position in custom.in_sockets(type): first the picture / value inputs, then one socket for every number or
colour parameter. "ex" lists the parameters that are exposed as a slider of the effect (in the inspector).
"""
import copy, json, re, time, uuid

from ..render.fxpack.custom import (FX_NODE_TYPES, in_sockets, out_kind, collect_param_specs, compile_effect)

CLIP_KIND = "minicut-fx-nodes"
CAT_ORDER = ["Image", "Source", "Color", "Blur", "Distort", "Composite", "Utility", "Parameter"]

# extra words for the node search (English + Thai), on top of the node's title and category
FX_KEYWORDS = {
    "fx_input": "picture source clip original input รูป ต้นฉบับ อินพุต",
    "fx_output": "result final output export ผลลัพธ์ เอาต์พุต",
    "fx_brightness": "light dark contrast exposure สว่าง มืด คอนทราสต์ ความสว่าง",
    "fx_hue_sat": "color colour hue saturation vivid สี ความอิ่ม โทนสี",
    "fx_tint_node": "color colour wash overlay ย้อมสี โทนสี",
    "fx_invert_node": "negative reverse กลับสี ฟิล์มลบ",
    "fx_bw_node": "grey gray black white monochrome desaturate ขาวดำ",
    "fx_threshold": "binary black white cutoff ขาวดำ ตัด",
    "fx_blur_node": "soft glow smooth gaussian เบลอ นุ่ม ฟุ้ง",
    "fx_box_blur": "soft fast เบลอ นุ่ม",
    "fx_displace": "distort warp map bend บิด ดิสเพลซ",
    "fx_wave_warp": "ripple wobble water distort คลื่น บิด น้ำ",
    "fx_chromatic_ab": "rgb split glitch lens fringe แยกสี กลิตช์",
    "fx_pixelate_node": "mosaic blocks retro 8bit โมเสก พิกเซล",
    "fx_over": "layer composite stack put on top ซ้อน เลเยอร์",
    "fx_blend_mode": "multiply screen overlay add difference mix layer ผสม ซ้อน",
    "fx_mask_alpha": "cut transparent matte stencil alpha มาสก์ โปร่งใส ตัด",
    "fx_mix": "blend crossfade fade lerp ผสม เฟด",
    "fx_noise_tex": "texture grain clouds random fbm สุ่ม เม็ด เมฆ",
    "fx_solid": "colour color flat fill background สีพื้น ทึบ พื้นหลัง",
    "fx_gradient": "ramp fade colour color ไล่สี เกรเดียนต์",
    "fx_checker": "chess squares pattern transparent grid ตาหมากรุก ลาย",
    "fx_time": "seconds clock progress animate เวลา แอนิเมชัน",
    "fx_lfo": "oscillator sine wave pulse animate loop repeat คลื่น วนซ้ำ แอนิเมชัน",
    "fx_map_range": "remap scale range convert ปรับช่วง แปลงค่า",
    "fx_math": "add subtract multiply divide calculate บวก ลบ คูณ หาร คำนวณ",
    "fx_constant": "number value fixed ตัวเลข ค่าคงที่",
    "fx_param_float": "slider inspector control number พารามิเตอร์ สไลเดอร์",
    "fx_param_int": "slider inspector control whole number พารามิเตอร์ จำนวนเต็ม",
    "fx_param_color": "colour color picker inspector พารามิเตอร์ ตัวเลือกสี",
}


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def default_graph() -> dict:
    """A new effect starts with the picture already wired to the result (so it works at once)."""
    return {"nodes": [{"id": "in0", "type": "fx_input", "x": 60, "y": 120, "p": {}},
                      {"id": "out0", "type": "fx_output", "x": 520, "y": 120, "p": {}}],
            "links": [{"from": "in0", "fo": 0, "to": "out0", "ti": 0}]}


def node_defaults(typ: str) -> dict:
    return {ps[0]: ps[3] for ps in FX_NODE_TYPES.get(typ, {}).get("params", [])}


def node_rows(typ: str) -> list:
    """What a node shows, row by row (the window draws exactly this). Outputs come first, then one row for every
    input socket (a number / colour parameter row also holds its value field), then the parameters that have no socket.
    Row: {"out": slot or None, "in": socket or None, "kind": 'image'|'float'|'color'|param kind|None, "label", "param"}"""
    spec = FX_NODE_TYPES.get(typ)
    if not spec: return []
    rows = [{"out": j, "in": None, "kind": out_kind(typ), "label": lab, "param": None} for j, lab in enumerate(spec.get("outs", []))]
    used = set()
    for i, (lab, kind, pk) in enumerate(in_sockets(typ)):
        rows.append({"out": None, "in": i, "kind": kind, "label": lab, "param": pk})
        if pk: used.add(pk)
    for ps in spec.get("params", []):
        if ps[0] in used: continue
        rows.append({"out": None, "in": None, "kind": ps[2], "label": ps[1], "param": ps[0]})
    return rows


def param_spec(typ: str, key: str):
    return next((ps for ps in FX_NODE_TYPES.get(typ, {}).get("params", []) if ps[0] == key), None)


def can_expose(typ: str, key: str) -> bool:
    ps = param_spec(typ, key)
    return bool(ps) and ps[2] != "text" and typ not in ("fx_param_float", "fx_param_int", "fx_param_color")


def link_problem(graph: dict, a: str, fo: int, b: str, ti: int):
    """None when a -> b can be linked, otherwise the reason (short, shown to the person)."""
    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    if a not in nodes or b not in nodes: return "missing node"
    if a == b: return "A node cannot be linked to itself"
    ta, tb = nodes[a]["type"], nodes[b]["type"]
    if not (0 <= fo < max(1, len(FX_NODE_TYPES[ta].get("outs", [])))) or not FX_NODE_TYPES[ta].get("outs"): return "That socket is not an output"
    socks = in_sockets(tb)
    if not (0 <= ti < len(socks)): return "That socket is not an input"
    want, got = socks[ti][1], out_kind(ta)
    if got != want: return "These sockets do not fit (%s -> %s)" % (got, want)
    if _reaches(graph, b, a): return "That link would make a loop"
    return None


def _reaches(graph: dict, start: str, goal: str) -> bool:
    """True when `goal` can be reached from `start` by following links forward."""
    nxt = {}
    for lk in graph.get("links", []): nxt.setdefault(lk["from"], []).append(lk["to"])
    seen, stack = set(), [start]
    while stack:
        n = stack.pop()
        if n == goal: return True
        if n in seen: continue
        seen.add(n); stack.extend(nxt.get(n, []))
    return False


def normalize(graph) -> dict:
    """A clean copy of a graph read from a file: unknown nodes and broken links are dropped, defaults are filled in."""
    out = {"nodes": [], "links": []}
    if not isinstance(graph, dict): return default_graph()
    ids = set()
    for n in graph.get("nodes", []) if isinstance(graph.get("nodes"), list) else []:
        if not isinstance(n, dict) or n.get("type") not in FX_NODE_TYPES: continue
        nid = str(n.get("id") or new_id())
        if nid in ids: nid = new_id()
        ids.add(nid)
        d = {"id": nid, "type": n["type"], "x": _num(n.get("x"), 0.0), "y": _num(n.get("y"), 0.0),
             "p": dict(n["p"]) if isinstance(n.get("p"), dict) else {}}
        if n.get("mute"): d["mute"] = True
        if isinstance(n.get("ex"), dict) and n["ex"]: d["ex"] = {str(k): str(v) for k, v in n["ex"].items() if param_spec(d["type"], str(k))}
        out["nodes"].append(d)
    # a node id that was changed above can no longer be found by the links: links are matched on the original ids only
    kept = {n["id"] for n in out["nodes"]}
    for lk in graph.get("links", []) if isinstance(graph.get("links"), list) else []:
        try: a, fo, b, ti = str(lk["from"]), int(lk.get("fo", 0)), str(lk["to"]), int(lk.get("ti", 0))
        except Exception: continue
        if a not in kept or b not in kept: continue
        if link_problem(out, a, fo, b, ti) is None:
            out["links"] = [l for l in out["links"] if not (l["to"] == b and l["ti"] == ti)]
            out["links"].append({"from": a, "fo": fo, "to": b, "ti": ti})
    return out


def _num(v, d):
    try:
        v = float(v)
        return v if v == v and abs(v) < 1e7 else d
    except Exception: return d


# ── search ────────────────────────────────────────────────────────────────────

def search_nodes(query: str, limit: int = 40) -> list:
    """Node types that match `query`, best first. Empty query = every node, in palette order."""
    q = (query or "").strip().lower()
    items = []
    for typ, spec in FX_NODE_TYPES.items():
        title = spec.get("title", typ); cat = spec.get("cat", "")
        if not q:
            items.append((_cat_rank(cat), title.lower(), typ)); continue
        s = _score(q, title.lower(), cat.lower(), FX_KEYWORDS.get(typ, "").lower(), typ.lower())
        if s > 0: items.append((-s, title.lower(), typ))
    items.sort()
    return [t for _s, _t, t in items][:limit]


def _cat_rank(cat): return CAT_ORDER.index(cat) if cat in CAT_ORDER else len(CAT_ORDER)


def _score(q, title, cat, kw, typ) -> int:
    toks = [t for t in re.split(r"\s+", q) if t]
    total = 0
    for t in toks:
        best = 0
        if title == t: best = 100
        elif title.startswith(t): best = 80
        elif any(w.startswith(t) for w in re.split(r"[\s()/\-]+", title)): best = 65
        elif t in title: best = 50
        elif any(w.startswith(t) for w in kw.split()): best = 45
        elif t in kw: best = 35
        elif t in cat: best = 25
        elif t in typ: best = 20
        elif _subseq(t, title): best = 10
        if best == 0: return 0
        total += best
    return total


def _subseq(t, s):
    it = iter(s)
    return all(c in it for c in t)


# ── the document ──────────────────────────────────────────────────────────────

class FxDoc:
    """A graph with undo / redo. Every change goes through a method of this class."""
    UNDO_LIMIT = 100
    COALESCE_SECONDS = 1.2        # dragging a number field makes one undo step, not hundreds

    def __init__(self, graph=None):
        self.graph = normalize(graph) if graph is not None else default_graph()
        self._undo, self._redo = [], []
        self._last_key, self._last_t = None, 0.0
        self.version = 0
        self._saved = self._dump()
        self.on_change = None           # called after every change (the window refreshes itself)

    # -- bookkeeping --
    def _dump(self): return json.dumps(self.graph, sort_keys=True)
    def is_dirty(self) -> bool: return self._dump() != self._saved
    def mark_saved(self): self._saved = self._dump()
    def can_undo(self) -> bool: return bool(self._undo)
    def can_redo(self) -> bool: return bool(self._redo)

    def _push(self, key=None):
        now = time.monotonic()
        if key is not None and key == self._last_key and now - self._last_t < self.COALESCE_SECONDS:
            self._last_t = now; return                     # the same field is still being dragged: same undo step
        self._undo.append(copy.deepcopy(self.graph))
        if len(self._undo) > self.UNDO_LIMIT: del self._undo[0]
        self._redo.clear(); self._last_key, self._last_t = key, now

    def _changed(self):
        self.version += 1
        if self.on_change: self.on_change()

    def undo(self) -> bool:
        if not self._undo: return False
        self._redo.append(copy.deepcopy(self.graph)); self.graph = self._undo.pop(); self._last_key = None; self._changed(); return True

    def redo(self) -> bool:
        if not self._redo: return False
        self._undo.append(copy.deepcopy(self.graph)); self.graph = self._redo.pop(); self._last_key = None; self._changed(); return True

    # -- lookups --
    def node(self, nid): return next((n for n in self.graph["nodes"] if n["id"] == nid), None)
    def links_of(self, nid): return [l for l in self.graph["links"] if l["from"] == nid or l["to"] == nid]
    def link_into(self, b, ti): return next((l for l in self.graph["links"] if l["to"] == b and l["ti"] == ti), None)

    # -- editing --
    def load(self, graph):
        self.graph = normalize(graph); self._undo.clear(); self._redo.clear(); self._last_key = None; self.mark_saved(); self._changed()

    def add_node(self, typ, x=0.0, y=0.0, p=None):
        if typ not in FX_NODE_TYPES: return None
        self._push()
        n = {"id": new_id(), "type": typ, "x": round(float(x), 1), "y": round(float(y), 1), "p": node_defaults(typ)}
        if p: n["p"].update(p)
        self.graph["nodes"].append(n); self._changed(); return n["id"]

    def remove_nodes(self, ids):
        ids = set(ids)
        outs = [n for n in self.graph["nodes"] if n["type"] == "fx_output"]
        keep_out = [n for n in outs if n["id"] not in ids]
        if outs and not keep_out: ids -= {n["id"] for n in outs}       # an effect always keeps its Output
        ids = {i for i in ids if self.node(i)}
        if not ids: return False
        self._push()
        self.graph["nodes"] = [n for n in self.graph["nodes"] if n["id"] not in ids]
        self.graph["links"] = [l for l in self.graph["links"] if l["from"] not in ids and l["to"] not in ids]
        self._changed(); return True

    def add_link(self, a, fo, b, ti):
        """(True, '') or (False, reason). An input holds one link: a new one replaces the old one."""
        why = link_problem(self.graph, a, fo, b, ti)
        if why: return False, why
        if any(l["from"] == a and l["fo"] == fo and l["to"] == b and l["ti"] == ti for l in self.graph["links"]): return True, ""
        self._push()
        self.graph["links"] = [l for l in self.graph["links"] if not (l["to"] == b and l["ti"] == ti)]
        self.graph["links"].append({"from": a, "fo": fo, "to": b, "ti": ti}); self._changed(); return True, ""

    def remove_link(self, a, fo, b, ti):
        n = len(self.graph["links"])
        if not any(l["from"] == a and l["fo"] == fo and l["to"] == b and l["ti"] == ti for l in self.graph["links"]): return False
        self._push()
        self.graph["links"] = [l for l in self.graph["links"] if not (l["from"] == a and l["fo"] == fo and l["to"] == b and l["ti"] == ti)]
        self._changed(); return True

    def set_param(self, nid, key, value):
        n = self.node(nid)
        if n is None or n["p"].get(key) == value: return False
        self._push(("p", nid, key)); n["p"][key] = value; self._changed(); return True

    def set_expose(self, nid, key, on, label=None):
        n = self.node(nid)
        if n is None or not can_expose(n["type"], key): return False
        ex = dict(n.get("ex") or {})
        if on:
            lab = (label or ex.get(key) or param_spec(n["type"], key)[1])
            if ex.get(key) == lab: return False
            ex[key] = str(lab)[:40]
        elif key in ex: del ex[key]
        else: return False
        self._push(("ex", nid, key)); 
        if ex: n["ex"] = ex
        else: n.pop("ex", None)
        self._changed(); return True

    def set_mute(self, ids, on=None):
        ns = [n for n in (self.node(i) for i in ids) if n and n["type"] not in ("fx_input", "fx_output")]
        if not ns: return False
        on = (not all(n.get("mute") for n in ns)) if on is None else bool(on)
        self._push()
        for n in ns:
            if on: n["mute"] = True
            else: n.pop("mute", None)
        self._changed(); return True

    def move_nodes(self, pos: dict):
        """pos: {node id: (x, y)}. One undo step per drag (the window calls this when the mouse is released)."""
        moved = {i: p for i, p in pos.items() if self.node(i) and (round(self.node(i)["x"], 1), round(self.node(i)["y"], 1)) != (round(p[0], 1), round(p[1], 1))}
        if not moved: return False
        self._push()
        for i, (x, y) in moved.items(): n = self.node(i); n["x"], n["y"] = round(float(x), 1), round(float(y), 1)
        self._changed(); return True

    # -- clipboard --
    def copy_nodes(self, ids) -> str:
        """The chosen nodes (not the Output) with the links between them, as text for the clipboard."""
        ids = {i for i in ids if self.node(i) and self.node(i)["type"] != "fx_output"}
        nodes = [copy.deepcopy(n) for n in self.graph["nodes"] if n["id"] in ids]
        links = [dict(l) for l in self.graph["links"] if l["from"] in ids and l["to"] in ids]
        return json.dumps({"kind": CLIP_KIND, "nodes": nodes, "links": links})

    @staticmethod
    def parse_clip(text):
        try: d = json.loads(text)
        except Exception: return None
        if not isinstance(d, dict) or d.get("kind") != CLIP_KIND or not isinstance(d.get("nodes"), list) or not d["nodes"]: return None
        return d

    def paste(self, text, dx=40.0, dy=40.0):
        """Paste what copy_nodes made (it may come from another effect). Returns the new node ids."""
        d = self.parse_clip(text)
        if d is None: return []
        sub = normalize({"nodes": [n for n in d["nodes"] if isinstance(n, dict) and n.get("type") != "fx_output"], "links": d.get("links", [])})
        if not sub["nodes"]: return []
        self._push()
        remap = {}
        # normalize() may have given new ids to duplicates; match links by the ids that survived
        for n in sub["nodes"]:
            old = n["id"]; n = copy.deepcopy(n); n["id"] = new_id(); n["x"] = round(n["x"] + dx, 1); n["y"] = round(n["y"] + dy, 1)
            remap[old] = n["id"]; self.graph["nodes"].append(n)
        for l in sub["links"]:
            if l["from"] in remap and l["to"] in remap:
                self.graph["links"].append({"from": remap[l["from"]], "fo": l["fo"], "to": remap[l["to"]], "ti": l["ti"]})
        self._changed(); return list(remap.values())

    def duplicate(self, ids): return self.paste(self.copy_nodes(ids))

    # -- tidy up --
    def arrange(self, col_w=300.0, row_h=180.0):
        """Left to right by how far a node is from the picture source; keeps the order up-down that nodes already had."""
        nodes = self.graph["nodes"]
        if not nodes: return False
        pred = {n["id"]: [] for n in nodes}
        for l in self.graph["links"]: pred[l["to"]].append(l["from"])
        depth = {}
        def d_of(i, seen=()):
            if i in depth: return depth[i]
            if i in seen: return 0
            depth[i] = 1 + max((d_of(p, seen + (i,)) for p in pred[i]), default=-1); return depth[i]
        for n in nodes: d_of(n["id"])
        cols = {}
        for n in sorted(nodes, key=lambda n: (n["y"], n["x"])): cols.setdefault(depth[n["id"]], []).append(n)
        self._push()
        for c, col in cols.items():
            y = 0.0
            for n in col:
                n["x"] = round(40.0 + c * col_w, 1); n["y"] = round(40.0 + y, 1)
                y += max(row_h * 0.6, 34 + 26 * len(node_rows(n["type"])) + 36)
        self._changed(); return True

    # -- checks --
    def validate(self):
        """(error message or None, [warnings]) - by compiling the graph exactly as the renderer will."""
        try:
            fn = compile_effect(self.graph, [])
            return None, list(getattr(fn, "_fx_warnings", []))
        except Exception as ex:
            return (str(ex).splitlines()[0] if str(ex) else "error"), []

    def param_specs(self): return collect_param_specs(self.graph)
