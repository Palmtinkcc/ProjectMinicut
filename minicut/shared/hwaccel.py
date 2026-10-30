"""GPU helpers: detect which hardware video encoders really work, and the matching encoder options.

A listed encoder is not proof that it runs: FFmpeg builds often compile NVENC / QSV / AMF in even on PCs that
do not have that GPU.  So every candidate is checked with a tiny real encode before it is used.
"""
from .core import *


ENCODE_CHOICES = [("Auto (GPU if it works, otherwise CPU)", "auto"), ("CPU only (libx264 / libx265)", "cpu"),
                  ("NVIDIA NVENC", "nvenc"), ("Intel QuickSync", "qsv"), ("AMD AMF", "amf")]
HW_ENCODERS = {"nvenc": ("h264_nvenc", "hevc_nvenc"), "qsv": ("h264_qsv", "hevc_qsv"), "amf": ("h264_amf", "hevc_amf")}
HW_NAMES = {"nvenc": "NVIDIA NVENC", "qsv": "Intel QuickSync", "amf": "AMD AMF"}

_LISTED = {}     # ffmpeg -encoders output (fetched once)
_WORKS = {}      # encoder name -> True / False (test encode result)


def clear_gpu_cache():
    _LISTED.clear(); _WORKS.clear()


def _listed_encoders():
    if "text" not in _LISTED:
        try:
            _LISTED["text"] = subprocess.run([FFMPEG, "-hide_banner", "-encoders"], capture_output=True, text=True,
                                             errors="ignore", creationflags=NOWIN, timeout=15).stdout
        except Exception:
            _LISTED["text"] = ""
    return _LISTED["text"]


def encoder_works(name):
    """Encode three black frames with the encoder. Returns True only if FFmpeg finishes without error."""
    if name not in _WORKS:
        if name not in _listed_encoders():
            _WORKS[name] = False
        else:
            try:
                r = subprocess.run([FFMPEG, "-hide_banner", "-v", "error", "-f", "lavfi", "-i",
                                    "color=c=black:s=256x256:d=0.2", "-frames:v", "3", "-c:v", name,
                                    "-pix_fmt", "yuv420p", "-f", "null", "-"],
                                   capture_output=True, creationflags=NOWIN, timeout=25)
                _WORKS[name] = r.returncode == 0
            except Exception:
                _WORKS[name] = False
    return _WORKS[name]


def pick_hw_encoder(hevc=False, choice=None):
    """Return (vendor, encoder_name) for the GPU encoder to use, or None to stay on the CPU."""
    choice = choice or CFG.get("encode_hw", "auto")
    if choice == "cpu": return None
    vendors = [choice] if choice in HW_ENCODERS else ["nvenc", "qsv", "amf"]
    for vendor in vendors:
        name = HW_ENCODERS[vendor][1 if hevc else 0]
        if encoder_works(name): return vendor, name
    if choice in HW_ENCODERS:
        print("GPU encoder %s is not available here, using the CPU encoder." % HW_NAMES[choice])
    return None


def hw_quality_args(vendor, crf, out_w):
    """Quality options for each GPU encoder (they do not accept the x264 -crf / -preset options)."""
    if vendor == "nvenc": return ["-preset", "p4", "-rc", "vbr", "-cq", str(crf), "-b:v", "0", "-pix_fmt", "yuv420p"]
    if vendor == "qsv": return ["-global_quality", str(crf), "-preset", "medium", "-pix_fmt", "yuv420p"]
    return ["-quality", "balanced", "-b:v", ("8M" if out_w >= 1920 else "4M"), "-pix_fmt", "yuv420p"]


GPU_CODECS = {"h264": {"nvenc": "h264_nvenc", "qsv": "h264_qsv", "amf": "h264_amf"},
              "hevc": {"nvenc": "hevc_nvenc", "qsv": "hevc_qsv", "amf": "hevc_amf"},
              "av1": {"nvenc": "av1_nvenc", "qsv": "av1_qsv", "amf": "av1_amf"}}
CPU_CODECS = {"h264": ["libx264"], "hevc": ["libx265"], "av1": ["libsvtav1", "libaom-av1"], "vp9": ["libvpx-vp9"], "prores": ["prores_ks"]}
CODEC_OF_FORMAT = {"mp4": "h264", "mkv": "h264", "mp4_265": "hevc", "av1": "av1", "webm": "vp9", "mov": "prores"}


def cpu_encoder_for(codec):
    listed = _listed_encoders()
    for name in CPU_CODECS.get(codec, []):
        if name in listed: return name
    return None


def codec_plan(fmt):
    """(encoder name, hardware tuple or None, note) for an export format, checked on this PC.
    The note says what will be used and why, e.g. when the GPU has no encoder for that codec."""
    codec = CODEC_OF_FORMAT.get(fmt)
    if codec is None: return None, None, ""
    if codec in ("vp9", "prores"):
        cpu = cpu_encoder_for(codec)
        if cpu is None: return None, None, "This FFmpeg build has no encoder for %s." % codec
        return cpu, None, "CPU encoder %s is used (no GPU encoder for this format)." % cpu
    want = CFG.get("encode_hw", "auto")
    if want != "cpu":
        for vendor in ("nvenc", "qsv", "amf"):
            if want not in ("auto", vendor): continue
            name = GPU_CODECS.get(codec, {}).get(vendor)
            if name and encoder_works(name): return name, (vendor, name), "GPU encoder %s is used." % name
    cpu = cpu_encoder_for(codec)
    if cpu is None: return None, None, "This FFmpeg build has no encoder for %s." % codec
    return cpu, None, "No GPU encoder for %s works on this PC, so the CPU encoder %s is used. It is slower." % (codec.upper(), cpu)


def detect_gpu_encoders():
    """For the Settings button: names of the GPU encoders that work for H.264 on this PC."""
    clear_gpu_cache()
    return [HW_NAMES[v] for v in ("nvenc", "qsv", "amf") if encoder_works(HW_ENCODERS[v][0])]
