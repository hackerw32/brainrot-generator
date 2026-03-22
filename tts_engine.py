"""
tts_engine.py - Text-to-Speech engine

Priority order for Greek text:
  1. Coqui XTTS-v2  (local, human-quality, voice cloning)
  2. gTTS           (Google, excellent Greek, needs internet)
  3. edge-tts       (Microsoft Neural, Greek voices)
  4. pyttsx3        (offline fallback)

Priority order for English/other text:
  1. edge-tts  (Microsoft Neural)
  2. pyttsx3   (offline fallback)
"""

import asyncio
import subprocess
import os
import threading
import unicodedata
from pathlib import Path
from typing import Optional, Callable

from config import CHARACTER_VOICES, GREEK_VOICES, FEMALE_CHARACTERS, TEMP_DIR, CPU_THREADS

# ── Engine availability detection ─────────────────────────────────────────────

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False

try:
    import pyttsx3
    PYTTSX3_AVAILABLE = True
except ImportError:
    PYTTSX3_AVAILABLE = False

try:
    from gtts import gTTS as _gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False

# Coqui XTTS-v2: only import if installed; model is lazy-loaded on first use
try:
    from TTS.api import TTS as _CoquiTTS
    XTTS_AVAILABLE = True
except ImportError:
    XTTS_AVAILABLE = False

_xtts_model = None          # cached XTTS model instance
_xtts_lock  = threading.Lock()


# ── Language detection ─────────────────────────────────────────────────────────

def _is_greek(text: str) -> bool:
    """Return True if text contains Greek Unicode characters."""
    for ch in text:
        if ch.isspace() or not ch.isalpha():
            continue
        name = unicodedata.name(ch, "")
        if name.startswith("GREEK"):
            return True
    return False


# ── Voice config ───────────────────────────────────────────────────────────────

def get_character_config(character: str, text: str = "") -> dict:
    """
    Return edge-tts voice config for a character.
    Automatically switches to Greek Neural voices when Greek text is detected.
    """
    name = character.strip().title()
    cfg = CHARACTER_VOICES.get(name, CHARACTER_VOICES["_default"])
    if text and _is_greek(text):
        gender = "female" if character.lower() in FEMALE_CHARACTERS else "male"
        cfg = dict(GREEK_VOICES[gender])
    return cfg


# ── XTTS-v2 (Coqui) ───────────────────────────────────────────────────────────

def _get_xtts():
    """Lazy-load the XTTS-v2 model (first call downloads ~1.8 GB)."""
    global _xtts_model
    if _xtts_model is None:
        with _xtts_lock:
            if _xtts_model is None:
                _xtts_model = _CoquiTTS("tts_models/multilingual/multi-dataset/xtts_v2")
    return _xtts_model


def generate_with_xtts(text: str, out_path: Path,
                        speaker_wav: Optional[str] = None,
                        language: str = "el",
                        log: Optional[Callable] = None) -> bool:
    """
    Generate speech with Coqui XTTS-v2.
    speaker_wav: path to a reference audio clip (5–30 sec) for voice cloning.
                 If None, uses the built-in default speaker.
    language:    ISO code — "el" for Greek, "en" for English, etc.
    """
    if not XTTS_AVAILABLE:
        return False
    try:
        if log:
            ref = Path(speaker_wav).name if speaker_wav else "default"
            log(f"[TTS] XTTS-v2 | lang={language} | speaker={ref}")
        tts = _get_xtts()
        kwargs = dict(text=text, language=language, file_path=str(out_path))
        if speaker_wav and Path(speaker_wav).exists():
            kwargs["speaker_wav"] = speaker_wav
        else:
            # Use the first available built-in speaker
            speakers = getattr(tts, "speakers", None)
            if speakers:
                kwargs["speaker"] = speakers[0]
        tts.tts_to_file(**kwargs)
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception as e:
        if log:
            log(f"[TTS] XTTS-v2 failed: {e}")
        return False


# ── gTTS (Google) ──────────────────────────────────────────────────────────────

def generate_with_gtts(text: str, out_path: Path,
                        lang: str = "el",
                        log: Optional[Callable] = None) -> bool:
    """Generate speech with gTTS (Google TTS). Requires internet."""
    if not GTTS_AVAILABLE:
        if log:
            log("[TTS] gTTS not installed — run: pip install gtts")
        return False
    try:
        if log:
            log(f"[TTS] gTTS | lang={lang}")
        tts = _gTTS(text=text, lang=lang, slow=False)
        tts.save(str(out_path))
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception as e:
        if log:
            log(f"[TTS] gTTS failed ({type(e).__name__}: {e})")
        return False


# ── edge-tts (Microsoft Neural) ───────────────────────────────────────────────

async def _edge_tts_generate(text: str, voice: str, rate: str, pitch: str, out_path: Path):
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
    await communicate.save(str(out_path))


def generate_with_edge_tts(text: str, character: str, out_path: Path,
                            log: Optional[Callable] = None) -> bool:
    if not EDGE_TTS_AVAILABLE:
        return False
    cfg = get_character_config(character, text)
    if log:
        log(f"[TTS] edge-tts | character={character} | voice={cfg['voice']}")
    try:
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            _edge_tts_generate(text, cfg["voice"], cfg["rate"], cfg["pitch"], out_path)
        )
        loop.close()
        ffmpeg_filter = cfg.get("ffmpeg_filter")
        if ffmpeg_filter and out_path.exists():
            _apply_ffmpeg_audio_filter(out_path, ffmpeg_filter, log)
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception as e:
        if log:
            log(f"[TTS] edge-tts failed: {e}")
        return False


