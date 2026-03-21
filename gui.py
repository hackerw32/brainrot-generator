"""
gui.py - Main CustomTkinter GUI for the Local Brainrot Generator
Dark theme matching the mockup: purple/cyan accents
"""

import json
import os
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk
from PIL import Image, ImageTk

from config import (
    RESOLUTIONS, DEFAULT_RESOLUTION,
    DEFAULT_FONT_COLOR, DEFAULT_STROKE_COLOR, DEFAULT_HIGHLIGHT_COLOR,
    DEFAULT_MAX_WORDS, SCRIPT_KEYS,
)
from tts_engine import check_status, generate_all_lines, list_available_voices
from whisper_alignment import transcribe_all_lines
from video_renderer import render_video, generate_preview_frame

# ── Theme ──────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

PURPLE  = "#9B59B6"
CYAN    = "#00BCD4"
DARK_BG = "#1A1A2E"
PANEL   = "#16213E"
CARD    = "#0F3460"
GREEN   = "#27AE60"
RED     = "#E74C3C"
YELLOW  = "#F1C40F"


# ─────────────────────────────────────────────────────────────────────────────
class BrainrotApp(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("LOCAL BRAINROT GENERATOR - Character Voices & Dynamic Captions")
        self.geometry("1300x760")
        self.minsize(1100, 680)
        self.configure(fg_color=DARK_BG)

        # ── State ──────────────────────────────────────────────────────────────
        self.script_lines:   list[dict] = []
        self.bg_folder:      Optional[str] = None
        self.avatars_folder: Optional[str] = None
        self.font_color      = DEFAULT_FONT_COLOR
        self.stroke_color    = DEFAULT_STROKE_COLOR
        self.highlight_color = DEFAULT_HIGHLIGHT_COLOR

        # Preview animation state
        self._preview_thread:  Optional[threading.Thread] = None
        self._preview_running: bool = False
        self._preview_image:   Optional[ImageTk.PhotoImage] = None

        # Render thread
        self._render_thread: Optional[threading.Thread] = None

        self._build_ui()
        self._update_tts_status()

    # ── UI Construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        """Build the 3-column layout matching the mockup."""
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=3)
        self.grid_columnconfigure(2, weight=4)
        self.grid_rowconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=0)

        # Header
        header = ctk.CTkLabel(
            self, text="LOCAL BRAINROT GENERATOR - Character Voices & Dynamic Captions",
            font=ctk.CTkFont(family="Arial", size=16, weight="bold"),
            text_color=CYAN,
        )
        header.grid(row=0, column=0, columnspan=3, sticky="ew", padx=20, pady=(10, 0))

        # Columns
        self._build_left_panel()
        self._build_middle_panel()
        self._build_right_panel()

        # Status bar
        self._status_var = tk.StringVar(value="Ready.")
        status_bar = ctk.CTkLabel(
            self, textvariable=self._status_var,
            font=ctk.CTkFont(size=11), text_color="gray70",
            fg_color="#0A0A1A",
        )
        status_bar.grid(row=2, column=0, columnspan=3, sticky="ew", padx=0, pady=0)

    # ── Left panel: Script ─────────────────────────────────────────────────────

    def _build_left_panel(self):
        frame = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10,
                             border_width=1, border_color=PURPLE)
        frame.grid(row=1, column=0, padx=(12, 6), pady=10, sticky="nsew")
        frame.grid_rowconfigure(2, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        # Title
        ctk.CTkLabel(frame, text="SCRIPT INPUT", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=PURPLE).grid(row=0, column=0, columnspan=2, pady=(10, 4), padx=10, sticky="w")

        # Load JSON row
        load_row = ctk.CTkFrame(frame, fg_color="transparent")
        load_row.grid(row=1, column=0, padx=10, pady=(0, 6), sticky="ew")
        load_row.grid_columnconfigure(0, weight=1)

        self._json_path_var = tk.StringVar(value="No file loaded")
        ctk.CTkLabel(load_row, textvariable=self._json_path_var,
                     text_color="gray70", font=ctk.CTkFont(size=11),
                     wraplength=200, justify="left").grid(row=0, column=0, sticky="w")

        ctk.CTkButton(load_row, text="LOAD JSON SCRIPT", width=140,
                      fg_color=PURPLE, hover_color="#7D3C98",
                      command=self._load_json).grid(row=0, column=1, padx=(6, 0))

        # Script text preview
        self._script_text = ctk.CTkTextbox(
            frame, fg_color=CARD, text_color="#E0E0E0",
            font=ctk.CTkFont(family="Consolas", size=12),
            wrap="word",
        )
        self._script_text.grid(row=2, column=0, padx=10, pady=(0, 6), sticky="nsew")

        # TTS status
        self._tts_status_var = tk.StringVar(value="Checking TTS...")
        ctk.CTkLabel(frame, textvariable=self._tts_status_var,
                     text_color=CYAN, font=ctk.CTkFont(size=11),
                     wraplength=260).grid(row=3, column=0, padx=10, pady=(0, 10), sticky="w")

    # ── Middle panel: Assets + Caption Styling ─────────────────────────────────

    def _build_middle_panel(self):
        frame = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10,
                             border_width=1, border_color=PURPLE)
        frame.grid(row=1, column=1, padx=6, pady=10, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)

        # ── Asset management ───────────────────────────────────────────────────
        ctk.CTkLabel(frame, text="ASSET MANAGEMENT", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=PURPLE).grid(row=0, column=0, pady=(10, 4), padx=10, sticky="w")

        # BG Videos
        bg_row = ctk.CTkFrame(frame, fg_color="transparent")
        bg_row.grid(row=1, column=0, padx=10, pady=3, sticky="ew")
        bg_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(bg_row, text="SELECT BG VIDEOS FOLDER",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(bg_row, text="BROWSE", width=90,
                      fg_color=CYAN, hover_color="#0097A7", text_color="black",
                      command=self._select_bg_folder).grid(row=0, column=1, padx=(6, 0))

        self._bg_label = ctk.CTkLabel(frame, text="Not selected", text_color="gray60",
                                      font=ctk.CTkFont(size=10), wraplength=260, justify="left")
        self._bg_label.grid(row=2, column=0, padx=10, sticky="w")

        # Avatars
        av_row = ctk.CTkFrame(frame, fg_color="transparent")
        av_row.grid(row=3, column=0, padx=10, pady=(8, 3), sticky="ew")
        av_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(av_row, text="LOAD CHARACTER AVATARS",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(av_row, text="BROWSE", width=90,
                      fg_color=CYAN, hover_color="#0097A7", text_color="black",
                      command=self._select_avatars_folder).grid(row=0, column=1, padx=(6, 0))

        self._avatars_label = ctk.CTkLabel(frame, text="Not selected", text_color="gray60",
                                           font=ctk.CTkFont(size=10), wraplength=260, justify="left")
        self._avatars_label.grid(row=4, column=0, padx=10, sticky="w")

        # Avatar thumbnails strip
        self._avatar_strip_frame = ctk.CTkFrame(frame, fg_color="transparent", height=64)
        self._avatar_strip_frame.grid(row=5, column=0, padx=10, pady=4, sticky="ew")

        ctk.CTkFrame(frame, height=2, fg_color=PURPLE).grid(
            row=6, column=0, padx=10, pady=8, sticky="ew")

        # ── Caption Styling ────────────────────────────────────────────────────
        ctk.CTkLabel(frame, text="CAPTION STYLING", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=PURPLE).grid(row=7, column=0, pady=(0, 6), padx=10, sticky="w")

        self._add_color_row(frame, 8,  "Default Font",       self.font_color,      self._pick_font_color)
        self._add_color_row(frame, 9,  "Stroke",             self.stroke_color,    self._pick_stroke_color)
        self._add_color_row(frame, 10, "Speaking Highlight", self.highlight_color, self._pick_highlight_color)

        # Max words
        mw_row = ctk.CTkFrame(frame, fg_color="transparent")
        mw_row.grid(row=11, column=0, padx=10, pady=(8, 4), sticky="ew")
        mw_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(mw_row, text="Max Words per Screen",
                     font=ctk.CTkFont(size=12)).grid(row=0, column=0, sticky="w")
        self._max_words_var = tk.IntVar(value=DEFAULT_MAX_WORDS)
        mw_spin = ctk.CTkEntry(mw_row, width=50, justify="center",
                               textvariable=self._max_words_var)
        mw_spin.grid(row=0, column=1, padx=(6, 0))

        mw_slider = ctk.CTkSlider(frame, from_=1, to=5, number_of_steps=4,
                                  variable=self._max_words_var,
                                  button_color=PURPLE, progress_color=PURPLE)
        mw_slider.grid(row=12, column=0, padx=10, pady=(0, 8), sticky="ew")

        # Resolution
        ctk.CTkLabel(frame, text="Output Resolution",
                     font=ctk.CTkFont(size=12)).grid(row=13, column=0, padx=10, sticky="w")
        self._resolution_var = tk.StringVar(value=DEFAULT_RESOLUTION)
        ctk.CTkOptionMenu(frame, values=list(RESOLUTIONS.keys()),
                          variable=self._resolution_var,
                          fg_color=CARD, button_color=PURPLE).grid(
            row=14, column=0, padx=10, pady=(2, 10), sticky="ew")

    def _add_color_row(self, parent, row, label, initial_color, command):
        """Add a label + color swatch button row."""
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid(row=row, column=0, padx=10, pady=2, sticky="ew")
        f.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(f, text=label, font=ctk.CTkFont(size=12)).grid(row=0, column=0, sticky="w")
        btn = tk.Button(f, bg=initial_color, width=4, relief="flat",
                        cursor="hand2", command=command)
        btn.grid(row=0, column=1)
        # Store reference for update
        setattr(self, f"_color_btn_{label.replace(' ', '_')}", btn)

    # ── Right panel: Preview + Render ─────────────────────────────────────────

    def _build_right_panel(self):
        frame = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10,
                             border_width=1, border_color=CYAN)
        frame.grid(row=1, column=2, padx=(6, 12), pady=10, sticky="nsew")
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(frame, text="LIVE PREVIEW & RENDER",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=CYAN).grid(row=0, column=0, pady=(10, 4), padx=10, sticky="w")

        # Preview canvas
        preview_card = ctk.CTkFrame(frame, fg_color=CARD, corner_radius=8)
        preview_card.grid(row=1, column=0, padx=10, pady=4, sticky="nsew")
        preview_card.grid_rowconfigure(0, weight=1)
        preview_card.grid_columnconfigure(0, weight=1)

        self._preview_canvas = tk.Canvas(preview_card, bg="#0A0A0A",
                                         highlightthickness=0)
        self._preview_canvas.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        # Preview controls row
        ctrl_row = ctk.CTkFrame(frame, fg_color="transparent")
        ctrl_row.grid(row=2, column=0, padx=10, pady=4, sticky="ew")
        ctrl_row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(ctrl_row, text="LIVE PREVIEW (Draft with basic TTS)",
                     font=ctk.CTkFont(size=11), text_color="gray60").grid(row=0, column=0, sticky="w")
        ctk.CTkButton(ctrl_row, text="▶ PREVIEW", width=100,
                      fg_color=GREEN, hover_color="#1E8449",
                      command=self._start_preview).grid(row=0, column=2, padx=(6, 0))

        ctk.CTkFrame(frame, height=2, fg_color=CYAN).grid(
            row=3, column=0, padx=10, pady=6, sticky="ew")

        # Generate button
        ctk.CTkButton(
            frame,
            text="GENERATE FINAL VIDEO",
            font=ctk.CTkFont(size=15, weight="bold"),
            height=50,
            fg_color=PURPLE, hover_color="#7D3C98",
            command=self._start_render,
        ).grid(row=4, column=0, padx=10, pady=(0, 6), sticky="ew")

        # Progress
        ctk.CTkLabel(frame, text="RENDER PROGRESS",
                     font=ctk.CTkFont(size=11), text_color="gray60").grid(
            row=5, column=0, padx=10, sticky="w")

        self._progress_var = tk.DoubleVar(value=0)
        self._progress_bar = ctk.CTkProgressBar(frame, variable=self._progress_var,
                                                 progress_color=PURPLE, height=18)
        self._progress_bar.grid(row=6, column=0, padx=10, pady=(0, 10), sticky="ew")
        self._progress_bar.set(0)

        # Log box
        self._log_box = ctk.CTkTextbox(frame, height=120, fg_color=CARD,
                                        font=ctk.CTkFont(family="Consolas", size=10),
                                        text_color="gray80", state="disabled")
        self._log_box.grid(row=7, column=0, padx=10, pady=(0, 10), sticky="ew")

    # ── Actions ────────────────────────────────────────────────────────────────

    def _load_json(self):
        path = filedialog.askopenfilename(
            title="Load JSON Script",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)

            # Accept top-level key "script", "scenes", or "lines"
            lines = None
            if isinstance(data, list):
                lines = data
            else:
                for key in SCRIPT_KEYS:
                    if key in data:
                        lines = data[key]
                        break

            if not lines or not isinstance(lines, list):
                messagebox.showerror("Format Error",
                    f"Expected a list under key {SCRIPT_KEYS} or a root JSON array.")
                return

            self.script_lines = lines
            self._json_path_var.set(Path(path).name)
            self._update_script_preview()
            self._log(f"Loaded {len(lines)} lines from {Path(path).name}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not load JSON:\n{e}")

    def _update_script_preview(self):
        self._script_text.configure(state="normal")
        self._script_text.delete("1.0", "end")
        for line in self.script_lines:
            char = line.get("character", "?")
            text = line.get("text", "")
            self._script_text.insert("end", f"{char}: {text}\n\n")
        self._script_text.configure(state="disabled")

    def _select_bg_folder(self):
        folder = filedialog.askdirectory(title="Select Background Videos Folder")
        if folder:
            self.bg_folder = folder
            count = len(list(Path(folder).glob("*.mp4")) +
                        list(Path(folder).glob("*.mov")) +
                        list(Path(folder).glob("*.mkv")))
            self._bg_label.configure(
                text=f"{Path(folder).name}/ ({count} videos)",
                text_color="gray80",
            )
            self._log(f"BG folder: {folder} ({count} videos)")

    def _select_avatars_folder(self):
        folder = filedialog.askdirectory(title="Select Avatars Folder")
        if folder:
            self.avatars_folder = folder
            pngs = list(Path(folder).glob("*.png")) + list(Path(folder).glob("*.PNG"))
            self._avatars_label.configure(
                text=f"{Path(folder).name}/ ({len(pngs)} avatars)",
                text_color="gray80",
            )
            self._show_avatar_thumbnails(pngs)
            self._log(f"Avatars folder: {folder} ({len(pngs)} PNGs)")
            self._auto_assign_avatars(pngs)

    def _show_avatar_thumbnails(self, pngs: list[Path]):
        """Show small thumbnails of the avatar PNGs in the strip."""
        for widget in self._avatar_strip_frame.winfo_children():
            widget.destroy()
        self._thumb_refs = []
        for i, png in enumerate(pngs[:6]):
            try:
                img = Image.open(png).resize((54, 54), Image.LANCZOS)
                tk_img = ImageTk.PhotoImage(img)
                self._thumb_refs.append(tk_img)
                lbl = tk.Label(self._avatar_strip_frame, image=tk_img,
                               bg="#16213E", cursor="hand2")
                lbl.pack(side="left", padx=2)
            except Exception:
                pass

    def _auto_assign_avatars(self, pngs: list[Path]):
        """Try to auto-match avatar filenames to characters in the script."""
        for line in self.script_lines:
            if line.get("avatar"):
                continue
            char = line.get("character", "").lower()
            for png in pngs:
                if char in png.stem.lower():
                    line["avatar"] = str(png)
                    break

    # ── Color pickers ──────────────────────────────────────────────────────────

    def _pick_color(self, attr: str, btn_attr: str):
        from tkinter import colorchooser
        current = getattr(self, attr)
        color = colorchooser.askcolor(color=current, title="Pick color")[1]
        if color:
            setattr(self, attr, color)
            btn = getattr(self, btn_attr, None)
            if btn:
                btn.configure(bg=color)
            self._log(f"{attr} = {color}")

    def _pick_font_color(self):
        self._pick_color("font_color", "_color_btn_Default_Font")

    def _pick_stroke_color(self):
        self._pick_color("stroke_color", "_color_btn_Stroke")

    def _pick_highlight_color(self):
        self._pick_color("highlight_color", "_color_btn_Speaking_Highlight")

    # ── TTS status ─────────────────────────────────────────────────────────────

    def _update_tts_status(self):
        status = check_status()
        primary = status["primary"]
        if primary == "none":
            msg = "TTS Status: NO engine available! Run: pip install edge-tts"
            color = RED
        elif primary == "edge-tts":
            msg = "TTS Status: edge-tts ready (Microsoft Neural voices)"
            color = GREEN
        else:
            msg = "TTS Status: pyttsx3 (offline fallback, basic quality)"
            color = YELLOW
        self._tts_status_var.set(msg)

    # ── Live preview ───────────────────────────────────────────────────────────

    def _start_preview(self):
        if not self.script_lines:
            messagebox.showwarning("No Script", "Please load a JSON script first.")
            return

        self._preview_running = False
        if self._preview_thread and self._preview_thread.is_alive():
            time.sleep(0.1)

        self._preview_running = True
        self._preview_thread = threading.Thread(target=self._preview_loop, daemon=True)
        self._preview_thread.start()

    def _preview_loop(self):
        """
        Animate the captions over a blank dark background in the preview canvas.
        Uses generate_preview_frame() — instant, no FFmpeg.
        """
        max_words = self._max_words_var.get()
        canvas_w  = self._preview_canvas.winfo_width()  or 300
        canvas_h  = self._preview_canvas.winfo_height() or 480
        font_size = max(36, canvas_w // 8)

        for line in self.script_lines:
            if not self._preview_running:
                break

            text  = line.get("text", "")
            words = text.split()
            if not words:
                continue

            # Show each group of max_words for 1.5s each
            for i in range(0, len(words), max_words):
                if not self._preview_running:
                    break
                chunk = words[i : i + max_words]

                # Animate word-by-word highlight
                for active in range(len(chunk)):
                    if not self._preview_running:
                        break

                    frame = generate_preview_frame(
                        " ".join(chunk), active,
                        canvas_w, canvas_h, font_size,
                        self.font_color, self.stroke_color, self.highlight_color,
                    )
                    tk_img = ImageTk.PhotoImage(frame)

                    def _update_canvas(img=tk_img, cw=canvas_w, ch=canvas_h):
                        self._preview_canvas.delete("all")
                        self._preview_canvas.create_image(
                            cw // 2, ch // 2, image=img, anchor="center")
                        self._preview_image = img  # keep reference

                    self.after(0, _update_canvas)
                    time.sleep(0.4)

        self._preview_running = False

    # ── Render pipeline ────────────────────────────────────────────────────────

    def _start_render(self):
        if self._render_thread and self._render_thread.is_alive():
            messagebox.showinfo("Busy", "A render is already in progress.")
            return
        if not self.script_lines:
            messagebox.showwarning("No Script", "Please load a JSON script first.")
            return
        if not self.bg_folder:
            messagebox.showwarning("No BG Videos", "Please select a background videos folder.")
            return

        output_path = filedialog.asksaveasfilename(
            title="Save Video As",
            defaultextension=".mp4",
            filetypes=[("MP4 video", "*.mp4")],
            initialfile="brainrot_output.mp4",
        )
        if not output_path:
            return

        res_key = self._resolution_var.get()
        width, height = RESOLUTIONS[res_key]

        self._progress_bar.set(0)
        self._log("=== Starting render pipeline ===")

        self._render_thread = threading.Thread(
            target=self._render_pipeline,
            args=(output_path, width, height),
            daemon=True,
        )
        self._render_thread.start()

    def _render_pipeline(self, output_path: str, width: int, height: int):
        """Full pipeline: TTS → Whisper → Video render. Runs in a background thread."""
        from config import TEMP_DIR
        tmp_audio = TEMP_DIR / "tts_audio"
        max_words = self._max_words_var.get()
        lines     = [dict(l) for l in self.script_lines]  # copy

        total_phases = 3

        # ── Phase 1: TTS ───────────────────────────────────────────────────────
        self._log("Phase 1/3: Generating TTS audio...")
        self._set_progress(0.0)

        def tts_progress(done, total):
            self._set_progress(done / total / total_phases)

        lines = generate_all_lines(lines, tmp_audio, log=self._log,
                                   progress_cb=tts_progress)
        self._log(f"TTS done. {sum(1 for l in lines if l.get('audio_path'))} files.")

        # ── Phase 2: Whisper ───────────────────────────────────────────────────
        self._log("Phase 2/3: Transcribing with Whisper...")
        self._set_progress(1 / total_phases)

        def whisper_progress(done, total):
            self._set_progress(1/total_phases + done / total / total_phases)

        lines = transcribe_all_lines(lines, max_words=max_words, log=self._log,
                                     progress_cb=whisper_progress)
        self._log("Whisper done.")

        # ── Phase 3: Video render ──────────────────────────────────────────────
        self._log("Phase 3/3: Rendering video...")
        self._set_progress(2 / total_phases)

        def render_progress(step, total):
            self._set_progress(2/total_phases + step / total / total_phases)

        success = render_video(
            lines,
            bg_folder=self.bg_folder,
            output_path=output_path,
            width=width,
            height=height,
            max_words=max_words,
            font_color=self.font_color,
            stroke_color=self.stroke_color,
            highlight_color=self.highlight_color,
            log=self._log,
            progress_cb=render_progress,
        )

        self._set_progress(1.0)

        if success:
            self._log(f"=== DONE! Saved to: {output_path} ===")
            self.after(0, lambda: messagebox.showinfo(
                "Done!", f"Video saved to:\n{output_path}"))
        else:
            self._log("=== RENDER FAILED. Check logs above. ===")
            self.after(0, lambda: messagebox.showerror(
                "Render Failed", "Video render failed. Check the log for details."))

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _log(self, msg: str):
        """Append a message to the log box (thread-safe)."""
        def _append():
            self._log_box.configure(state="normal")
            self._log_box.insert("end", msg + "\n")
            self._log_box.see("end")
            self._log_box.configure(state="disabled")
            self._status_var.set(msg[-100:])
        self.after(0, _append)

    def _set_progress(self, value: float):
        """Set progress bar 0.0–1.0 (thread-safe)."""
        self.after(0, lambda: self._progress_bar.set(max(0.0, min(1.0, value))))


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = BrainrotApp()
    app.mainloop()
