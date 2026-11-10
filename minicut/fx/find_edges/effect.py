"""find_edges: Find Edges. CPU version; the GPU version is added here as build() when there is one."""
from ...shared.deps import *
from ...render.effects import register

def fx_find_edges(img, p, ctx):
    amount = p["amount"] / 100.0
    invert = p.get("invert", False)
    mode   = p.get("mode", "luminance")   # luminance | color
    sigma  = max(0.4, p.get("softness", 1.0) * ctx.k)
    rgb = np.ascontiguousarray(img[..., :3])
    if mode == "color":
        blurred = cv2.GaussianBlur(rgb, (0, 0), sigma).astype(np.float32)
        edges = np.abs(rgb.astype(np.float32) - blurred)
        edges = np.clip(edges * (amount * 4), 0, 255).astype(np.uint8)
    else:
        gray = cv2.cvtColor(rgb, cv2.COLOR_BGR2GRAY)
        blurred_g = cv2.GaussianBlur(gray, (0, 0), sigma)
        edge_g = cv2.Laplacian(blurred_g, cv2.CV_32F)
        edge_g = np.clip(np.abs(edge_g) * amount * 4, 0, 255).astype(np.uint8)
        edges = cv2.cvtColor(edge_g, cv2.COLOR_GRAY2BGR)
    if invert: edges = 255 - edges
    out = img.copy(); out[..., :3] = edges; return out

register("find_edges", "Stylize", "Find Edges",
         [("amount",   "Amount",   "float",  60.0, 0.0, 100.0),
          ("softness", "Softness", "float",  1.0,  0.1, 10.0),
          ("mode",     "Mode",     "choice", "luminance",
           [("luminance", "Luminance"), ("color", "Color")], None),
          ("invert",   "Invert",   "bool",   False, None, None)],
         fx_find_edges,
         help="Detect and highlight edges. Combine with Copy Background for neon edge effects.")

ID = "find_edges"
