"""GLSL effect library (Patch 35): the "instructions" the GPU runs for each effect.

How to add an effect
--------------------
    1. Write a builder  b_xxx(p, c, w, h, opaque) -> Built | None
         p       the cleaned effect parameters (same dict the CPU function gets)
         c       .k (preview scale), .lt (clip time), .fast
         w, h    picture size in pixels
         opaque  True when no pixel is transparent
       It returns a list of Pass objects (see glfx.py) wrapped in Built(passes, alpha=<writes the alpha plane>), or None when this
       combination of parameters is not handled (the CPU function then runs, so nothing is ever lost).
    2. Add it to GL_FX = {"effect type": builder}.
That is all: the engine uploads the picture once, runs the passes of every effect in the run, and reads the result back once.

Conventions
-----------
  * Pictures are stored B, G, R, A: in a shader c.rgb is (B, G, R).  Colour uniforms are therefore passed as (blue, green, red).
  * v_uv is image coordinates (row 0 = v 0); gl_FragCoord.xy is the pixel index; u_size is the size of the pass's own target.
  * The looks match the 8-bit CPU versions in fastfx.py (same formulas, same constants).  Every blur works on a shrunken copy for big
    radii exactly like the CPU version, so the cost stays small for any radius.
"""
import math

from ..shared.deps import QColor
from .glfx import Pass, Built

# ───────────────────────── shader source ─────────────────────────
HEAD = """#version 330
in vec2 v_uv; out vec4 o;
uniform vec2 u_size;
uniform sampler2D u_in;
float lum(vec3 c) { return dot(c, vec3(0.114, 0.587, 0.299)); }
vec3 bgr2hsv(vec3 c) {                       // c = (B,G,R) -> (h turns 0..1, s, v)
    float B = c.r, G = c.g, R = c.b;
    float mx = max(R, max(G, B)), mn = min(R, min(G, B)), d = mx - mn, h = 0.0;
    if (d > 1e-6) {
        if (mx == R) h = mod((G - B) / d, 6.0); else if (mx == G) h = (B - R) / d + 2.0; else h = (R - G) / d + 4.0;
        h /= 6.0;
    }
    return vec3(h, mx > 1e-6 ? d / mx : 0.0, mx);
}
vec3 hsv2bgr(vec3 hsv) {
    vec3 rgb = clamp(abs(mod(fract(hsv.x) * 6.0 + vec3(0.0, 4.0, 2.0), 6.0) - 3.0) - 1.0, 0.0, 1.0);
    return (hsv.z * mix(vec3(1.0), rgb, hsv.y)).bgr;
}
uint hsh(uint x) { x ^= x >> 16; x *= 0x7feb352du; x ^= x >> 15; x *= 0x846ca68bu; x ^= x >> 16; return x; }
float rnd(uvec2 p, uint seed) { return float(hsh(p.x * 1973u + p.y * 9277u + seed * 26699u + 911u)) * (1.0 / 4294967295.0); }
"""


def _fs(body):
    return HEAD + body


def _bgr(col):
    q = QColor(col)
    return (q.blueF(), q.greenF(), q.redF())


# ───────────────────────── colour ─────────────────────────
_TINT = _fs("""uniform vec3 u_col; uniform float u_a;
void main() { vec4 c = texture(u_in, v_uv); float g = lum(c.rgb);
  vec3 t = mix(2.0 * g * u_col, 1.0 - 2.0 * (1.0 - g) * (1.0 - u_col), step(0.5, g));
  o = vec4(mix(c.rgb, t, u_a), c.a); }""")


def b_tint(p, c, w, h, opaque):
    a = p["amount"] / 100.0
    if a <= 0: return Built([])
    return Built([Pass(_TINT, {"u_col": _bgr(p["color"]), "u_a": a})])


_BW = _fs("""uniform float u_a;
void main() { vec4 c = texture(u_in, v_uv); o = vec4(mix(c.rgb, vec3(lum(c.rgb)), u_a), c.a); }""")


def b_bw(p, c, w, h, opaque):
    a = p["amount"] / 100.0
    return Built([Pass(_BW, {"u_a": a})] if a > 0 else [])


_INV = _fs("""uniform float u_a;
void main() { vec4 c = texture(u_in, v_uv); o = vec4(mix(c.rgb, 1.0 - c.rgb, u_a), c.a); }""")


def b_invert(p, c, w, h, opaque):
    a = p["amount"] / 100.0
    return Built([Pass(_INV, {"u_a": a})] if a > 0 else [])


_ADJ = _fs("""uniform float u_br, u_co, u_t, u_hi, u_sh, u_hu, u_sa, u_vib;
void main() {
  vec4 c = texture(u_in, v_uv);
  vec3 base = (c.rgb - 0.5) * u_co + 0.5 + u_br;                    // brightness + contrast (per channel)
  vec3 x = clamp(base + vec3(-u_t, 0.0, u_t), 0.0, 1.0);            // temperature: B down, R up
  float l = lum(x);                                                  // highlights / shadows
  x = clamp(x + clamp((l - 0.5) * 2.0, 0.0, 1.0) * u_hi + clamp((0.5 - l) * 2.0, 0.0, 1.0) * u_sh, 0.0, 1.0);
  if (u_sa != 1.0 || u_hu != 0.0 || u_vib != 0.0) {
    vec3 hsv = bgr2hsv(x); hsv.x += u_hu / 360.0; hsv.y = clamp(hsv.y * u_sa, 0.0, 1.0);
    hsv.y = clamp(hsv.y + (1.0 - hsv.y) * u_vib, 0.0, 1.0); x = hsv2bgr(hsv);
  }
  o = vec4(clamp(x, 0.0, 1.0), c.a); }""")


def b_adjust(p, c, w, h, opaque):
    br, co, sa, hu = p["brightness"], p["contrast"], p["saturation"], p["hue"]
    t, vib, hi, sh = p.get("temperature", 0.0), p.get("vibrance", 0.0), p.get("highlights", 0.0), p.get("shadows", 0.0)
    if br == 0 and co == 0 and sa == 0 and hu == 0 and t == 0 and vib == 0 and hi == 0 and sh == 0: return Built([])
    return Built([Pass(_ADJ, {"u_br": br / 200.0, "u_co": 1 + co / 100.0, "u_t": t / 100.0 * 0.15, "u_hi": hi / 200.0, "u_sh": sh / 200.0,
                              "u_hu": float(hu), "u_sa": 1 + sa / 100.0, "u_vib": vib / 100.0})])


