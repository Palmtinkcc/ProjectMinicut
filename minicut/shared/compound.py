"""Compound clips (rewritten in this patch).

A compound clip is a normal clip (kind "compound") that carries its own little timeline: 'children' (the clips inside, with
their 'start' on the inner timeline) and 'subtracks' (the tracks they sit on). Nothing is rendered or copied when it is made.

Fast paths of this rewrite:
  * Pass-through: a compound that has no opacity / position / scale / rotation / blend / effect / mask / speed of its own is not
    drawn as a picture at all. Its children are put straight into the parent's layer list (inner_layers) and go through the
    normal compositor, GPU included. This is the common case and costs the same as the clips would outside the compound.
  * Everything else is drawn once into an off-screen layer (render/renderer.py, CompoundSource) in a single pass.
  * The waveform is computed once per compound (compound_wave) instead of for every pixel on every repaint.
"""
from .deps import *
from .core import *
from .core import _shift_keys

__all__ = ["WAVE_RATE", "compound_rate", "compound_view", "compound_identity", "inner_layers", "flatten_compounds",
           "compound_wave", "wave_signature", "wave_at"]

WAVE_RATE = 50          # waveform samples per second of inner time


def compound_rate(comp):
    """How fast the inside of a compound clip runs (1.0 = normal). With a keyframed speed: the average over the clip."""
    if not clip_has_speed(comp) or comp.get("dur", 0) <= 1e-9: return 1.0
    return max(1e-3, (src_time(comp, comp["dur"]) - comp["inp"]) / comp["dur"])


def compound_view(comp, ch):
    """A clip inside a compound clip as it must sit on the inner timeline when the compound has a speed of s: s times faster
    means it starts and ends 1/s as late, its keyframes are 1/s as far apart and its own speed is multiplied by s."""
    s = compound_rate(comp)
    if abs(s - 1.0) < 1e-9: return ch
    n = copy.deepcopy(ch); i0 = comp["inp"]
    n["start"] = i0 + (ch["start"] - i0) / s; n["dur"] = ch["dur"] / s
    for pr in n["props"].values():
        for k in pr["k"]: k["t"] = k["t"] / s
    sp = n["props"].get("speed")
    if sp is not None and n.get("kind") in SPEED_KINDS:
        sp["v"] = sp["v"] * s
        for k in sp["k"]: k["v"] = k["v"] * s
    if comp.get("pitch_follow"): n["pitch_follow"] = True
    return n


# ───────────────────────── drawing: pass-through ─────────────────────────
def compound_identity(c, lt, w, h):
    """True when drawing the compound clip c at local time lt would change nothing about its inside: normal blend, full opacity, not
    moved / scaled / turned, no effects, no speed, and the same picture size as the project (w x h). (A mask is checked by the caller.)"""
    if c.get("blend", "normal") != "normal" or clip_has_speed(c): return False
    if int(c.get("cw", w)) != w or int(c.get("chh", h)) != h: return False
    if any(e.get("on", True) for e in (c.get("effects") or ())): return False
    for k, want in (("opacity", 100.0), ("x", 0.0), ("y", 0.0), ("sx", 100.0), ("sy", 100.0), ("rot", 0.0)):
        if abs(prop_at(c, k, lt) - want) > 1e-6: return False
    return True


def inner_layers(comp, t):
    """The visible clips inside a compound clip at project time t, bottom layer first. Each is a shallow copy whose 'start' is on the
    project timeline (so the normal renderer can draw it as if it sat on the main timeline). Hidden sub-tracks are skipped."""
    ti = t - comp["start"] + comp["inp"]; off = comp["start"] - comp["inp"]; by = {}
    for k in comp.get("children", ()):
        if k["start"] <= ti < k["start"] + k["dur"]: by.setdefault(k["track"], []).append(k)
    out = []
    if not by: return out
    for tr in reversed([x for x in comp.get("subtracks", ()) if x.get("kind") == "video"]):
        if tr.get("hidden"): continue
        for k in by.get(tr["id"], ()):
            n = dict(k); n["start"] = k["start"] + off; out.append(n)
    return out


# ───────────────────────── sound: flatten for mixing ─────────────────────────
def _bake_ancestor_volume(n, ancestors):
    """Fold every ancestor compound's own volume (constant or keyframed) into n's volume."""
    const = 1.0; animated = False
    for comp, _ in ancestors:
        if comp["props"]["volume"]["k"]: animated = True
        else: const *= comp["props"]["volume"]["v"] / 100.0
    if not animated:
        if const != 1.0:
            n["props"]["volume"]["v"] = n["props"]["volume"]["v"] * const
            for k in n["props"]["volume"]["k"]: k["v"] = k["v"] * const
        return
    s, e = n["start"], n["start"] + n["dur"]; step = max(1.0 / 20, (e - s) / 200.0)
    times = []; t = s
    while t < e - 1e-9: times.append(t); t += step
    times.append(e)
    def total(t_abs):
        v = prop_at(n, "volume", t_abs - n["start"])
        for comp, abs_start in ancestors: v *= prop_at(comp, "volume", t_abs - abs_start) / 100.0
        return v
    n["props"]["volume"]["k"] = [{"t": t - n["start"], "v": total(t), "e": [0, 0, 1, 1]} for t in times]
    n["props"]["volume"]["v"] = n["props"]["volume"]["k"][0]["v"] if n["props"]["volume"]["k"] else n["props"]["volume"]["v"]


