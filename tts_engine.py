"""
tts_engine.py - Text-to-Speech engine
Primary: edge-tts (free, local runtime, Microsoft Neural voices, needs internet first time)
Fallback: pyttsx3 (fully offline, robotic but works)
"""

import asyncio
import subprocess
import os
import sys
import threading
from pathlib import Path
from typing import Optional, Callable

from config import CHARACTER_VOICES, TEMP_DIR, CPU_THREADS

# ── Try importing edge-tts ─────────────────────────────────────────────────────
try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False

# ── Try importing pyttsx3 ──────────────────────────────────────────────────────
try:
    import pyttsx3
    PYTTSX3_AVAILABLE = True
except ImportError:
    PYTTSX3_AVAILABLE = False


def get_character_config(character: str) -> dict:
    """Return voice config for a character, falling back to _default."""
    name = character.strip().title()
    return CHARACTER_VOICES.get(name, CHARACTER_VOICES["_default"])


# ── edge-tts (async) ──────────────────────────────────────────────────────────

async def _edge_tts_generate(text: str, voice: str, rate: str, pitch: str, out_path: Path):
    """Async edge-tts call."""
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
    await communicate.save(str(out_path))


def generate_with_edge_tts(text: str, character: str, out_path: Path,
                            log: Optional[Callable] = None) -> bool:
    """
    Generate speech using edge-tts.
    Returns True on success, False on failure.
    """
    cfg = get_character_config(character)
    if log:
        log(f"[TTS] edge-tts | character={character} | voice={cfg['voice']}")
    try:
        # Run async in a new event loop (safe to call from any thread)
        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            _edge_tts_generate(text, cfg["voice"], cfg["rate"], cfg["pitch"], out_path)
        )
        loop.close()

        # Apply FFmpeg audio effect if defined
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
    """Apply an ffmpeg audio filter chain in-place."""
    tmp = wav_path.with_suffix(".tmp.mp3")
    cmd = [
        "ffmpeg", "-y",
        "-threads", str(CPU_THREADS),
        "-i", str(wav_path),
        "-af", af_filter,
        "-ar", "44100",
        "-ac", "1",
        str(tmp),
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
            log(f"[TTS] Audio filter skipped (ffmpeg error): {result.stderr[-200:]}")


# ── pyttsx3 fallback ──────────────────────────────────────────────────────────

def generate_with_pyttsx3(text: str, out_path: Path,
                           log: Optional[Callable] = None) -> bool:
    """
    Generate speech using pyttsx3 (fully offline).
    Returns True on success, False on failure.
    """
    if not PYTTSX3_AVAILABLE:
        if log:
            log("[TTS] pyttsx3 not installed")
        return False
    try:
        if log:
            log("[TTS] Using pyttsx3 (offline fallback)")
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

def generate_speech(text: str, character: str, out_path: Path,
                    log: Optional[Callable] = None) -> bool:
    """
    Generate speech for `text` spoken by `character`.
    Tries edge-tts first, then pyttsx3 fallback.
    out_path: desired output file (will be .mp3 or .wav)
    Returns True on success.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if EDGE_TTS_AVAILABLE:
        if generate_with_edge_tts(text, character, out_path, log):
            return True
        if log:
            log("[TTS] edge-tts failed, trying pyttsx3...")

    return generate_with_pyttsx3(text, out_path, log)


def check_status() -> dict:
    """Return a dict describing TTS availability."""
    return {
        "edge_tts": EDGE_TTS_AVAILABLE,
        "pyttsx3":  PYTTSX3_AVAILABLE,
        "primary":  "edge-tts" if EDGE_TTS_AVAILABLE else ("pyttsx3" if PYTTSX3_AVAILABLE else "none"),
    }


def list_available_voices() -> list[str]:
    """Return list of known character names."""
    return [k for k in CHARACTER_VOICES if not k.startswith("_")]


# ── Async batch generation (used by renderer) ─────────────────────────────────

def generate_all_lines(script_lines: list[dict],
                       output_dir: Path,
                       log: Optional[Callable] = None,
                       progress_cb: Optional[Callable] = None) -> list[dict]:
    """
    Generate TTS audio for every line in the script.
    script_lines: list of {"character": str, "text": str, ...}
    Returns the same list with "audio_path" key added to each item.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    total = len(script_lines)

    for i, line in enumerate(script_lines):
        character = line.get("character", "Narrator")
        text      = line.get("text", "")
        out_file  = output_dir / f"line_{i:03d}.mp3"

        if log:
            log(f"[TTS] Line {i+1}/{total}: {character}: {text[:50]}...")

        success = generate_speech(text, character, out_file, log)
        line["audio_path"] = str(out_file) if success else None

        if progress_cb:
            progress_cb(i + 1, total)

    return script_lines