_HUE = _fs("""uniform float u_hu;
void main() { vec4 c = texture(u_in, v_uv); vec3 hsv = bgr2hsv(c.rgb); hsv.x += u_hu / 360.0; o = vec4(hsv2bgr(hsv), c.a); }""")


def b_hue_shift(p, c, w, h, opaque):
    return Built([Pass(_HUE, {"u_hu": float(p["shift"])})] if p["shift"] != 0 else [])


_TEMP = _fs("""uniform float u_t, u_ti;
void main() { vec4 c = texture(u_in, v_uv); float r = clamp(c.b + u_t, 0.0, 1.0), g = clamp(c.g + u_ti, 0.0, 1.0);
  float b = clamp(clamp(c.r - u_t, 0.0, 1.0) - u_ti, 0.0, 1.0); o = vec4(b, g, r, c.a); }""")


def b_color_temperature(p, c, w, h, opaque):
    t = p["temperature"] / 100.0; ti = p.get("tint", 0.0) / 100.0
    if t == 0 and ti == 0: return Built([])
    return Built([Pass(_TEMP, {"u_t": t * 30 / 255.0, "u_ti": ti * 20 / 255.0})])


_HS = _fs("""uniform float u_hi, u_sh;
void main() { vec4 c = texture(u_in, v_uv); float l = lum(c.rgb);
  o = vec4(clamp(c.rgb + clamp((l - 0.5) * 2.0, 0.0, 1.0) * u_hi + clamp((0.5 - l) * 2.0, 0.0, 1.0) * u_sh, 0.0, 1.0), c.a); }""")


def b_highlights_shadows(p, c, w, h, opaque):
    hi = p["highlights"] / 100.0; sh = p["shadows"] / 100.0
    if hi == 0 and sh == 0: return Built([])
    return Built([Pass(_HS, {"u_hi": hi * 0.5, "u_sh": sh * 0.5})])


_POST = _fs("""uniform float u_n;
void main() { vec4 c = texture(u_in, v_uv); o = vec4(floor(c.rgb * u_n + 0.5) / u_n, c.a); }""")


def b_posterize(p, c, w, h, opaque):
    return Built([Pass(_POST, {"u_n": float(max(2, int(p["levels"])) - 1)})])


_THR = _fs("""uniform float u_lv; uniform int u_inv;
void main() { vec4 c = texture(u_in, v_uv); float on = floor(lum(c.rgb) * 255.0 + 0.5) >= u_lv ? 1.0 : 0.0;
  if (u_inv == 1) on = 1.0 - on; o = vec4(vec3(on), c.a); }""")


def b_threshold(p, c, w, h, opaque):
    return Built([Pass(_THR, {"u_lv": float(int(p["level"])), "u_inv": 1 if p.get("invert", False) else 0})])


_GMAP = _fs("""uniform vec3 u_lo, u_hi; uniform float u_a;
void main() { vec4 c = texture(u_in, v_uv); vec3 m = mix(u_lo, u_hi, lum(c.rgb)); o = vec4(mix(c.rgb, m, u_a), c.a); }""")


def b_gradient_map(p, c, w, h, opaque):
    return Built([Pass(_GMAP, {"u_lo": _bgr(p.get("color_lo", "#000000")), "u_hi": _bgr(p.get("color_hi", "#ffffff")),
                               "u_a": p.get("amount", 100.0) / 100.0})])


_LKEY = _fs("""uniform float u_thr, u_soft; uniform int u_bright;
void main() { vec4 c = texture(u_in, v_uv); float l = lum(c.rgb);
  float k = u_bright == 1 ? clamp((u_thr - l) / u_soft, 0.0, 1.0) : clamp((l - u_thr) / u_soft, 0.0, 1.0);
  o = vec4(c.rgb, c.a * k); }""")


def b_luma_key(p, c, w, h, opaque):
    return Built([Pass(_LKEY, {"u_thr": p["threshold"] / 100.0, "u_soft": max(0.001, p.get("softness", 10.0) / 100.0),
                               "u_bright": 1 if p.get("mode", "dark") == "bright" else 0})], alpha=True)


_CHROMA = _fs("""uniform float u_kh, u_ks, u_tol;
void main() { vec4 c = texture(u_in, v_uv); vec3 hsv = bgr2hsv(c.rgb);
  float dh = abs(hsv.x * 360.0 - u_kh); dh = min(dh, 360.0 - dh);          // 0..180 (same scale as the CPU hue distance)
  float ds = abs(hsv.y - u_ks) * 255.0; float m = max(dh, ds);
  o = vec4(c.rgb, c.a * clamp((m - u_tol) / max(1.0, u_tol), 0.0, 1.0)); }""")


def b_chroma(p, c, w, h, opaque):
    q = QColor(p["color"]); kh = max(0.0, q.hsvHueF()) * 360.0
    return Built([Pass(_CHROMA, {"u_kh": kh, "u_ks": q.hsvSaturationF(), "u_tol": float(int(p["tolerance"]))})], alpha=True)


# ───────────────────────── blur family ─────────────────────────
_DOWN = """uniform vec2 u_foot; uniform ivec2 u_n;
void main() {
  vec4 acc = vec4(0.0);
  for (int j = 0; j < u_n.y; j++) for (int i = 0; i < u_n.x; i++) {
    vec2 off = (vec2((float(i) + 0.5) / float(u_n.x), (float(j) + 0.5) / float(u_n.y)) - 0.5) * u_foot;
    acc += texture(u_in, v_uv + off);
  }
  vec4 col4 = acc / float(u_n.x * u_n.y); vec3 col = col4.rgb;
  //POST
  o = vec4(col, col4.a); }"""
_BLUR1D = _fs("""uniform vec2 u_dir; uniform float u_sig; uniform int u_r;
void main() { vec3 acc = vec3(0.0); float ws = 0.0;
  for (int i = -u_r; i <= u_r; i++) { float wt = exp(-0.5 * float(i * i) / (u_sig * u_sig)); acc += texture(u_in, v_uv + u_dir * float(i)).rgb * wt; ws += wt; }
  o = vec4(acc / ws, 1.0); }""")
