"""Pure data helpers for timeline editing: rolling trim (drag the border between two clips), closing gaps, moving a
group together when one of its clips is trimmed, and the quick volume line drawn on a clip. No Qt here, so these are
easy to test and to reuse from both the mouse handlers and any future command (e.g. a keyboard shortcut)."""
import copy


def touches(a_end, b_start, fps):
    return abs(a_end - b_start) <= 0.5 / fps


def track_clips(clips, track_id, exclude_id=None):
    return sorted((c for c in clips if c["track"] == track_id and c["id"] != exclude_id), key=lambda c: c["start"])


def neighbor_before(clips, track_id, clip_id, start):
    best = None
    for c in track_clips(clips, track_id, clip_id):
        end = c["start"] + c["dur"]
        if end <= start + 1e-6 and (best is None or end > best["start"] + best["dur"]): best = c
    return best


def neighbor_after(clips, track_id, clip_id, end):
    best = None
    for c in track_clips(clips, track_id, clip_id):
        if c["start"] >= end - 1e-6 and (best is None or c["start"] < best["start"]): best = c
    return best


def _shift_keys(clip, delta):
    for pr in clip.get("props", {}).values():
        for k in pr.get("k", []): k["t"] = k["t"] + delta


def _has_source(c): return c["kind"] in ("video", "audio") and c.get("src_dur", 0) > 0


def trim_l_bounds(c, prev, fps):
    """How far left and right c's LEFT edge may move. Moving it left grows c (needs c's own source) and shrinks a
    touching previous clip (always possible, down to one frame). Moving it right shrinks c and grows the previous
    clip (needs the previous clip's own source, if it has one). With a non-touching previous clip (a gap), the edge
    may only move down to the previous clip's end: there is nothing there to roll."""
    lo = 0.0
    if _has_source(c): lo = max(lo, c["start"] - c["inp"])
    hi = c["start"] + c["dur"] - 1.0 / fps
    if prev is not None:
        prev_end = prev["start"] + prev["dur"]
        if touches(prev_end, c["start"], fps):
            lo = max(lo, prev["start"] + 1.0 / fps)
            if _has_source(prev): hi = min(hi, prev["start"] + (prev.get("src_dur", 0) - prev.get("inp", 0.0)))
        else:
            lo = max(lo, prev_end)
    return lo, hi


def trim_r_bounds(c, nxt, fps):
    """How far left and right c's RIGHT edge may move: the mirror image of trim_l_bounds."""
    lo = c["start"] + 1.0 / fps
    hi = c["start"] + (c.get("src_dur", 0) - c["inp"]) if _has_source(c) else float("inf")
    if nxt is not None:
        if touches(c["start"] + c["dur"], nxt["start"], fps):
            hi = min(hi, nxt["start"] + nxt["dur"] - 1.0 / fps)
            if _has_source(nxt): lo = max(lo, nxt["start"] - nxt.get("inp", 0.0))
        else:
            hi = min(hi, nxt["start"])
    return lo, hi


def apply_trim_l(c, ns, fps, prev=None, roll=True):
    """Move c's left edge to ns (already clamped by trim_l_bounds). If a clip touches c's old left edge and roll is
    on, its right edge (and duration) changes by the same amount, so the two clips stay joined with no gap or
    overlap. Returns the delta applied to c's start (0 if nothing moved)."""
    old_start = c["start"]; ns = max(ns, old_start - c["dur"] + 1 / fps)
    delta = ns - old_start
    if abs(delta) < 1e-9: return 0.0
    c["start"] = ns; c["dur"] = old_start + c["dur"] - ns
    if _has_source(c): c["inp"] = max(0.0, c["inp"] + delta)
    _shift_keys(c, -delta)
    if roll and prev is not None and touches(prev["start"] + prev["dur"], old_start, fps):
        prev["dur"] = prev["dur"] + delta
    return delta


def apply_trim_r(c, ne, fps, nxt=None, roll=True):
    """Move c's right edge to ne (already clamped by trim_r_bounds). A touching next clip is rolled the same way."""
    old_end = c["start"] + c["dur"]; ne = max(ne, c["start"] + 1 / fps)
    delta = ne - old_end
    if abs(delta) < 1e-9: return 0.0
    c["dur"] = ne - c["start"]
    if roll and nxt is not None and touches(old_end, nxt["start"], fps):
        nxt["start"] = nxt["start"] + delta
        if _has_source(nxt): nxt["inp"] = max(0.0, nxt["inp"] + delta)
        nxt["dur"] = nxt["dur"] - delta
        _shift_keys(nxt, -delta)
    return delta


def group_ids_of(clips, clip):
    g = clip.get("group")
    return {o["id"] for o in clips if g and o.get("group") == g} | {clip["id"]}


def propagate_group_delta(clips, clip, delta, exclude_ids=()):
    """A grouped clip's start moved by delta (e.g. a left trim): move every other member of the group by the same
    amount, so the group's relative timing stays the same. Clamped so no member's start goes negative."""
    if abs(delta) < 1e-9: return
    ids = group_ids_of(clips, clip) - {clip["id"]} - set(exclude_ids)
    if not ids: return
    members = [c for c in clips if c["id"] in ids]
    if delta < 0:
        lo = min((c["start"] for c in members), default=0.0)
        if lo + delta < 0: delta = -lo
    for c in members: c["start"] = max(0.0, c["start"] + delta)


def close_gaps(clips, track_ids, fps):
    """Shift the clips of the given tracks left so there is no gap between them (the first clip of each track keeps
    its own position). Each track is closed on its own. Returns the clips that moved, with their old start."""
    moved = []
    for tid in track_ids:
        cursor = None
        for c in track_clips(clips, tid):
            if cursor is None: cursor = c["start"] + c["dur"]; continue
            if c["start"] > cursor + 0.5 / fps:
                moved.append((c, c["start"])); c["start"] = cursor
            cursor = c["start"] + c["dur"]
    return moved


# ---- the quick volume line drawn on a clip (band is the clip's own rectangle on screen) ----
def vol_to_y(v, band_top, band_bottom):
    v = max(0.0, min(200.0, v))
    return band_bottom - v / 200.0 * (band_bottom - band_top)


def y_to_vol(y, band_top, band_bottom):
    h = max(1.0, band_bottom - band_top)
    v = (band_bottom - y) / h * 200.0
    return max(0.0, min(200.0, v))
