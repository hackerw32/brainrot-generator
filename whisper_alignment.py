"""
whisper_alignment.py - Word-level timestamp extraction using faster-whisper
"""

import os
from pathlib import Path
from typing import Optional, Callable

from config import WHISPER_MODEL, WHISPER_DEVICE, CPU_THREADS

# ── Import faster-whisper ──────────────────────────────────────────────────────
try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER_AVAILABLE = True
except ImportError:
    FASTER_WHISPER_AVAILABLE = False


_model_cache: dict = {}   # cache loaded model by (model_size, device)


def _load_model(model_size: str = WHISPER_MODEL,
                device: str = WHISPER_DEVICE) -> "WhisperModel":
    """Load (or return cached) WhisperModel."""
    if not FASTER_WHISPER_AVAILABLE:
        raise RuntimeError(
            "faster-whisper is not installed. Run: pip install faster-whisper"
        )

    # Auto-detect device
    if device == "auto":
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"

    compute_type = "float16" if device == "cuda" else "int8"
    key = (model_size, device)

    if key not in _model_cache:
        _model_cache[key] = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            cpu_threads=CPU_THREADS,
        )
    return _model_cache[key]


def transcribe_audio(audio_path: str | Path,
                     model_size: str = WHISPER_MODEL,
                     log: Optional[Callable] = None) -> list[dict]:
    """
    Transcribe an audio file and return word-level timestamps.

    Returns a list of word dicts:
    [
        {"word": "Hello", "start": 0.0, "end": 0.42},
        {"word": "world", "start": 0.50, "end": 0.82},
        ...
    ]
    """
    audio_path = Path(audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    if log:
        log(f"[Whisper] Loading model '{model_size}'...")

    model = _load_model(model_size)

    if log:
        log(f"[Whisper] Transcribing {audio_path.name}...")

    segments, info = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        language=None,          # auto-detect language
        beam_size=5,
    )

    words = []
    for segment in segments:
        if segment.words:
            for w in segment.words:
                words.append({
                    "word":  w.word.strip(),
                    "start": round(w.start, 3),
                    "end":   round(w.end,   3),
                })

    if log:
        log(f"[Whisper] Done. {len(words)} words detected. "
            f"Language: {info.language} ({info.language_probability:.0%})")

    return words


def group_words_into_captions(words: list[dict],
                               max_words: int = 3) -> list[dict]:
    """
    Group words into caption segments (max N words per screen).

    Returns list of:
    {
        "text":        "Hey Lois this",   # full caption text
        "words":       [{"word":..., "start":..., "end":...}, ...],
        "start":       0.0,               # caption start time
        "end":         1.2,               # caption end time
        "active_word_index": int          # which word is currently spoken
                                          # (used for karaoke highlight)
    }
    """
    if not words:
        return []

    captions = []
    for i in range(0, len(words), max_words):
        chunk = words[i : i + max_words]
        text  = " ".join(w["word"] for w in chunk)
        captions.append({
            "text":  text,
            "words": chunk,
            "start": chunk[0]["start"],
            "end":   chunk[-1]["end"],
        })

    return captions


def get_audio_duration(audio_path: str | Path) -> float:
    """Return audio duration in seconds using ffprobe."""
    import subprocess, json
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            str(audio_path),
        ],
        capture_output=True, text=True,
    )
    try:
        data = json.loads(result.stdout)
        return float(data["streams"][0]["duration"])
    except Exception:
        return 0.0


def transcribe_all_lines(script_lines: list[dict],
                          max_words: int = 3,
                          log: Optional[Callable] = None,
                          progress_cb: Optional[Callable] = None) -> list[dict]:
    """
    For every line that has an "audio_path", transcribe it and attach
    "words" (raw word timestamps) and "captions" (grouped segments).

    Returns the updated script_lines list.
    """
    total = len(script_lines)
    for i, line in enumerate(script_lines):
        audio_path = line.get("audio_path")
        if not audio_path or not Path(audio_path).exists():
            if log:
                log(f"[Whisper] Line {i+1}/{total}: no audio, skipping")
            line["words"]    = []
            line["captions"] = []
            continue

        try:
            words    = transcribe_audio(audio_path, log=log)
            captions = group_words_into_captions(words, max_words=max_words)
            line["words"]    = words
            line["captions"] = captions
            line["duration"] = get_audio_duration(audio_path)
        except Exception as e:
            if log:
                log(f"[Whisper] Line {i+1} failed: {e}")
            line["words"]    = []
            line["captions"] = []
            line["duration"] = 0.0

        if progress_cb:
            progress_cb(i + 1, total)

    return script_lines