def _apply_ffmpeg_audio_filter(wav_path: Path, af_filter: str,
                                log: Optional[Callable] = None):
    tmp = wav_path.with_suffix(".tmp.mp3")
    cmd = [
        "ffmpeg", "-y", "-threads", str(CPU_THREADS),
        "-i", str(wav_path), "-af", af_filter,
        "-ar", "44100", "-ac", "1", str(tmp),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0 and tmp.exists():
        tmp.replace(wav_path)
        if log:
            log(f"[TTS] Audio filter applied: {af_filter}")
    else:
        if tmp.exists():
            tmp.unlink()
        if log:
            log(f"[TTS] Audio filter skipped: {result.stderr[-200:]}")


# ── pyttsx3 (offline fallback) ────────────────────────────────────────────────

def generate_with_pyttsx3(text: str, out_path: Path,
                           log: Optional[Callable] = None) -> bool:
    if not PYTTSX3_AVAILABLE:
        return False
    try:
        if log:
            log("[TTS] pyttsx3 (offline fallback)")
        engine = pyttsx3.init()
        engine.setProperty("rate", 165)
        engine.save_to_file(text, str(out_path))
        engine.runAndWait()
        engine.stop()
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception as e:
        if log:
            log(f"[TTS] pyttsx3 failed: {e}")
        return False


# ── Public API ────────────────────────────────────────────────────────────────

# Active TTS engine choice — set by GUI
# Values: "auto" | "xtts" | "gtts" | "edge-tts" | "pyttsx3"
_active_engine: str = "auto"
_xtts_speaker_wav: Optional[str] = None   # path to reference audio for XTTS


def set_engine(engine: str, xtts_speaker_wav: Optional[str] = None):
    """Called by GUI when the user selects an engine."""
    global _active_engine, _xtts_speaker_wav
    _active_engine = engine
    _xtts_speaker_wav = xtts_speaker_wav


def generate_speech(text: str, character: str, out_path: Path,
                    log: Optional[Callable] = None) -> bool:
    """
    Generate speech using the best available engine.
    Greek text → XTTS-v2 → gTTS → edge-tts Greek → pyttsx3
    Other text → edge-tts → pyttsx3
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    greek = _is_greek(text)
    lang_code = "el" if greek else "en"

    # ── Engine selection ───────────────────────────────────────────────────
    if _active_engine == "xtts":
        if generate_with_xtts(text, out_path, _xtts_speaker_wav, lang_code, log):
            return True
        if log:
            log("[TTS] XTTS failed, trying edge-tts...")

    elif _active_engine == "gtts":
        if generate_with_gtts(text, out_path, lang_code, log):
            return True
        if log:
            log("[TTS] gTTS failed, trying edge-tts...")

    elif _active_engine == "edge-tts":
        if generate_with_edge_tts(text, character, out_path, log):
            return True
        if log:
            log("[TTS] edge-tts failed, trying pyttsx3...")
        return generate_with_pyttsx3(text, out_path, log)

    elif _active_engine == "pyttsx3":
        return generate_with_pyttsx3(text, out_path, log)

    else:  # "auto"
        if greek:
            # Greek: XTTS → gTTS → edge-tts Greek → pyttsx3
            if XTTS_AVAILABLE:
                if generate_with_xtts(text, out_path, _xtts_speaker_wav, "el", log):
                    return True
            if GTTS_AVAILABLE:
                if generate_with_gtts(text, out_path, "el", log):
                    return True
        else:
            pass  # skip to edge-tts below

    # Common fallback path for all engines: edge-tts (with Greek voice if needed)
    # then pyttsx3 as last resort
    if EDGE_TTS_AVAILABLE:
        if generate_with_edge_tts(text, character, out_path, log):
            return True
        if log:
            log("[TTS] edge-tts failed, falling back to pyttsx3...")

    return generate_with_pyttsx3(text, out_path, log)


def check_status() -> dict:
    """Return a dict describing TTS engine availability."""
    return {
        "edge_tts":  EDGE_TTS_AVAILABLE,
        "gtts":      GTTS_AVAILABLE,
        "xtts":      XTTS_AVAILABLE,
        "pyttsx3":   PYTTSX3_AVAILABLE,
        "active":    _active_engine,
        "primary":   (
            "edge-tts" if EDGE_TTS_AVAILABLE
            else ("pyttsx3" if PYTTSX3_AVAILABLE else "none")
        ),
    }


def list_available_voices() -> list[str]:
    return [k for k in CHARACTER_VOICES if not k.startswith("_")]


def generate_all_lines(script_lines: list[dict],
                       output_dir: Path,
                       log: Optional[Callable] = None,
                       progress_cb: Optional[Callable] = None) -> list[dict]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    total = len(script_lines)
    for i, line in enumerate(script_lines):
        character = line.get("character", "Narrator")
        text      = line.get("text", "")
        out_file  = output_dir / f"line_{i:03d}.mp3"
        if log:
            log(f"[TTS] Line {i+1}/{total}: {character}: {text[:60]}...")
        success = generate_speech(text, character, out_file, log)
        line["audio_path"] = str(out_file) if success else None
        if progress_cb:
            progress_cb(i + 1, total)
    return script_lines
