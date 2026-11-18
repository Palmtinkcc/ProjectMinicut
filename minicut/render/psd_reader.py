"""A small Photoshop (.psd) reader for Bone2D: every layer as a picture with its place, opacity, visibility and folder.
No extra package needed. 8 / 16 bit RGB files, RAW / RLE / ZIP layer data.
read_psd(path) -> (canvas_w, canvas_h, layers), layers bottom to top: {"name", "x", "y", "img" (BGRA uint8, straight alpha), "opacity" 0..100,
"visible", "group": [folder names, outer first]}."""
import struct, zlib
import numpy as np


class PSDError(Exception): pass


def _unrle(body, h, counts):
    rows = []; pos = 0
    for n in counts:
        chunk = body[pos:pos + n]; pos += n; row = bytearray(); i = 0
        while i < len(chunk):
            c = chunk[i]; i += 1
            if c < 128: row += chunk[i:i + c + 1]; i += c + 1
            elif c > 128 and i < len(chunk): row += chunk[i:i + 1] * (257 - c); i += 1
        rows.append(bytes(row))
    return rows


def _channel(buf, off, length, w, h, depth):
    """One channel (compression word first) -> (h, w) uint8."""
    if w == 0 or h == 0 or length < 2: return np.zeros((max(h, 0), max(w, 0)), np.uint8)
    comp, = struct.unpack(">H", buf[off:off + 2]); body = buf[off + 2:off + length]; bps = depth // 8; rowlen = w * bps
    if comp == 0: raw = body[:rowlen * h]
    elif comp == 1:
        counts = struct.unpack(">%dH" % h, body[:2 * h]); raw = b"".join(r[:rowlen].ljust(rowlen, b"\0") for r in _unrle(body[2 * h:], h, counts))
    elif comp in (2, 3):
        raw = zlib.decompress(body)
        if comp == 3:                                                          # ZIP with prediction: undo the delta
            a = np.frombuffer(raw, np.uint8 if bps == 1 else ">u2", count=w * h).reshape(h, w); raw = np.cumsum(a, axis=1, dtype=a.dtype).astype(a.dtype).tobytes()
    else: raise PSDError("unknown compression %d" % comp)
    if bps == 1: return np.frombuffer(raw, np.uint8, count=w * h).reshape(h, w)
    return (np.frombuffer(raw, ">u2", count=w * h).reshape(h, w) >> 8).astype(np.uint8)


def read_psd(path):
    with open(path, "rb") as f: buf = f.read()
    if buf[:4] != b"8BPS": raise PSDError("not a PSD file")
    if struct.unpack(">H", buf[4:6])[0] != 1: raise PSDError("PSB (large document) files are not supported")
    nch, H, W, depth, mode = struct.unpack(">HIIHH", buf[12:26])
    if depth not in (8, 16): raise PSDError("only 8 and 16 bit files are supported")
    pos = 26
    for _ in range(2): n, = struct.unpack(">I", buf[pos:pos + 4]); pos += 4 + n   # colour mode data, image resources
    n, = struct.unpack(">I", buf[pos:pos + 4]); pos += 4
    if n == 0: raise PSDError("this PSD has no layers (it is flattened)")
    pos += 4                                                                      # length of the layer info
    cnt, = struct.unpack(">h", buf[pos:pos + 2]); pos += 2; cnt = abs(cnt); recs = []
    for _ in range(cnt):
        top, left, bottom, right, k = struct.unpack(">iiiiH", buf[pos:pos + 18]); pos += 18; chans = []
        for _c in range(k): cid, clen = struct.unpack(">hI", buf[pos:pos + 6]); pos += 6; chans.append((cid, clen))
        pos += 8                                                                  # '8BIM' + blend mode key
        opacity, clip, flags, _f = struct.unpack(">BBBB", buf[pos:pos + 4]); pos += 4
        ex, = struct.unpack(">I", buf[pos:pos + 4]); pos += 4; exend = pos + ex
        m, = struct.unpack(">I", buf[pos:pos + 4]); pos += 4 + m                  # layer mask data
        b, = struct.unpack(">I", buf[pos:pos + 4]); pos += 4 + b                  # blending ranges
        nl = buf[pos]; name = buf[pos + 1:pos + 1 + nl].decode("latin-1", "replace"); pos += (1 + nl + 3) // 4 * 4; section = 0
        while pos + 12 <= exend:
            key = buf[pos + 4:pos + 8]; ln, = struct.unpack(">I", buf[pos + 8:pos + 12]); data = buf[pos + 12:pos + 12 + ln]; pos += 12 + (ln + 3) // 4 * 4
            if key == b"luni" and len(data) >= 4:
                kk, = struct.unpack(">I", data[:4]); name = data[4:4 + 2 * kk].decode("utf-16-be", "replace").rstrip("\0") or name
            elif key == b"lsct" and len(data) >= 4: section, = struct.unpack(">I", data[:4])
        pos = exend
        recs.append({"rect": (top, left, bottom, right), "chans": chans, "opacity": opacity, "flags": flags, "name": name, "section": section, "groups": []})
    # the folders: a divider (3) opens a group, the folder record (1 / 2) that follows its children closes it and names it
    stack = []
    for i, r in enumerate(recs):
        if r["section"] == 3: stack.append([])
        elif r["section"] in (1, 2):
            if stack:
                for j in stack.pop(): recs[j]["groups"].insert(0, r["name"])
        else:
            for fr in stack: fr.append(i)
    layers = []
    for r in recs:
        top, left, bottom, right = r["rect"]; w = max(0, right - left); h = max(0, bottom - top); planes = {}
        for cid, clen in r["chans"]:
            if cid in (0, 1, 2, -1) and w and h and r["section"] == 0:
                try: planes[cid] = _channel(buf, pos, clen, w, h, depth)
                except Exception: planes[cid] = None
            pos += clen
        if r["section"] != 0 or not w or not h or any(planes.get(c) is None for c in (0, 1, 2)): continue
        img = np.zeros((h, w, 4), np.uint8); img[..., 2] = planes[0]; img[..., 1] = planes[1]; img[..., 0] = planes[2]; a = planes.get(-1); img[..., 3] = a if a is not None else 255
        if not img[..., 3].any(): continue
        layers.append({"name": r["name"], "x": left, "y": top, "img": img, "opacity": r["opacity"] / 255.0 * 100.0, "visible": not (r["flags"] & 2), "group": r["groups"]})
    return W, H, layers
