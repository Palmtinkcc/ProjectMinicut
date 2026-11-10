"""signal: Signal. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_vhs import *

def fx_signal(img, p, ctx):
    a = p["amount"] / 100.0; h, w = img.shape[:2]; r = rng(ctx, p["seed"], 8); cyc = (ctx.lt * p["rate"]) % 1.0; burst = float(np.clip((0.35 - cyc) / 0.35, 0, 1)) * a
    if burst <= 0.01: return img
    off = int(r.normal(0, h * 0.2 * burst)); out = np.roll(img, off, axis=0); sh = r.normal(0, w * 0.05 * burst, h).astype(np.float32); out = shift_rows(out, sh)
    st = r.random((h, w, 1)).astype(np.float32); f = f3(out) * (1 - burst * 0.5) + st * burst * 0.5; g = lum(f)[..., None]; f = f * (1 - burst * 0.6) + g * burst * 0.6; return pack(np.clip(f, 0, 1), like=out)

reg("signal", V, "Signal", [F("amount", "Amount", 70, 0, 100), F("rate", "Signal loss per second", 0.7, 0.1, 5), SEED()], fx_signal, "The picture keeps losing its signal: it rolls, tears and fills with static.", "signal loss roll")

ID = "signal"
