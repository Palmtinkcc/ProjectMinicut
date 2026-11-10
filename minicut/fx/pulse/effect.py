"""pulse: Pulse size. CPU version; the GPU version is added here as build() when there is one."""
from ..pool.cpu_repeat import *

def fx_pulse(img, p, ctx):
    s = 1 + np.sin(ctx.lt * p["speed"] * 2 * np.pi) * p["amount"] / 100.0 * 0.5; return _tf(img, ctx, 0, 0, 0, max(0.05, s))

reg("pulse", MV, "Pulse size", [F("amount", "Amount", 25, 0, 100), F("speed", "Pulses / s", 1.0, 0.1, 8)], fx_pulse, "The picture grows and shrinks like a heartbeat.", "heartbeat scale")

ID = "pulse"
