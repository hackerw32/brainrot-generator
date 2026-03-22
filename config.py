"""
config.py - Global constants and character voice configuration
"""
import os
from pathlib import Path

# ── Project paths ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)

# ── Output resolutions ─────────────────────────────────────────────────────────
RESOLUTIONS = {
    "1080x1920 (Full HD Shorts)": (1080, 1920),
    "720x1280 (HD Shorts)":       (720,  1280),
}
DEFAULT_RESOLUTION = "1080x1920 (Full HD Shorts)"

# ── Caption defaults ───────────────────────────────────────────────────────────
DEFAULT_FONT_COLOR     = "#FFFFFF"   # white
DEFAULT_STROKE_COLOR   = "#000000"   # black
DEFAULT_HIGHLIGHT_COLOR= "#FFFF00"   # yellow
DEFAULT_MAX_WORDS      = 3
DEFAULT_FONT_SIZE_1080 = 90          # px at 1080 wide
DEFAULT_FONT_SIZE_720  = 60          # px at 720 wide
STROKE_WIDTH           = 5          # px

# ── Character voice map (edge-tts voices) ─────────────────────────────────────
# Each character: voice name + optional ffmpeg audio filter string
CHARACTER_VOICES = {
    "Peter":  {
        "voice":  "en-US-GuyNeural",
        "rate":   "-5%",      # slightly slower
        "pitch":  "-5Hz",     # slightly deeper
        "ffmpeg_filter": "atempo=0.95,asetrate=44100*0.97,aresample=44100",
    },
    "Stewie": {
        "voice":  "en-GB-RyanNeural",
        "rate":   "+5%",      # slightly faster / clipped
        "pitch":  "+10Hz",
        "ffmpeg_filter": "atempo=1.05,asetrate=44100*1.05,aresample=44100",
    },
    "Rick":   {
        "voice":  "en-US-DavisNeural",
        "rate":   "-10%",
        "pitch":  "-8Hz",
        "ffmpeg_filter": "atempo=0.90,asetrate=44100*0.95,aresample=44100",
    },
    "Morty":  {
        "voice":  "en-US-JasonNeural",
        "rate":   "+10%",
        "pitch":  "+5Hz",
        "ffmpeg_filter": "atempo=1.08,asetrate=44100*1.03,aresample=44100",
    },
    "Lois":   {
        "voice":  "en-US-JennyNeural",
        "rate":   "0%",
        "pitch":  "0Hz",
        "ffmpeg_filter": None,
    },
    "Meg":    {
        "voice":  "en-US-AriaNeural",
        "rate":   "-5%",
        "pitch":  "-3Hz",
        "ffmpeg_filter": "atempo=0.97",
    },
    "Narrator": {
        "voice":  "en-US-AndrewNeural",
        "rate":   "0%",
        "pitch":  "0Hz",
        "ffmpeg_filter": None,
    },
    # Fallback for unknown characters
    "_default": {
        "voice":  "en-US-GuyNeural",
        "rate":   "0%",
        "pitch":  "0Hz",
        "ffmpeg_filter": None,
    },
}

# ── Greek voice overrides (auto-used when Greek text is detected) ──────────────
GREEK_VOICES = {
    "male": {
        "voice":  "el-GR-NestorasNeural",
        "rate":   "0%",
        "pitch":  "0Hz",
        "ffmpeg_filter": None,
    },
    "female": {
        "voice":  "el-GR-AthinaNeural",
        "rate":   "0%",
        "pitch":  "0Hz",
        "ffmpeg_filter": None,
    },
}

# Characters treated as female for voice selection
FEMALE_CHARACTERS = {"lois", "meg", "aria", "elena", "maria", "athina", "anna"}

# ── Whisper model ──────────────────────────────────────────────────────────────
WHISPER_MODEL  = "base"      # tiny | base | small | medium | large-v3
WHISPER_DEVICE = "auto"      # "cpu" | "cuda" | "auto"

# ── FFmpeg ─────────────────────────────────────────────────────────────────────
CPU_THREADS = os.cpu_count() or 4

# Font for captions — Arial Bold first so Greek characters render correctly.
# Impact looks great for English but lacks Greek Unicode glyphs.
CAPTION_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",   # Arial Bold — supports Greek & Latin
    "C:/Windows/Fonts/arialuni.ttf",  # Arial Unicode MS — widest coverage
    "C:/Windows/Fonts/impact.ttf",    # Impact — classic brainrot (English only)
    "C:/Windows/Fonts/arial.ttf",
]

def get_caption_font_path() -> str:
    for p in CAPTION_FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None   # PIL will use default bitmap font as last resort

# ── JSON script format ─────────────────────────────────────────────────────────
# Expected structure:
# {
#   "script": [
#     {
#       "character": "Peter",
#       "text": "Hey Lois!",
#       "avatar": "/path/to/peter.png"   ← optional, can be empty string
#     },
#     ...
#   ]
# }
#
# Top-level key can be "script", "scenes", or "lines" (all accepted).
SCRIPT_KEYS = ["script", "scenes", "lines"]
