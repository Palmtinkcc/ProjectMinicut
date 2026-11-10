"""What every GPU effect imports.

    from ..pool.gl import Pass, Built, gauss_chain, shaders

Pass, Built      one shader pass / the list of passes of one effect (render/glfx.py)
gauss_chain      the Gaussian blur as passes on a shrunken copy (render/glfx_lib.py)
shaders(__file__) loads every *.frag next to the effect and returns {"file name without .frag": shader source}.
                 A line  //#use sampling  at the top of a .frag adds pool/glsl/sampling.glsl in front of it
                 (texel fetch with OpenCV-style borders, bilinear sampling, a safe modulo). Add more files to pool/glsl/ for code that
                 several effects need, and name them in //#use lines.
"""
import glob, os, re

from ...render.glfx import Pass, Built
from ...render.glfx_lib import gauss_chain, _fs

_GLSL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "glsl")
_USE = re.compile(r"^//#use\s+(\w+)\s*$", re.M)


def _glsl(name):
    with open(os.path.join(_GLSL, name + ".glsl"), encoding="utf-8") as f: return f.read()


def shaders(effect_file):
    out = {}
    for path in sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(effect_file)), "*.frag"))):
        with open(path, encoding="utf-8") as f: text = f.read()
        pre = "".join(_glsl(n) for n in _USE.findall(text))
        out[os.path.splitext(os.path.basename(path))[0]] = _fs(pre + _USE.sub("", text))
    return out
