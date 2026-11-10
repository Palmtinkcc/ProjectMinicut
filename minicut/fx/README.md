# Effects: one folder each

Every effect of MiniCut is a folder in `minicut/fx/<effect id>/`. The code of an effect is exactly what it was before (Patch 36 only moved it).

```
fx/
  order.txt          the effect ids in the order the effects panel shows them (loader.reorder() puts the registry in this order)
  loader.py          imports every effect folder (this registers the CPU effects) and collects the GPU builders
  pool/              the shared part
    cpu_kit.py         helpers every CPU effect uses (F / I / C / CH / B parameter makers, blend, remap, coords ...)   (old path: render/fxpack/kit.py)
    cpu_<group>.py     helpers shared by the effects of one group (color, glitch, vhs, background, repeat, particle, wipes, strokes, warp, motion)
    gl.py              what a GPU effect imports: Pass, Built, gauss_chain, shaders()
    glsl/sampling.glsl shared shader code (texel fetch with OpenCV-style borders, bilinear, safe modulo)   (//#use sampling)
    testing.py         GPU vs CPU comparison:  python -m minicut.fx.pool.testing [effect ...]
  <effect id>/       e.g. mirror/
    effect.py          1. the CPU effect: its function and the reg(...) / register(...) call    2. (only if it has one) the GPU part: ID, build()
    *.frag             one file per shader pass of the GPU version
    cases.json         parameter sets for the GPU test
```
Effects in render/effects.py (the first 40) import the helpers they use from `render/effects.py` by name; the others get everything of their group with
`from ..pool.cpu_<group> import *`. 3 ids (mirror, swirl, dissolve) were registered twice in the old code (the second one wins); both versions are in their effect.py, in the old order.

## New effect, step by step
1. Make the folder `fx/<id>/` with an empty `__init__.py` and an `effect.py`.
2. CPU: write the function `fx_<id>(img, p, ctx)` and register it (`reg(...)`, see any effect.py of the same group for the parameter list). Add the id to `order.txt` where the panel should show it (without it the effect goes last).
3. GPU (optional): in the same file `from ..pool.gl import Pass, Built, shaders`, `ID = "<id>"`, `SH = shaders(__file__)`, `def build(p, c, w, h, opaque)`.
   `p` = the cleaned parameters, `c.k` = preview scale (multiply every pixel size by it), `opaque` = no see-through pixel.
   Return `Built([Pass(SH["main"], {uniforms}, {samplers}, "out target"), ...])`, or `None` for a parameter combination the GPU version does not do (the CPU runs it).
4. One `*.frag` per pass; `//#use sampling` on the first line when you need `fetch()`, `bil()`, `pmod()`, `rfl()`.
5. `cases.json` with a few parameter sets, then `python -m minicut.fx.pool.testing <id>` must pass (mean difference <= 0.5 of 255, opaque and see-through picture).

## Rules learned the hard way
* A relative import INSIDE a function (`from ..shared.deps import X`) breaks silently when the file moves: the effect fails and the picture comes back unchanged. Use top-level imports, and compare outputs after a move (the Patch 36 check compared 1454 variants).
* Pictures are B, G, R, A: in a shader `c.rgb` is (B, G, R). Colour uniforms go in as (blue, green, red).
* Never use `%` on an int that can be negative: drivers differ. Use `pmod()`.
* Anything divided later (a sum / a weight) goes in a 16-bit target: `Pass(..., dt="f2")`.
* Borders: `rfl()` = OpenCV BORDER_REFLECT, `rfl101()` = BORDER_REFLECT_101 (the OpenCV default for filters), clamp = BORDER_REPLICATE.
* `cv2.remap` positions are pixel indexes: the centre of pixel i is i, and `gl_FragCoord.xy` is i + 0.5.
* Every parameter measured in pixels is multiplied by `c.k`.
* One broken effect folder never stops the program: the loader skips it, writes the error to the log, and the other effects work.
