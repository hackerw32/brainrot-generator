"""
video_renderer.py - FFmpeg-based video compositor
Uses all CPU cores (like slideshow_app.py pattern).
Karaoke captions: Pillow generates PNG frames → FFmpeg overlays them.
"""

import os
import json
import random
import subprocess
import threading
from pathlib import Path
from typing import Optional, Callable

from PIL import Image, ImageDraw, ImageFont
from config import (
    TEMP_DIR, CPU_THREADS,
    DEFAULT_FONT_COLOR, DEFAULT_STROKE_COLOR, DEFAULT_HIGHLIGHT_COLOR,
    DEFAULT_FONT_SIZE_1080, DEFAULT_FONT_SIZE_720,
    STROKE_WIDTH, get_caption_font_path,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _run(cmd: list, log: Optional[Callable] = None) -> bool:
    """Run an FFmpeg command. Returns True on success."""
    if log:
        log(f"[FFmpeg] {' '.join(str(c) for c in cmd[:8])}...")
    result = subprocess.run(cmd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode != 0 and log:
        log(f"[FFmpeg] Error: {result.stderr[-300:]}")
    return result.returncode == 0


def _get_bg_video(bg_folder: str | Path) -> Optional[Path]:
    """Pick a random background video from the folder."""
    folder = Path(bg_folder)
    videos = list(folder.glob("*.mp4")) + list(folder.glob("*.mov")) + list(folder.glob("*.mkv"))
    if not videos:
        return None
    return random.choice(videos)


def _loop_bg_video(src: Path, duration: float, out: Path,
                   width: int, height: int,
                   log: Optional[Callable] = None) -> bool:
    """Loop/subclip background video to match target duration + scale to portrait."""
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",          # infinite loop
        "-i", str(src),
        "-t", str(duration),
        "-vf", (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        ),
        "-an",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-threads", str(CPU_THREADS),
        str(out),
    ]
    return _run(cmd, log)


# ── Caption frame rendering (Pillow) ──────────────────────────────────────────

def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_path = get_caption_font_path()
    if font_path:
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _render_caption_frame(
    words: list[dict],
    active_word_idx: int,
    canvas_w: int,
    canvas_h: int,
    font_size: int,
    font_color: str,
    stroke_color: str,
    highlight_color: str,
    stroke_width: int,
) -> Image.Image:
    """
    Render a single caption frame (RGBA PNG).
    Words are displayed in a row; the active word is highlighted.
    """
    img  = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = _load_font(font_size)

    # Measure each word
    word_texts = [w["word"] for w in words]
    word_sizes = []
    for wt in word_texts:
        bbox = draw.textbbox((0, 0), wt + " ", font=font)
        word_sizes.append((bbox[2] - bbox[0], bbox[3] - bbox[1]))

    total_w = sum(s[0] for s in word_sizes)
    max_h   = max(s[1] for s in word_sizes) if word_sizes else font_size

    # Center horizontally, place in lower 40% of frame
    x = (canvas_w - total_w) // 2
    y = int(canvas_h * 0.60)

    for idx, (wt, (ww, wh)) in enumerate(zip(word_texts, word_sizes)):
        color = highlight_color if idx == active_word_idx else font_color

        # Draw stroke (outline)
        for dx in range(-stroke_width, stroke_width + 1):
            for dy in range(-stroke_width, stroke_width + 1):
                if dx == 0 and dy == 0:
                    continue
                draw.text((x + dx, y + dy), wt, font=font, fill=stroke_color)

        # Draw text
        draw.text((x, y), wt, font=font, fill=color)
        x += ww

    return img


def _build_caption_video(captions: list[dict],
                          canvas_w: int,
                          canvas_h: int,
                          font_size: int,
                          font_color: str,
                          stroke_color: str,
                          highlight_color: str,
                          stroke_width: int,
                          tmp_dir: Path,
                          log: Optional[Callable] = None) -> Optional[Path]:
    """
    Generate a transparent caption overlay video (.mov with prores_ks/rgba).
    Returns path to the generated file, or None on failure.

    Strategy:
    - For each caption group, create N frames (one per word being active).
    - Write a concat demuxer file so FFmpeg assembles them at exact durations.
    """
    frames_dir = tmp_dir / "caption_frames"
    frames_dir.mkdir(exist_ok=True)

    concat_lines = []  # ["file 'path'\nduration X\n", ...]
    fps = 30

    for cap_idx, cap in enumerate(captions):
        words     = cap["words"]
        cap_start = cap["start"]
        cap_end   = cap["end"]

        for word_idx, word in enumerate(words):
            w_start = word["start"]
            w_end   = word["end"]
            w_dur   = max(w_end - w_start, 0.033)  # min 1 frame

            frame_img = _render_caption_frame(
                words, word_idx,
                canvas_w, canvas_h,
                font_size, font_color, stroke_color, highlight_color, stroke_width,
            )
            frame_path = frames_dir / f"cap_{cap_idx:04d}_word_{word_idx:02d}.png"
            frame_img.save(str(frame_path), "PNG")

            concat_lines.append(f"file '{frame_path.as_posix()}'\nduration {w_dur:.4f}\n")

    if not concat_lines:
        return None

    # FFmpeg needs the last file listed twice (concat demuxer quirk)
    last_frame_path = frames_dir / f"cap_{len(captions)-1:04d}_word_{len(captions[-1]['words'])-1:02d}.png"
    concat_lines.append(f"file '{last_frame_path.as_posix()}'\n")

    concat_file = tmp_dir / "caption_concat.txt"
    concat_file.write_text("".join(concat_lines), encoding="utf-8")

    out_path = tmp_dir / "captions_overlay.mov"
    cmd = [
        "ffmpeg", "-y",
        "-f",       "concat",
        "-safe",    "0",
        "-i",       str(concat_file),
        "-vf",      f"scale={canvas_w}:{canvas_h}",
        "-c:v",     "qtrle",           # lossless + alpha
        "-pix_fmt", "argb",
        "-threads", str(CPU_THREADS),
        str(out_path),
    ]
    if not _run(cmd, log):
        # Fallback: use png codec
        out_path = tmp_dir / "captions_overlay_png.mov"
        cmd[-4] = "png"
        cmd[-2] = "rgba"
        cmd[-1] = str(out_path)
        if not _run(cmd, log):
            return None

    return out_path


# ── Avatar overlay ────────────────────────────────────────────────────────────

def _overlay_avatar(base_video: Path, avatar_png: Optional[str | Path],
                    out: Path, canvas_w: int, canvas_h: int,
                    log: Optional[Callable] = None) -> bool:
    """Overlay avatar PNG (top-left) on base video using FFmpeg."""
    if not avatar_png or not Path(avatar_png).exists():
        # No avatar — just copy
        cmd = [
            "ffmpeg", "-y",
            "-threads", str(CPU_THREADS),
            "-i", str(base_video),
            "-c", "copy",
            str(out),
        ]
        return _run(cmd, log)

    avatar_size = canvas_w // 4   # avatar takes ~25% of width
    cmd = [
        "ffmpeg", "-y",
        "-threads", str(CPU_THREADS),
        "-i",    str(base_video),
        "-i",    str(avatar_png),
        "-filter_complex",
        (
            f"[1:v]scale={avatar_size}:{avatar_size}[avatar];"
            f"[0:v][avatar]overlay=20:20"
        ),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf",    "20",
        "-threads", str(CPU_THREADS),
        "-an",
        str(out),
    ]
    return _run(cmd, log)


# ── Captions overlay ──────────────────────────────────────────────────────────

def _overlay_captions(base_video: Path, caption_overlay: Path,
                      out: Path, log: Optional[Callable] = None) -> bool:
    """Composite caption overlay (with alpha) on base video."""
    cmd = [
        "ffmpeg", "-y",
        "-threads", str(CPU_THREADS),
        "-i", str(base_video),
        "-i", str(caption_overlay),
        "-filter_complex",
        "[0:v][1:v]overlay=0:0:shortest=1",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf",    "18",
        "-threads", str(CPU_THREADS),
        "-an",
        str(out),
    ]
    return _run(cmd, log)


# ── Audio merge ───────────────────────────────────────────────────────────────

def _concat_audios(audio_paths: list[Path], out: Path,
                   log: Optional[Callable] = None) -> bool:
    """Concatenate multiple audio files into one using FFmpeg concat filter."""
    if len(audio_paths) == 1:
        import shutil
        shutil.copy(str(audio_paths[0]), str(out))
        return True

    inputs = []
    for p in audio_paths:
        inputs += ["-i", str(p)]

    n = len(audio_paths)
    filter_str = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[aout]"
    cmd = [
        "ffmpeg", "-y",
        "-threads", str(CPU_THREADS),
        *inputs,
        "-filter_complex", filter_str,
        "-map", "[aout]",
        "-ar", "44100",
        "-ac", "1",
        str(out),
    ]
    return _run(cmd, log)


def _mux_audio_video(video: Path, audio: Path, out: Path,
                     log: Optional[Callable] = None) -> bool:
    """Mux separate video and audio into final MP4."""
    cmd = [
        "ffmpeg", "-y",
        "-threads", str(CPU_THREADS),
        "-i", str(video),
        "-i", str(audio),
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(out),
    ]
    return _run(cmd, log)


# ── Main render pipeline ──────────────────────────────────────────────────────

def render_video(
    script_lines: list[dict],
    bg_folder:    str | Path,
    output_path:  str | Path,
    width:        int = 1080,
    height:       int = 1920,
    max_words:    int = 3,
    font_color:   str = DEFAULT_FONT_COLOR,
    stroke_color: str = DEFAULT_STROKE_COLOR,
    highlight_color: str = DEFAULT_HIGHLIGHT_COLOR,
    stroke_width: int = STROKE_WIDTH,
    log:          Optional[Callable] = None,
    progress_cb:  Optional[Callable] = None,
) -> bool:
    """
    Full render pipeline. script_lines must already have:
      - "audio_path"  (from tts_engine)
      - "captions"    (from whisper_alignment)
      - "duration"    (audio duration)
      - "avatar"      (PNG path, optional)

    Returns True on success.
    """
    output_path = Path(output_path)
    tmp = TEMP_DIR / "render"
    tmp.mkdir(parents=True, exist_ok=True)

    font_size = DEFAULT_FONT_SIZE_1080 if width >= 1080 else DEFAULT_FONT_SIZE_720
    total_steps = 6
    step = 0

    def _step(msg: str):
        nonlocal step
        step += 1
        if log:
            log(f"[Render] Step {step}/{total_steps}: {msg}")
        if progress_cb:
            progress_cb(step, total_steps)

    # ── 1. Calculate total duration ────────────────────────────────────────────
    total_duration = sum(line.get("duration", 0) for line in script_lines)
    if total_duration <= 0:
        if log:
            log("[Render] ERROR: total duration is 0. Did TTS run?")
        return False
    _step(f"Total duration: {total_duration:.1f}s")

    # ── 2. Pick & loop background video ───────────────────────────────────────
    bg_src = _get_bg_video(bg_folder)
    if not bg_src:
        if log:
            log(f"[Render] ERROR: No video files in {bg_folder}")
        return False

    bg_looped = tmp / "bg_looped.mp4"
    _step(f"Looping background: {bg_src.name}")
    if not _loop_bg_video(bg_src, total_duration, bg_looped, width, height, log):
        return False

    # ── 3. Build caption overlay video ────────────────────────────────────────
    _step("Rendering caption frames")

    # Merge all captions, adjusting timestamps per line offset
    all_captions = []
    time_offset = 0.0
    for line in script_lines:
        for cap in line.get("captions", []):
            shifted = {
                "words": [
                    {
                        "word":  w["word"],
                        "start": w["start"] + time_offset,
                        "end":   w["end"]   + time_offset,
                    }
                    for w in cap["words"]
                ],
                "start": cap["start"] + time_offset,
                "end":   cap["end"]   + time_offset,
            }
            all_captions.append(shifted)
        time_offset += line.get("duration", 0.0)

    caption_overlay = _build_caption_video(
        all_captions, width, height, font_size,
        font_color, stroke_color, highlight_color, stroke_width,
        tmp, log,
    )
    if not caption_overlay:
        if log:
            log("[Render] Warning: caption overlay failed, continuing without captions")

    # ── 4. Overlay avatar (use first line's avatar for now) ────────────────────
    _step("Overlaying avatars")
    first_avatar = next(
        (line.get("avatar") for line in script_lines if line.get("avatar")), None
    )
    with_avatar = tmp / "with_avatar.mp4"
    _overlay_avatar(bg_looped, first_avatar, with_avatar, width, height, log)

    # ── 5. Composite captions ─────────────────────────────────────────────────
    _step("Compositing captions")
    if caption_overlay and caption_overlay.exists():
        with_captions = tmp / "with_captions.mp4"
        if not _overlay_captions(with_avatar, caption_overlay, with_captions, log):
            with_captions = with_avatar   # fallback
    else:
        with_captions = with_avatar

    # ── 6. Merge audio + mux ──────────────────────────────────────────────────
    _step("Merging audio & finalising")
    audio_paths = [
        Path(line["audio_path"])
        for line in script_lines
        if line.get("audio_path") and Path(line["audio_path"]).exists()
    ]
    if not audio_paths:
        if log:
            log("[Render] ERROR: no audio files to merge")
        return False

    merged_audio = tmp / "merged_audio.m4a"
    if not _concat_audios(audio_paths, merged_audio, log):
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    success = _mux_audio_video(with_captions, merged_audio, output_path, log)

    if success and log:
        log(f"[Render] DONE → {output_path}")
    return success


# ── Quick preview (no full render) ───────────────────────────────────────────

def generate_preview_frame(
    caption_text: str,
    active_word_idx: int,
    canvas_w: int = 540,
    canvas_h: int = 960,
    font_size: int = 55,
    font_color: str = DEFAULT_FONT_COLOR,
    stroke_color: str = DEFAULT_STROKE_COLOR,
    highlight_color: str = DEFAULT_HIGHLIGHT_COLOR,
    stroke_width: int = STROKE_WIDTH,
    bg_image: Optional[Image.Image] = None,
) -> Image.Image:
    """
    Generate a single preview frame (Pillow Image) instantly.
    Used by the GUI live preview — no FFmpeg, no file I/O.
    """
    words = [{"word": w} for w in caption_text.split()]

    if bg_image:
        img = bg_image.resize((canvas_w, canvas_h)).convert("RGBA")
    else:
        img = Image.new("RGBA", (canvas_w, canvas_h), (30, 30, 30, 255))

    caption_layer = _render_caption_frame(
        words, active_word_idx,
        canvas_w, canvas_h,
        font_size, font_color, stroke_color, highlight_color, stroke_width,
    )
    img = Image.alpha_composite(img, caption_layer)
    return img.convert("RGB")
