# Effects: one folder each

```
fx/
  loader.py          finds the folders and gives their GPU builders to the engine (nothing to register by hand)
  pool/              the shared part
    gl.py              Pass, Built, gauss_chain, shaders()      <- what an effect imports
    glsl/sampling.glsl texel fetch with OpenCV-style borders, bilinear sampling, safe modulo   (//#use sampling)
    testing.py         GPU vs CPU comparison:  python -m minicut.fx.pool.testing [effect ...]
  <effect id>/       e.g. mirror/
    effect.py          ID = "mirror"  and  build(p, c, w, h, opaque) -> Built | None
    *.frag             one file per shader pass
    cases.json         {"cases": [ {parameter overrides}, ... ]}   used by the test tool
    assets/            (only if needed) LUTs, textures, fonts
```

## New effect, step by step
1. Make the folder `fx/<id>/` (the `<id>` is the effect id of the CPU effect it belongs to).
2. `effect.py`: `from ..pool.gl import Pass, Built, shaders`, `ID = "..."`, `SH = shaders(__file__)`, then `build(p, c, w, h, opaque)`.
   `p` = the cleaned parameters, `c.k` = preview scale (multiply every pixel size by it), `opaque` = no see-through pixel.
   Return `Built([Pass(SH["main"], {uniforms}, {samplers}, "out target"), ...])`, or `None` for a parameter combination the GPU version does not do (the CPU runs it).
3. One `*.frag` per pass. Put `//#use sampling` on the first line when you need `fetch()`, `bil()`, `pmod()`, `rfl()`.
4. `cases.json`: a few parameter sets that cover every mode / branch of the effect.
5. Run `python -m minicut.fx.pool.testing <id>`. It must pass (mean difference <= 0.5 of 255) on the opaque and the see-through picture.

## Rules learned the hard way
* Pictures are B, G, R, A: in a shader `c.rgb` is (B, G, R). Colour uniforms go in as (blue, green, red).
* Never use `%` on an int that can be negative: drivers differ (the same shader gave wrong pictures on one). Use `pmod()`.
* Anything that is divided later (a sum / a weight) goes in a 16-bit target: `Pass(..., dt="f2")`. 8-bit targets round too much.
* Borders: `rfl()` = OpenCV BORDER_REFLECT, `rfl101()` = BORDER_REFLECT_101 (the OpenCV default for filters), clamp = BORDER_REPLICATE.
* `cv2.remap` positions are pixel indexes: the centre of pixel i is i, and `gl_FragCoord.xy` is i + 0.5.
* Every parameter measured in pixels is multiplied by `c.k`.
* One broken effect folder never stops the program: the loader skips it and the CPU version is used.