def flatten_compounds(proj):
    """A copy of the project where every compound clip (any depth) is replaced by the audio/video clips inside it, placed on the main
    timeline, with the volume of every compound they sit in folded into their own."""
    clips = getattr(proj, "clips", None)
    if not clips or not any(c.get("kind") == "compound" for c in clips): return proj
    p = copy.copy(proj); p.clips = []; p.tracks = list(proj.tracks)

    def walk(items, off, ancestors, lo, hi):
        for c in items:
            if c.get("kind") == "compound":
                if not ancestors:
                    tr = proj.track(c["track"])
                    if tr and tr.get("muted"): continue
                a, b = c["start"] + off, c["start"] + off + c["dur"]
                nlo, nhi = max(lo, a), min(hi, b)
                if nhi <= nlo: continue
                p.tracks += c.get("subtracks", [])
                kids = c.get("children", [])
                if abs(compound_rate(c) - 1.0) > 1e-9: kids = [compound_view(c, k) for k in kids]
                walk(kids, off + c["start"] - c["inp"], ancestors + [(c, a)], nlo, nhi)
            else:
                if c["kind"] not in ("audio", "video"): continue
                s, e = c["start"] + off, c["start"] + off + c["dur"]; s2, e2 = max(s, lo), min(e, hi)
                if e2 <= s2: continue
                n = copy.deepcopy(c) if (s2 > s or ancestors) else dict(c)
                n["start"], n["dur"], n["inp"] = s2, e2 - s2, c["inp"] + src_delta(c, s2 - s)
                if s2 > s: _shift_keys(n, s2 - s)
                if ancestors: _bake_ancestor_volume(n, ancestors)
                p.clips.append(n)

    walk(clips, 0.0, [], float("-inf"), float("inf"))
    return p


# ───────────────────────── waveform (computed once, then cached by the timeline) ─────────────────────────
def wave_signature(comp):
    """A cheap hashable value that changes whenever something that shapes the compound's waveform changes."""
    def vol(k):
        v = k["props"]["volume"]; sp = k["props"].get("speed") or {"v": 100, "k": []}
        return (v["v"], tuple((x["t"], x["v"]) for x in v["k"]), sp["v"], tuple((x["t"], x["v"]) for x in sp["k"]))
    muted = tuple(sorted(t["id"] for t in comp.get("subtracks", ()) if t.get("muted")))
    return (muted, tuple((k["id"], k["kind"], k.get("path"), k["track"], k["start"], k["dur"], k["inp"], vol(k),
                         wave_signature(k) if k["kind"] == "compound" else None) for k in comp.get("children", ())))


def compound_wave(comp, peaks_of, gain, depth=0):
    """(curve, t0, ok): loudness 0..1 of everything inside the compound, WAVE_RATE samples per second of INNER time starting at t0.
    peaks_of(path) -> array of peaks at 100 per second, or None while it is still being read (then ok is False: do not cache)."""
    ok = True; kids = comp.get("children", ())
    if depth > 6 or not kids: return np.zeros(1, np.float32), 0.0, True
    muted = {t["id"] for t in comp.get("subtracks", ()) if t.get("muted")}
    t0 = min(k["start"] for k in kids); t1 = max(k["start"] + k["dur"] for k in kids)
    n = max(1, int(math.ceil((t1 - t0) * WAVE_RATE))); out = np.zeros(n, np.float32)
    for k in kids:
        if k["track"] in muted: continue
        i0 = max(0, int((k["start"] - t0) * WAVE_RATE)); i1 = min(n, int(math.ceil((k["start"] + k["dur"] - t0) * WAVE_RATE)))
        if i1 <= i0: continue
        lts = (np.arange(i0, i1) / float(WAVE_RATE) + t0) - k["start"]; lts = np.clip(lts, 0.0, k["dur"])
        vp = k["props"]["volume"]
        vol = (np.array([prop_at(k, "volume", float(x)) for x in lts]) if vp["k"] else np.full(len(lts), vp["v"], np.float64)) / 100.0
        if k["kind"] == "compound":
            sub, s0, sok = compound_wave(k, peaks_of, gain, depth + 1); ok = ok and sok
            idx = np.rint((src_time_arr(k, lts) - s0) * WAVE_RATE).astype(int)
            good = (idx >= 0) & (idx < len(sub)); a = np.zeros(len(lts)); a[good] = sub[idx[good]] * vol[good]
        elif k["kind"] in ("audio", "video") and k.get("path"):
            pk = peaks_of(k["path"])
            if pk is None: ok = False; continue
            if not len(pk): continue
            idx = (src_time_arr(k, lts) * 100).astype(int); good = (idx >= 0) & (idx < len(pk)); a = np.zeros(len(lts))
            a[good] = np.minimum(1.0, np.asarray(pk)[idx[good]] * gain * vol[good])
        else: continue
        out[i0:i1] += a.astype(np.float32)
    return np.minimum(out, 1.0), float(t0), ok


def wave_at(curve, t0, t_inner):
    """Loudness of a compound waveform at inner time t_inner."""
    i = int(round((t_inner - t0) * WAVE_RATE))
    return float(curve[i]) if 0 <= i < len(curve) else 0.0