_COPY = _fs("void main() { o = texture(u_in, v_uv); }")


def _down_frag(post=""):
    return _fs(_DOWN.replace("//POST", post))


_DOWN_PLAIN = _down_frag()


def down_pass(src, w, h, sw, sh, out, frag=None):
    """Area-average the picture down to sw x sh (bilinear taps on a 2-texel lattice = an exact box filter for whole ratios)."""
    nx = max(1, min(8, int(math.ceil(w / float(sw) / 2.0)))); ny = max(1, min(8, int(math.ceil(h / float(sh) / 2.0))))
    return Pass(frag or _DOWN_PLAIN, {"u_foot": (1.0 / sw, 1.0 / sh), "u_n": (nx, ny)}, {"u_in": src}, out, (sw, sh))


def _shrink(s):
    return 1 if s < 3.0 else int(min(8, max(2, s / 1.5)))


def gauss_chain(w, h, sx, sy, src="in", prefix="g", shrink=True):
    """Passes of a Gaussian blur of sigma (sx, sy) like fastfx.gauss_u8. Returns (passes, target of the result, its size).
    The result may be smaller than the picture (the consumer reads it with linear filtering = the resize back up)."""
    passes = []; cur = src; cw, ch = w, h
    fx = _shrink(sx) if (shrink and sx >= 0.3) else 1; fy = _shrink(sy) if (shrink and sy >= 0.3) else 1
    tx, ty = sx, sy
    if fx > 1 or fy > 1:
        sw, sh = max(1, w // fx), max(1, h // fy); rx, ry = w / float(sw), h / float(sh)
        passes.append(down_pass(src, w, h, sw, sh, prefix + "d")); cur = prefix + "d"; cw, ch = sw, sh
        tx = math.sqrt(max(sx * sx - rx * rx * 0.25, 0.04)) / rx if sx >= 0.3 else 0.0
        ty = math.sqrt(max(sy * sy - ry * ry * 0.25, 0.04)) / ry if sy >= 0.3 else 0.0
    for axis, s in ((0, tx), (1, ty)):
        if s < 0.3: continue
        name = "%s%d" % (prefix, axis)
        passes.append(Pass(_BLUR1D, {"u_dir": (1.0 / cw, 0.0) if axis == 0 else (0.0, 1.0 / ch), "u_sig": float(s), "u_r": max(1, min(31, int(s * 3)))},
                           {"u_in": cur}, name, (cw, ch)))
        cur = name
    return passes, cur, (cw, ch)


def b_blur(p, c, w, h, opaque):
    amt = p["amount"] * c.k
    if amt < 0.3: return Built([])
    sx = amt * p["x_blur"] / 100.0; sy = amt * p["y_blur"] / 100.0
    if sx < 0.3 and sy < 0.3: return Built([])
    if not opaque: return None                                   # transparent edges need premultiplied pixels: the CPU function does that
    if abs(sx - sy) < 0.5: sy = sx
    passes, cur, (cw, ch) = gauss_chain(w, h, sx, sy)
    if (cw, ch) == (w, h): passes[-1].out = "main"
    else: passes.append(Pass(_COPY, {}, {"u_in": cur}, "main"))
    return Built(passes)


_MBLUR = _fs("""uniform vec2 u_step; uniform int u_n; uniform float u_t0;
void main() { vec3 acc = vec3(0.0); float cov = 0.0;
  for (int i = 0; i < u_n; i++) {
    vec2 uv = v_uv + u_step * (u_t0 + float(i));
    cov += (uv.x >= 0.0 && uv.x <= 1.0 && uv.y >= 0.0 && uv.y <= 1.0) ? 1.0 : 0.0;
    acc += texture(u_in, clamp(uv, 0.0, 1.0)).rgb;
  }
  o = vec4(acc / float(u_n), cov / float(u_n)); }""")


def b_motion_blur(p, c, w, h, opaque):
    n = int(p["length"] * c.k)
    if n < 2: return Built([])
    if not opaque: return None
    n = min(n, max(h, w) // 2); bidir = bool(p.get("bidirectional", False)); a = math.radians(p["angle"])
    sc = max(1.0, n / 9.0); sw, sh = (max(1, int(w / sc)), max(1, int(h / sc))) if sc > 1 else (w, h)
    m = max(3, int(round(n / sc))) | 1
    taps, t0 = (m, -(m // 2)) if bidir else (m // 2 + 1, 0)
    passes = []; src = "in"
    if sc > 1: passes.append(down_pass("in", w, h, sw, sh, "md")); src = "md"
    passes.append(Pass(_MBLUR, {"u_step": (math.cos(a) / sw, math.sin(a) / sh), "u_n": min(taps, 64), "u_t0": float(t0)}, {"u_in": src}, "mb", (sw, sh)))
    passes.append(Pass(_COPY, {}, {"u_in": "mb"}, "main"))
    return Built(passes, alpha=True)


_RADIAL = _fs("""uniform int u_mode, u_n; uniform float u_zam, u_amax; uniform vec2 u_c;
void main() { vec3 acc = vec3(0.0); float cov = 0.0;
  for (int i = 0; i < u_n; i++) {
    float t = float(i) / float(max(u_n - 1, 1)); vec2 q;
    t -= 0.5;                                              // centred on 0 / scale 1: the sharp picture stays where it is
    if (u_mode == 0) { q = u_c + (v_uv - u_c) / (1.0 + u_zam * t); }
    else { float a = u_amax * t, cs = cos(a), sn = sin(a); vec2 d = (v_uv - u_c) * u_size; q = u_c + vec2(cs * d.x + sn * d.y, -sn * d.x + cs * d.y) / u_size; }
    cov += (q.x >= 0.0 && q.x <= 1.0 && q.y >= 0.0 && q.y <= 1.0) ? 1.0 : 0.0;
    acc += texture(u_in, clamp(q, 0.0, 1.0)).rgb;
  }
  o = vec4(acc / float(u_n), u_mode == 1 ? cov / float(u_n) : 1.0); }""")


def _steps(disp, fast):
    return int(max(4, min(10 if fast else 14, disp * 0.5 + 2)))


def _radial(w, h, c, mode, zam, amax, cx, cy, disp_fn):
    sc = 2 if min(w, h) >= 240 else 1                  # the CPU version counts its steps on a half-size picture: same count here
    n = _steps(disp_fn(max(1, w // sc), max(1, h // sc)), c.fast)
    return Built([Pass(_RADIAL, {"u_mode": mode, "u_n": n, "u_zam": float(zam), "u_amax": float(amax), "u_c": (cx, cy)})], alpha=(mode == 1))


def b_radial_blur(p, c, w, h, opaque):
    amt = p["amount"] / 100.0
    if amt <= 0.002: return Built([])
    if not opaque: return None
    spin = p.get("mode", "zoom") == "spin"; cx, cy = p["cx"] / 100.0, p["cy"] / 100.0
    if spin: return _radial(w, h, c, 1, 0, amt * 0.3, cx, cy, lambda a, b: amt * 0.3 * math.hypot(a, b) / 2)
    return _radial(w, h, c, 0, amt * 0.25, 0, cx, cy, lambda a, b: amt * 0.25 * max(a, b) / 2)


def b_zoom_blur(p, c, w, h, opaque):
    amt = p["amount"] / 100.0
    if amt <= 0.001: return Built([])
    if not opaque: return None
    return _radial(w, h, c, 0, amt * 0.5, 0, p.get("cx", 50.0) / 100.0, p.get("cy", 50.0) / 100.0, lambda a, b: amt * 0.5 * max(a, b) / 2)


def b_spin_blur(p, c, w, h, opaque):
    ang = p["angle"]
    if abs(ang) < 0.1: return Built([])
    if not opaque: return None
    return _radial(w, h, c, 1, 0, math.radians(ang), p.get("cx", 50.0) / 100.0, p.get("cy", 50.0) / 100.0,
                   lambda a, b: abs(math.radians(ang)) * math.hypot(a, b) / 2)


# ───────────────────────── distort ─────────────────────────
_RGBS = _fs("""uniform int u_mode; uniform float u_d; uniform vec2 u_c, u_dir;
void main() {
  vec2 sz = u_size, p = v_uv * sz - 0.5, pr = p, pb = p;
  if (u_mode == 0) { pr = p - u_dir; pb = p + u_dir; }
  else if (u_mode == 1) { float sr = 1.0 + u_d / sz.x, sb = 1.0 - u_d / sz.x; pr = u_c + (p - u_c) / sr; if (sb > 0.0) pb = u_c + (p - u_c) / sb; }
  else { vec2 n = (p - u_c) / (sz * 0.5); float ln = max(length(n), 1e-5); vec2 u = n / ln * u_d; pr = p + u; pb = p - u; }
  vec4 c = texture(u_in, v_uv);
  o = vec4(texture(u_in, (pb + 0.5) / sz).r, c.g, texture(u_in, (pr + 0.5) / sz).b, c.a); }""")


def b_rgb_split(p, c, w, h, opaque):
    d = p["amount"] * c.k
    if d < 0.3: return Built([])
    mode = p.get("mode", "directional"); th = math.radians(p["angle"])
    u = {"u_mode": {"directional": 0, "zoom": 1, "radial": 2}.get(mode, 0), "u_d": float(d),
         "u_c": (w * p.get("cx", 50.0) / 100.0, h * p.get("cy", 50.0) / 100.0), "u_dir": (math.cos(th) * d, math.sin(th) * d)}
    return Built([Pass(_RGBS, u)])


_PIX = _fs("""uniform vec2 u_k;                         // small size / picture size
void main() { ivec2 p = ivec2(gl_FragCoord.xy); o = texelFetch(u_in, ivec2(floor(vec2(p) * u_k)), 0); }""")


def b_pixelate(p, c, w, h, opaque):
    s = max(1, int(round(p["size"] * c.k)))
    if s <= 1: return Built([])
    sw, sh = max(1, w // s), max(1, h // s)
    return Built([down_pass("in", w, h, sw, sh, "px"), Pass(_PIX, {"u_k": (sw / float(w), sh / float(h))}, {"u_in": "px"}, "main")])


# ───────────────────────── stylize ─────────────────────────
_SHARP = _fs("""uniform sampler2D u_blur; uniform float u_a;
void main() { vec4 c = texture(u_in, v_uv); o = vec4(clamp(c.rgb * (1.0 + u_a) - texture(u_blur, v_uv).rgb * u_a, 0.0, 1.0), c.a); }""")


def b_sharpen(p, c, w, h, opaque):
    a = p["amount"] / 100.0
    if a <= 0: return Built([])
    if p.get("threshold", 0.0) > 0: return None
    r = max(0.4, p.get("radius", 1.0) * c.k)
    passes, cur, _ = gauss_chain(w, h, r, r, prefix="s")
    passes.append(Pass(_SHARP, {"u_a": a}, {"u_in": "in", "u_blur": cur}, "main"))
    return Built(passes)


_VIG = _fs("""uniform float u_a, u_start, u_rnd; uniform int u_mode; uniform vec3 u_col;
void main() { vec4 c = texture(u_in, v_uv); vec2 n = v_uv * 2.0 - 1.0;
  float r = mix(max(abs(n.x), abs(n.y)), length(n) / 1.4142, u_rnd);
  float m = clamp((r - u_start) / max(1e-3, 1.0 - u_start), 0.0, 1.0); m = m * m * u_a;
  if (u_mode == 2) o = vec4(c.rgb, c.a * (1.0 - m));
  else if (u_mode == 1) o = vec4(c.rgb * (1.0 - m) + u_col * m, c.a);
  else o = vec4(c.rgb * (1.0 - m), c.a); }""")


def b_vignette(p, c, w, h, opaque):
    a = p["amount"] / 100.0
    if a <= 0: return Built([])
    mode = p.get("mode", "darken")
    return Built([Pass(_VIG, {"u_a": a, "u_start": 1.0 - p["softness"] / 100.0 * 0.95, "u_rnd": p.get("roundness", 50.0) / 100.0,
                              "u_mode": {"darken": 0, "color": 1, "alpha": 2}.get(mode, 0), "u_col": _bgr(p.get("color", "#000000"))})],
                 alpha=(mode == "alpha"))


def _glow_scale(radius):
    return int(min(8, max(1, radius / 3.0)))


_GLOW_BRIGHT = _down_frag("float mk = clamp((lum(col) - u_thr) / max(1e-3, 1.0 - u_thr), 0.0, 1.0); col *= mk;").replace("uniform vec2 u_foot;", "uniform float u_thr; uniform vec2 u_foot;")
_GLOW_DARK = _down_frag("float mk = clamp((u_thr - lum(col)) / max(1e-3, u_thr), 0.0, 1.0); col = (1.0 - col) * mk;").replace("uniform vec2 u_foot;", "uniform float u_thr; uniform vec2 u_foot;")


def _glow_chain(w, h, radius, frag, thr):
    """fastfx._glow_layer: shrink, pick the glowing pixels, blur. Returns (passes, result target)."""
    f = _glow_scale(radius); sw, sh = (max(1, w // f), max(1, h // f)) if f > 1 else (w, h)
    dp = down_pass("in", w, h, sw, sh, "gd", frag); dp.u["u_thr"] = float(thr)
    rs = w / float(sw); s = max(0.5, radius / rs)
    passes, cur, _ = gauss_chain(sw, sh, s, s, src="gd", prefix="gb")
    return [dp] + passes, cur


_GLOW_FIN = _fs("""uniform sampler2D u_blur; uniform float u_a, u_soft; uniform int u_kind;
void main() { vec4 c = texture(u_in, v_uv); vec3 gl = texture(u_blur, v_uv).rgb; vec3 x;
  if (u_kind == 0) x = 1.0 - (1.0 - c.rgb) * (1.0 - gl * u_a);                    // glow, screen
  else if (u_kind == 1) x = min(c.rgb + gl * u_a, 1.0);                           // glow, add
  else if (u_kind == 2) x = mix(c.rgb, 1.0 - (1.0 - c.rgb) * (1.0 - gl * u_soft), u_a);   // soft glow
  else x = max(c.rgb - gl * u_a, 0.0);                                            // dark glow
  o = vec4(clamp(x, 0.0, 1.0), c.a); }""")


def b_glow(p, c, w, h, opaque):
    a = p["amount"] / 100.0
    if a <= 0: return Built([])
    if p.get("color"): return None
    radius = max(0.5, p["radius"] * c.k)
    passes, cur = _glow_chain(w, h, radius, _GLOW_BRIGHT, p["threshold"] / 100.0)
    passes.append(Pass(_GLOW_FIN, {"u_a": a, "u_soft": 1.0, "u_kind": 1 if p.get("blend_mode", "screen") == "add" else 0}, {"u_in": "in", "u_blur": cur}, "main"))
    return Built(passes)


def b_soft_glow(p, c, w, h, opaque):
    a = p["amount"] / 100.0
    if a <= 0: return Built([])
    radius = max(0.5, p["radius"] * c.k)
    passes, cur = _glow_chain(w, h, radius, _DOWN_PLAIN_THR, 0.0)
    passes.append(Pass(_GLOW_FIN, {"u_a": a, "u_soft": p.get("softness", 50.0) / 100.0, "u_kind": 2}, {"u_in": "in", "u_blur": cur}, "main"))
    return Built(passes)


def b_dark_glow(p, c, w, h, opaque):
    a = p["amount"] / 100.0
    if a <= 0: return Built([])
    radius = max(0.5, p["radius"] * c.k)
    passes, cur = _glow_chain(w, h, radius, _GLOW_DARK, p.get("threshold", 40.0) / 100.0)
    passes.append(Pass(_GLOW_FIN, {"u_a": a, "u_soft": 1.0, "u_kind": 3}, {"u_in": "in", "u_blur": cur}, "main"))
    return Built(passes)


_DOWN_PLAIN_THR = _down_frag().replace("uniform vec2 u_foot;", "uniform float u_thr; uniform vec2 u_foot;")

_GRAIN = _fs("""uniform float u_a, u_s; uniform uint u_seed; uniform int u_color;
float gn(uvec2 p, uint ch) { float s = 0.0; for (uint k = 0u; k < 4u; k++) s += rnd(p, u_seed * 7u + ch * 131u + k * 977u); return (s - 2.0) * 1.7320508; }
void main() { vec4 c = texture(u_in, v_uv); uvec2 cell = uvec2(floor(gl_FragCoord.xy / u_s));
  vec3 d = u_color == 1 ? vec3(gn(cell, 0u), gn(cell, 1u), gn(cell, 2u)) : vec3(gn(cell, 0u));
  o = vec4(clamp(c.rgb + d * (40.0 / 255.0) * u_a, 0.0, 1.0), c.a); }""")


def b_grain(p, c, w, h, opaque):
    a = p["amount"] / 100.0
    if a <= 0: return Built([])
    return Built([Pass(_GRAIN, {"u_a": a, "u_s": float(max(1, int(round(p["size"] * c.k)))), "u_seed": int(c.lt * 24) & 0xFFFFFF,
                                "u_color": 1 if p.get("color_grain", False) else 0})])


_NOISE = _fs("""uniform float u_a; uniform uint u_seed;
void main() { vec4 c = texture(u_in, v_uv); uvec2 p = uvec2(gl_FragCoord.xy);
  vec3 n = vec3(rnd(p, u_seed * 3u), rnd(p, u_seed * 3u + 1u), rnd(p, u_seed * 3u + 2u)); o = vec4(mix(c.rgb, n, u_a), c.a); }""")


def b_noise(p, c, w, h, opaque):
    a = p["amount"] / 100.0
    if a <= 0: return Built([])
    return Built([Pass(_NOISE, {"u_a": a, "u_seed": int(c.lt * 30) & 0xFFFFFF})])


_EDGE = _fs("""uniform sampler2D u_blur; uniform float u_a; uniform int u_color, u_inv;
void main() { vec4 c = texture(u_in, v_uv); vec2 t = 1.0 / u_size; vec3 e;
  vec3 m = texture(u_blur, v_uv).rgb;
  if (u_color == 1) e = abs(c.rgb - m) * u_a * 4.0;
  else { float L = lum(texture(u_blur, v_uv + vec2(t.x, 0.0)).rgb) + lum(texture(u_blur, v_uv - vec2(t.x, 0.0)).rgb)
                 + lum(texture(u_blur, v_uv + vec2(0.0, t.y)).rgb) + lum(texture(u_blur, v_uv - vec2(0.0, t.y)).rgb) - 4.0 * lum(m);
         e = vec3(abs(L) * u_a * 4.0); }
  e = clamp(e, 0.0, 1.0); if (u_inv == 1) e = 1.0 - e; o = vec4(e, c.a); }""")


def b_find_edges(p, c, w, h, opaque):
    sigma = max(0.4, p.get("softness", 1.0) * c.k)
    passes, cur, _ = gauss_chain(w, h, sigma, sigma, prefix="e", shrink=False)
    passes.append(Pass(_EDGE, {"u_a": p["amount"] / 100.0, "u_color": 1 if p.get("mode", "luminance") == "color" else 0,
                               "u_inv": 1 if p.get("invert", False) else 0}, {"u_in": "in", "u_blur": cur}, "main"))
    return Built(passes)


# ───────────────────────── Better Chroma Key (Patch 36) ─────────────────────────
# Same steps and constants as smartkey.fx_smart_key (matte from the chroma distance, despill, choke / feather, edge colour) as GPU passes.
# Targets: col = the colour, A = the matte (grey), inner / z0 / cn / cd = the edge-colour helpers.
_SK_OBJ = _fs("void main() { float a = texture(u_in, v_uv).a; o = vec4(a, a, a, 1.0); }")
_SK_COL = _fs("""uniform vec3 u_dom, u_oth; uniform float u_cnt, u_amt;
void main() { vec3 x = texture(u_in, v_uv).rgb;
  if (u_amt > 0.0 && u_cnt > 0.0) { float lim = dot(x, u_oth) / u_cnt; x = mix(x, min(x, vec3(lim)), u_dom * u_amt); }
  o = vec4(x, 1.0); }""")
_SK_A = _fs("""uniform vec2 u_kc; uniform float u_t0, u_wd;
void main() { vec4 c = texture(u_in, v_uv); float R = floor(c.b * 255.0 + 0.5), G = floor(c.g * 255.0 + 0.5), B = floor(c.r * 255.0 + 0.5);
  float Y = floor(0.299 * R + 0.587 * G + 0.114 * B + 0.5);                       // the 8-bit YCrCb of the CPU version (Y is rounded first)
  float cr = clamp(floor((R - Y) * 0.713 + 128.5), 0.0, 255.0), cb = clamp(floor((B - Y) * 0.564 + 128.5), 0.0, 255.0);
  float d = length(vec2(cr - u_kc.x, cb - u_kc.y)); float t = clamp((d - u_t0) / u_wd, 0.0, 1.0);
  float a = t * t * (3.0 - 2.0 * t) * c.a; o = vec4(a, a, a, 1.0); }""")
_SK_MORPH = _fs("""uniform int u_n; uniform int u_grow; uniform vec2 u_in_sz;
void main() { float m = u_grow == 1 ? 0.0 : 1.0; int n2 = u_n * u_n;
  for (int j = -u_n; j <= u_n; j++) { int hw = int(floor(sqrt(float(n2 - j * j)) + 0.5));          // the same round ellipse as OpenCV's getStructuringElement
    for (int i = -hw; i <= hw; i++) {
      float a = texture(u_in, v_uv + vec2(float(i), float(j)) / u_in_sz).r; m = u_grow == 1 ? max(m, a) : min(m, a); } }
  o = vec4(m, m, m, 1.0); }""")
_SK_INNER = _fs("""uniform int u_n; uniform vec2 u_in_sz;
void main() { float m = 1.0; int n2 = u_n * u_n;
  for (int j = -u_n; j <= u_n; j++) { int hw = int(floor(sqrt(float(n2 - j * j)) + 0.5));
    for (int i = -hw; i <= hw; i++) {
      float a = texture(u_in, v_uv + vec2(float(i), float(j)) / u_in_sz).r; m = min(m, a > 0.97 ? 1.0 : 0.0); } }
  o = vec4(m, m, m, 1.0); }""")
_SK_ZONE = _fs("""uniform sampler2D u_inner;
void main() { float a = texture(u_in, v_uv).r; float solid = a > 0.97 ? 1.0 : 0.0; float ring = solid - texture(u_inner, v_uv).r;
  float partial = (a > 0.004 && a <= 0.97) ? 1.0 : 0.0; float z = max(ring, partial); o = vec4(z, z, z, 1.0); }""")
_SK_CN = _fs("""uniform sampler2D u_col, u_inner;
void main() { float k = texture(u_inner, v_uv).r; o = vec4(texture(u_col, v_uv).rgb * k, 1.0); }""")
_SK_FIN = _fs("""uniform sampler2D u_col, u_A, u_z, u_cn, u_cd; uniform float u_amt; uniform vec3 u_ecol; uniform int u_mode, u_view;
void main() {
  vec3 col = texture(u_col, v_uv).rgb; float A = texture(u_A, v_uv).r;
  float z = (u_mode > 0 || u_view == 2) ? clamp(texture(u_z, v_uv).r * 1.6, 0.0, 1.0) : 0.0;
  if (u_view == 1) { o = vec4(vec3(A), 1.0); return; }
  if (u_view == 2) { o = vec4(vec3(z), 1.0); return; }
  if (u_mode == 2) col = mix(col, u_ecol, z * u_amt);
  else if (u_mode == 1) { float den = texture(u_cd, v_uv).r; vec3 ec = den > 1e-3 ? texture(u_cn, v_uv).rgb / max(den, 1e-3) : col; col = mix(col, ec, z * u_amt); }
  o = vec4(clamp(col, 0.0, 1.0), A); }""")


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


def b_smart_key(p, c, w, h, opaque):
    mode = p.get("mode", "color"); view = p.get("view", "result"); k = max(1e-3, float(c.k)); passes = []
    if mode == "object":
        if opaque: return Built([])                                    # nothing rendered (yet): the picture is left alone (as on the CPU)
        passes.append(Pass(_SK_OBJ, {}, {"u_in": "in"}, "A")); colsrc = "in"
    else:
        kb = _sk_bgr(p["color"]); kd = [v / 255.0 for v in kb]; mx = max(kd); amt = float(p.get("spill", 60.0)) / 100.0
        dom = [1.0 if kd[i] >= 0.7 * mx else 0.0 for i in range(3)]; oth = [1.0 - d for d in dom]; cnt = sum(oth)
        if amt <= 0 or mx < 0.12 or cnt == 0: amt = 0.0
        R, G, B = kb[2], kb[1], kb[0]; Y = math.floor(0.299 * R + 0.587 * G + 0.114 * B + 0.5)
        kc = (float(min(255, max(0, math.floor((R - Y) * 0.713 + 128.5)))), float(min(255, max(0, math.floor((B - Y) * 0.564 + 128.5)))))
        t0 = float(p["tolerance"]) * 1.1 + 1.5; wd = 1.5 + float(p["softness"]) * 1.1
        passes.append(Pass(_SK_COL, {"u_dom": tuple(dom), "u_oth": tuple(oth), "u_cnt": cnt, "u_amt": amt}, {"u_in": "in"}, "col"))
        passes.append(Pass(_SK_A, {"u_kc": kc, "u_t0": t0, "u_wd": wd}, {"u_in": "in"}, "A"))
        colsrc = "col"
    A = "A"
    r = float(p.get("choke", 0.0)) * k
    if abs(r) >= 0.5:
        n = int(round(abs(r)))
        if n > 12: return None                                         # a very big choke: the CPU does it
        passes.append(Pass(_SK_MORPH, {"u_n": n, "u_grow": 0 if r > 0 else 1}, {"u_in": A}, "A1")); A = "A1"
    f = float(p.get("feather", 0.0)) * k
    if f > 0.3: A = _blur_to(passes, A, w, h, f * 0.5, "kf")
    emode = p.get("edge_mode", "auto"); eamt = float(p.get("edge_amount", 70.0)) / 100.0; wpx = float(p.get("edge_width", 3.0)) * k
    edge_on = not (emode == "off" or eamt <= 0 or wpx <= 0.0)
    zname = A; cn = A; cd = A
    if edge_on or view == "edge":
        wz = wpx if edge_on else max(1.0, float(p.get("edge_width", 3.0)) * k); n = max(1, int(round(wz)))
        if n > 12: return None
        passes.append(Pass(_SK_INNER, {"u_n": n}, {"u_in": A}, "inner"))
        passes.append(Pass(_SK_ZONE, {}, {"u_in": A, "u_inner": "inner"}, "z0"))
        zname = _blur_to(passes, "z0", w, h, max(0.7, wz * 0.35), "kz")
        if edge_on and emode != "custom":
            sig = max(3.0, wz * 2.0 + 3.0)
            passes.append(Pass(_SK_CN, {}, {"u_col": colsrc, "u_inner": "inner"}, "cn0", dt="f2"))
            cn = _blur_to(passes, "cn0", w, h, sig, "kn", "f2"); cd = _blur_to(passes, "inner", w, h, sig, "kd", "f2")
    ec = tuple(v / 255.0 for v in _sk_bgr(p.get("edge_color", "#303030")))
    passes.append(Pass(_SK_FIN, {"u_amt": eamt, "u_ecol": ec, "u_mode": (0 if not edge_on else (2 if emode == "custom" else 1)),
                                 "u_view": {"result": 0, "matte": 1, "edge": 2}.get(view, 0)},
                       {"u_col": colsrc, "u_A": A, "u_z": zname, "u_cn": cn, "u_cd": cd}, "main"))
    return Built(passes, alpha=True)



# ───────────────────────── more effects (Patch 36) ─────────────────────────
# Every one of these was compared with its CPU version on a test picture (see the Patch 36 notes); where a parameter combination is not done
# here the builder returns None and the CPU runs it.
_SAMP = """uniform vec2 u_in_sz;
int pmod(int a, int b) { return a - b * int(floor(float(a) / float(b))); }                                        // never negative (the % operator on a negative number differs between drivers)
int rfl(int i, int n) { int m = pmod(i, 2 * n); return m >= n ? 2 * n - 1 - m : m; }          // BORDER_REFLECT
int rfl101(int i, int n) { if (n < 2) return 0; int P = 2 * (n - 1); int m = pmod(i, P); return m >= n ? P - m : m; }   // BORDER_REFLECT_101
vec4 fetch(ivec2 i) { ivec2 n = ivec2(u_in_sz); return texelFetch(u_in, ivec2(rfl(i.x, n.x), rfl(i.y, n.y)), 0); }
vec4 bil(vec2 s) { vec2 f = floor(s); vec2 t = s - f; ivec2 i = ivec2(f);                                           // cv2.remap INTER_LINEAR, pixel index coordinates
  return mix(mix(fetch(i), fetch(i + ivec2(1, 0)), t.x), mix(fetch(i + ivec2(0, 1)), fetch(i + ivec2(1, 1)), t.x), t.y); }
"""

_EXPO = _fs("""uniform float u_ev, u_off, u_ig;
void main() { vec4 c = texture(u_in, v_uv); vec3 f = clamp(c.rgb * u_ev + u_off, 0.0, 8.0); o = vec4(clamp(pow(f, vec3(u_ig)), 0.0, 1.0), c.a); }""")


def b_exposure(p, c, w, h, opaque):
    return Built([Pass(_EXPO, {"u_ev": 2.0 ** float(p["exposure"]), "u_off": float(p["offset"]) / 100.0, "u_ig": 1.0 / max(0.05, float(p["gamma"]))})])


_FLIP = _fs(_SAMP + """uniform ivec2 u_f;
void main() { ivec2 p = ivec2(gl_FragCoord.xy); ivec2 n = ivec2(u_in_sz); if (u_f.x == 1) p.x = n.x - 1 - p.x; if (u_f.y == 1) p.y = n.y - 1 - p.y; o = texelFetch(u_in, p, 0); }""")


def b_flip_layer(p, c, w, h, opaque):
    ax = p.get("axis", "horizontal")
    f = (1, 0) if ax == "horizontal" else ((0, 1) if ax == "vertical" else (1, 1))
    return Built([Pass(_FLIP, {"u_f": f})])


_MIRROR = _fs(_SAMP + """uniform int u_mode; uniform vec2 u_c;
void main() { vec2 xy = floor(gl_FragCoord.xy); vec2 s = xy;
  if (u_mode == 0 || u_mode == 4) s.x = xy.x > u_c.x ? 2.0 * u_c.x - xy.x : xy.x;
  if (u_mode == 1) s.x = xy.x < u_c.x ? 2.0 * u_c.x - xy.x : xy.x;
  if (u_mode == 2 || u_mode == 4) s.y = xy.y > u_c.y ? 2.0 * u_c.y - xy.y : xy.y;
  if (u_mode == 3) s.y = xy.y < u_c.y ? 2.0 * u_c.y - xy.y : xy.y;
  o = bil(s); }""")


def b_mirror(p, c, w, h, opaque):
    m = {"lr": 0, "rl": 1, "tb": 2, "bt": 3, "quad": 4}.get(p["mode"])
    if m is None: return None                                        # kaleidoscope: the CPU does it
    return Built([Pass(_MIRROR, {"u_mode": m, "u_c": (w * float(p["cx"]) / 100.0, h * float(p["cy"]) / 100.0)})])


_BOXH = _fs("""uniform ivec2 u_dir; uniform int u_r; uniform vec2 u_in_sz;
void main() { ivec2 p = ivec2(gl_FragCoord.xy); ivec2 n = ivec2(u_in_sz); vec4 acc = vec4(0.0);
  for (int i = -u_r; i <= u_r; i++) acc += texelFetch(u_in, clamp(p + u_dir * i, ivec2(0), n - 1), 0);
  o = acc / float(2 * u_r + 1); }""")


def b_boxblur(p, c, w, h, opaque):
    if not opaque: return None                                       # see-through edges need premultiplied pixels: the CPU function does that
    r = int(max(1, p["size"] * c.k)); n = int(p["passes"])
    if r > 100 or n < 1: return None if r > 100 else Built([])
    ps = []; cur = "in"
    for i in range(n):
        ps.append(Pass(_BOXH, {"u_dir": (1, 0), "u_r": r}, {"u_in": cur}, "bx%da" % i, dt="f2")); cur = "bx%da" % i
        ps.append(Pass(_BOXH, {"u_dir": (0, 1), "u_r": r}, {"u_in": cur}, "bx%db" % i, dt="f2" if i < n - 1 else "f1")); cur = "bx%db" % i
    ps[-1].out = "main"
    return Built(ps)


_CHROMA_AB = _fs(_SAMP + """uniform float u_k; uniform vec2 u_o;
void main() { vec2 xy = floor(gl_FragCoord.xy); vec2 cen = u_in_sz * 0.5; vec4 c = texelFetch(u_in, ivec2(xy), 0);
  float rr = bil(cen + (xy - cen) * (1.0 - u_k) + u_o).b;            // R (index 2) is the b component
  float bb = bil(cen + (xy - cen) * (1.0 + u_k) - u_o).r;            // B (index 0)
  o = vec4(bb, c.g, rr, c.a); }""")


def b_chromab(p, c, w, h, opaque):
    a = math.radians(float(p["angle"])); sh = float(p["shift"]) * c.k
    return Built([Pass(_CHROMA_AB, {"u_k": float(p["amount"]) / 1000.0, "u_o": (math.cos(a) * sh, math.sin(a) * sh)})])


_EMBOSS = _fs("""uniform mat3 u_kern; uniform float u_mix; uniform int u_color; uniform vec2 u_in_sz;
int r101(int i, int n) { if (n < 2) return 0; int P = 2 * (n - 1); int m = i - P * int(floor(float(i) / float(P))); return m >= n ? P - m : m; }
float L(ivec2 p) { ivec2 n = ivec2(u_in_sz); return lum(texelFetch(u_in, ivec2(r101(p.x, n.x), r101(p.y, n.y)), 0).rgb); }
void main() { ivec2 p = ivec2(gl_FragCoord.xy); vec4 c = texture(u_in, v_uv); float g = 0.0;
  for (int j = 0; j < 3; j++) for (int i = 0; i < 3; i++) g += u_kern[i][j] * L(p + ivec2(i - 1, j - 1));     // u_kern[col i][row j]
  float rel = clamp(0.5 + g * 0.5, 0.0, 1.0);
  vec3 e = u_color == 0 ? vec3(rel) : c.rgb * rel * 2.0; o = vec4(clamp(c.rgb * (1.0 - u_mix) + e * u_mix, 0.0, 1.0), c.a); }""")


def b_emboss(p, c, w, h, opaque):
    if c.k > 1.5: return None                                        # the CPU smooths the picture first at this scale
    a = math.radians(float(p["angle"])); sa, ca = math.sin(a), math.cos(a); d = float(p["depth"]) / 30.0
    rows = [[-sa - ca, -sa, ca - sa], [-ca, 1.0, ca], [sa - ca, sa, sa + ca]]
    # GLSL mat3 is column-major: u_kern[i][j] = rows[j][i]
    flat = [rows[j][i] * d for i in range(3) for j in range(3)]
    return Built([Pass(_EMBOSS, {"u_kern": tuple(flat), "u_mix": float(p["mix"]) / 100.0, "u_color": 1 if p["color"] else 0})])



GL_FX = {"tint": b_tint, "bw": b_bw, "invert": b_invert, "adjust": b_adjust, "hue_shift": b_hue_shift,
         "color_temperature": b_color_temperature, "highlights_shadows": b_highlights_shadows, "posterize": b_posterize,
         "threshold": b_threshold, "gradient_map": b_gradient_map, "luma_key": b_luma_key, "chroma": b_chroma,
         "blur": b_blur, "motion_blur": b_motion_blur, "radial_blur": b_radial_blur, "zoom_blur": b_zoom_blur, "spin_blur": b_spin_blur,
         "rgb_split": b_rgb_split, "pixelate": b_pixelate, "sharpen": b_sharpen, "vignette": b_vignette,
         "glow": b_glow, "soft_glow": b_soft_glow, "dark_glow": b_dark_glow, "grain": b_grain, "noise": b_noise, "find_edges": b_find_edges, "smart_key": b_smart_key,
         "exposure": b_exposure, "flip_layer": b_flip_layer, "mirror": b_mirror, "boxblur": b_boxblur, "chromab": b_chromab, "emboss": b_emboss}
