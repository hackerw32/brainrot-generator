"""
gui.py - Main CustomTkinter GUI for the Local Brainrot Generator
"""

import json
import os
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
from tts_engine import check_status, generate_all_lines, list_available_voices, set_engine
from whisper_alignment import transcribe_all_lines
from video_renderer import render_video, generate_preview_frame

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

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm"}

# Persistent app settings (folders, colors, etc.) — saved between sessions
SETTINGS_FILE = Path(__file__).parent / "_app_settings.json"


class BrainrotApp(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("LOCAL BRAINROT GENERATOR - Character Voices & Dynamic Captions")
        self.geometry("1400x820")
        self.minsize(1200, 720)
        self.configure(fg_color=DARK_BG)

        self.script_lines:   list[dict] = []
        self.bg_folder:      Optional[str] = None
        self.avatars_folder: Optional[str] = None
        self.music_folder:   Optional[str] = None
        self.font_color      = DEFAULT_FONT_COLOR
        self.stroke_color    = DEFAULT_STROKE_COLOR
        self.highlight_color = DEFAULT_HIGHLIGHT_COLOR

        self._bg_video_paths:  list[Path] = []
        self._music_paths:     list[Path] = []
        self.output_folder:    Optional[str] = None

        self._preview_thread:  Optional[threading.Thread] = None
        self._preview_running: bool = False
        self._preview_image:   Optional[ImageTk.PhotoImage] = None
        self._render_thread:   Optional[threading.Thread] = None

        self._build_ui()
        self._update_tts_status()
        self._load_app_settings()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI Construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=3)
        self.grid_columnconfigure(2, weight=4)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkLabel(
            self, text="LOCAL BRAINROT GENERATOR - Character Voices & Dynamic Captions",
            font=ctk.CTkFont(family="Arial", size=16, weight="bold"),
            text_color=CYAN,
        )
        header.grid(row=0, column=0, columnspan=3, sticky="ew", padx=20, pady=(10, 0))

        self._build_left_panel()
        self._build_middle_panel()
        self._build_right_panel()

        self._status_var = tk.StringVar(value="Ready.")
        ctk.CTkLabel(
            self, textvariable=self._status_var,
            font=ctk.CTkFont(size=11), text_color="gray70",
            fg_color="#0A0A1A",
        ).grid(row=2, column=0, columnspan=3, sticky="ew")

    # ── Left panel ─────────────────────────────────────────────────────────────

    def _build_left_panel(self):
        frame = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10,
                             border_width=1, border_color=PURPLE)
        frame.grid(row=1, column=0, padx=(12, 6), pady=10, sticky="nsew")
        frame.grid_rowconfigure(4, weight=1)
        frame.grid_rowconfigure(6, weight=0)
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(frame, text="SCRIPT INPUT",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=PURPLE).grid(row=0, column=0, pady=(10, 4), padx=10, sticky="w")

        # Project name + save/load
        proj_row = ctk.CTkFrame(frame, fg_color="transparent")
        proj_row.grid(row=1, column=0, padx=10, pady=(0, 4), sticky="ew")
        proj_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(proj_row, text="Project:", font=ctk.CTkFont(size=11),
                     text_color="gray70").grid(row=0, column=0, padx=(0, 4))
        self._project_name_var = tk.StringVar(value="my_project")
        ctk.CTkEntry(proj_row, textvariable=self._project_name_var,
                     font=ctk.CTkFont(size=11), height=28).grid(row=0, column=1, sticky="ew")
        ctk.CTkButton(proj_row, text="SAVE", width=55, height=28,
                      fg_color=CARD, hover_color="#1a4a8a",
                      command=self._save_project).grid(row=0, column=2, padx=(4, 0))
        ctk.CTkButton(proj_row, text="LOAD", width=55, height=28,
                      fg_color=CARD, hover_color="#1a4a8a",
                      command=self._load_project).grid(row=0, column=3, padx=(4, 0))

        # Status label (filename)
        self._json_path_var = tk.StringVar(value="Paste JSON below or load a file")
        ctk.CTkLabel(frame, textvariable=self._json_path_var,
                     text_color="gray60", font=ctk.CTkFont(size=10),
                     wraplength=300, justify="left").grid(row=2, column=0, padx=10, sticky="w")

        # Button row: LOAD FILE | PASTE | CONVERT
        load_row = ctk.CTkFrame(frame, fg_color="transparent")
        load_row.grid(row=3, column=0, padx=10, pady=(2, 4), sticky="ew")
        ctk.CTkButton(load_row, text="LOAD FILE", width=90,
                      fg_color=PURPLE, hover_color="#7D3C98",
                      command=self._load_json).grid(row=0, column=0)
        ctk.CTkButton(load_row, text="PASTE", width=75,
                      fg_color=CARD, hover_color="#1a4a8a",
                      command=self._paste_to_textbox).grid(row=0, column=1, padx=(4, 0))
        ctk.CTkButton(load_row, text="CONVERT", width=85,
                      fg_color=CYAN, hover_color="#0097A7", text_color="black",
                      command=self._convert_json).grid(row=0, column=2, padx=(4, 0))

        # Editable textbox — paste JSON here or view parsed script
        self._script_text = ctk.CTkTextbox(
            frame, fg_color=CARD, text_color="#E0E0E0",
            font=ctk.CTkFont(family="Consolas", size=11),
            wrap="word",
        )
        self._script_text.grid(row=4, column=0, padx=10, pady=(0, 4), sticky="nsew")
        self._script_text.insert("1.0",
            'Paste your JSON here and click CONVERT\n'
            'or use LOAD FILE to open a .json file.\n\n'
            'Example:\n'
            '{\n'
            '  "script": [\n'
            '    {"character": "Peter", "text": "Hey Lois!"},\n'
            '    {"character": "Stewie", "text": "Blast!"}\n'
            '  ]\n'
            '}'
        )
        # Fix Ctrl+V and right-click on the internal tk Text widget
        tb = self._script_text._textbox
        tb.bind("<Control-v>", lambda e: self._paste_to_textbox() or "break")
        tb.bind("<Control-V>", lambda e: self._paste_to_textbox() or "break")
        tb.bind("<Button-3>", self._show_right_click_menu)

        # TTS engine selector
        tts_row = ctk.CTkFrame(frame, fg_color="transparent")
        tts_row.grid(row=5, column=0, padx=10, pady=(2, 2), sticky="ew")
        tts_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(tts_row, text="TTS Engine:",
                     font=ctk.CTkFont(size=11), text_color="gray70").grid(row=0, column=0, padx=(0, 6))
        self._tts_engine_var = tk.StringVar(value="auto")
        self._tts_engine_menu = ctk.CTkOptionMenu(
            tts_row,
            values=["auto", "gtts (Greek)", "xtts-v2 (best)", "edge-tts", "pyttsx3"],
            variable=self._tts_engine_var,
            fg_color=CARD, button_color=PURPLE,
            font=ctk.CTkFont(size=11), width=160,
            command=self._on_tts_engine_change,
        )
        self._tts_engine_menu.grid(row=0, column=1, sticky="ew")

        # XTTS speaker reference (shown only when xtts-v2 selected)
        self._xtts_row = ctk.CTkFrame(frame, fg_color="transparent")
        self._xtts_row.grid(row=6, column=0, padx=10, pady=(0, 2), sticky="ew")
        self._xtts_row.grid_columnconfigure(1, weight=1)
        self._xtts_row.grid_remove()   # hidden by default
        ctk.CTkLabel(self._xtts_row, text="Voice sample:",
                     font=ctk.CTkFont(size=10), text_color="gray60").grid(row=0, column=0, padx=(0, 4))
        self._xtts_wav_var = tk.StringVar(value="(no file — uses default)")
        ctk.CTkLabel(self._xtts_row, textvariable=self._xtts_wav_var,
                     font=ctk.CTkFont(size=10), text_color="gray60",
                     wraplength=160).grid(row=0, column=1, sticky="w")
        ctk.CTkButton(self._xtts_row, text="...", width=30,
                      fg_color=CARD, hover_color="#1a4a8a",
                      command=self._pick_xtts_wav).grid(row=0, column=2, padx=(4, 0))

        self._tts_status_var = tk.StringVar(value="Checking TTS...")
        ctk.CTkLabel(frame, textvariable=self._tts_status_var,
                     text_color=CYAN, font=ctk.CTkFont(size=10),
                     wraplength=280).grid(row=7, column=0, padx=10, pady=(0, 8), sticky="w")

    # ── Middle panel ───────────────────────────────────────────────────────────

    def _build_middle_panel(self):
        outer = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10,
                             border_width=1, border_color=PURPLE)
        outer.grid(row=1, column=1, padx=6, pady=10, sticky="nsew")
        outer.grid_rowconfigure(0, weight=1)
        outer.grid_columnconfigure(0, weight=1)

        scroll = ctk.CTkScrollableFrame(outer, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)
        scroll.grid_columnconfigure(0, weight=1)

        r = 0  # row counter inside scroll

        ctk.CTkLabel(scroll, text="ASSET MANAGEMENT",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=PURPLE).grid(row=r, column=0, pady=(8, 4), padx=10, sticky="w")
        r += 1

        # BG Videos
        bg_row = ctk.CTkFrame(scroll, fg_color="transparent")
        bg_row.grid(row=r, column=0, padx=10, pady=2, sticky="ew")
        bg_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(bg_row, text="BG VIDEOS FOLDER",
                     font=ctk.CTkFont(size=11)).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(bg_row, text="BROWSE", width=75,
                      fg_color=CYAN, hover_color="#0097A7", text_color="black",
                      command=self._select_bg_folder).grid(row=0, column=1, padx=(4, 0))
        ctk.CTkButton(bg_row, text="↻", width=32,
                      fg_color=CARD, hover_color="#1a4a8a",
                      command=self._refresh_video_list).grid(row=0, column=2, padx=(4, 0))
        r += 1

        self._bg_label = ctk.CTkLabel(scroll, text="Not selected", text_color="gray60",
                                      font=ctk.CTkFont(size=10), wraplength=240, justify="left")
        self._bg_label.grid(row=r, column=0, padx=10, sticky="w")
        r += 1

        self._bg_video_var = tk.StringVar(value="-- select video --")
        self._bg_video_menu = ctk.CTkOptionMenu(
            scroll, variable=self._bg_video_var,
            values=["-- select video --"],
            fg_color=CARD, button_color=PURPLE,
            dynamic_resizing=False,
        )
        self._bg_video_menu.grid(row=r, column=0, padx=10, pady=(2, 6), sticky="ew")
        r += 1

        # Separator
        ctk.CTkFrame(scroll, height=2, fg_color=PURPLE).grid(
            row=r, column=0, padx=10, pady=6, sticky="ew")
        r += 1

        # Avatars
        av_row = ctk.CTkFrame(scroll, fg_color="transparent")
        av_row.grid(row=r, column=0, padx=10, pady=2, sticky="ew")
        av_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(av_row, text="CHARACTER AVATARS",
                     font=ctk.CTkFont(size=11)).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(av_row, text="BROWSE", width=75,
                      fg_color=CYAN, hover_color="#0097A7", text_color="black",
                      command=self._select_avatars_folder).grid(row=0, column=1, padx=(4, 0))
        r += 1

        self._avatars_label = ctk.CTkLabel(scroll, text="Not selected", text_color="gray60",
                                           font=ctk.CTkFont(size=10), wraplength=240, justify="left")
        self._avatars_label.grid(row=r, column=0, padx=10, sticky="w")
        r += 1

        self._avatar_strip_frame = ctk.CTkFrame(scroll, fg_color="transparent", height=64)
        self._avatar_strip_frame.grid(row=r, column=0, padx=10, pady=4, sticky="ew")
        r += 1

        # Separator
        ctk.CTkFrame(scroll, height=2, fg_color=PURPLE).grid(
            row=r, column=0, padx=10, pady=6, sticky="ew")
        r += 1

        # Background music
        music_row = ctk.CTkFrame(scroll, fg_color="transparent")
        music_row.grid(row=r, column=0, padx=10, pady=2, sticky="ew")
        music_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(music_row, text="BACKGROUND MUSIC",
                     font=ctk.CTkFont(size=11)).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(music_row, text="BROWSE", width=75,
                      fg_color=CYAN, hover_color="#0097A7", text_color="black",
                      command=self._select_music_folder).grid(row=0, column=1, padx=(4, 0))
        ctk.CTkButton(music_row, text="↻", width=32,
                      fg_color=CARD, hover_color="#1a4a8a",
                      command=self._refresh_music_list).grid(row=0, column=2, padx=(4, 0))
        r += 1

        self._music_label = ctk.CTkLabel(scroll, text="Not selected (optional)",
                                          text_color="gray60",
                                          font=ctk.CTkFont(size=10), wraplength=240, justify="left")
        self._music_label.grid(row=r, column=0, padx=10, sticky="w")
        r += 1

        self._music_var = tk.StringVar(value="-- no music --")
        self._music_menu = ctk.CTkOptionMenu(
            scroll, variable=self._music_var,
            values=["-- no music --"],
            fg_color=CARD, button_color=PURPLE,
            dynamic_resizing=False,
        )
        self._music_menu.grid(row=r, column=0, padx=10, pady=(2, 4), sticky="ew")
        r += 1

        vol_row = ctk.CTkFrame(scroll, fg_color="transparent")
        vol_row.grid(row=r, column=0, padx=10, pady=(0, 2), sticky="ew")
        vol_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(vol_row, text="Music Volume",
                     font=ctk.CTkFont(size=11)).grid(row=0, column=0, sticky="w")
        self._music_vol_var = tk.DoubleVar(value=0.15)
        self._music_vol_label = ctk.CTkLabel(vol_row, text="15%",
                                              font=ctk.CTkFont(size=11), width=35)
        self._music_vol_label.grid(row=0, column=1)
        r += 1

        ctk.CTkSlider(scroll, from_=0.0, to=0.5, variable=self._music_vol_var,
                      button_color=PURPLE, progress_color=PURPLE,
                      command=self._on_vol_change,
                      ).grid(row=r, column=0, padx=10, pady=(0, 6), sticky="ew")
        r += 1

        # Separator
        ctk.CTkFrame(scroll, height=2, fg_color=PURPLE).grid(
            row=r, column=0, padx=10, pady=6, sticky="ew")
        r += 1

        # Caption styling
        ctk.CTkLabel(scroll, text="CAPTION STYLING",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=PURPLE).grid(row=r, column=0, pady=(0, 4), padx=10, sticky="w")
        r += 1

        self._add_color_row(scroll, r, "Default Font",       self.font_color,      self._pick_font_color);    r += 1
        self._add_color_row(scroll, r, "Stroke",             self.stroke_color,    self._pick_stroke_color);   r += 1
        self._add_color_row(scroll, r, "Speaking Highlight", self.highlight_color, self._pick_highlight_color); r += 1

        mw_row = ctk.CTkFrame(scroll, fg_color="transparent")
        mw_row.grid(row=r, column=0, padx=10, pady=(8, 4), sticky="ew")
        mw_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(mw_row, text="Max Words per Screen",
                     font=ctk.CTkFont(size=11)).grid(row=0, column=0, sticky="w")
        self._max_words_var = tk.IntVar(value=DEFAULT_MAX_WORDS)
        ctk.CTkEntry(mw_row, width=50, justify="center",
                     textvariable=self._max_words_var).grid(row=0, column=1, padx=(6, 0))
        r += 1

        ctk.CTkSlider(scroll, from_=1, to=5, number_of_steps=4,
                      variable=self._max_words_var,
                      button_color=PURPLE, progress_color=PURPLE,
                      ).grid(row=r, column=0, padx=10, pady=(0, 8), sticky="ew")
        r += 1

        ctk.CTkLabel(scroll, text="Output Resolution",
                     font=ctk.CTkFont(size=11)).grid(row=r, column=0, padx=10, sticky="w")
        r += 1
        self._resolution_var = tk.StringVar(value=DEFAULT_RESOLUTION)
        ctk.CTkOptionMenu(scroll, values=list(RESOLUTIONS.keys()),
                          variable=self._resolution_var,
                          fg_color=CARD, button_color=PURPLE,
                          ).grid(row=r, column=0, padx=10, pady=(2, 10), sticky="ew")

    def _on_vol_change(self, val):
        self._music_vol_label.configure(text=f"{int(float(val) * 100)}%")
        # Debounce: schedule save 1s after last change
        if hasattr(self, "_vol_save_job"):
            self.after_cancel(self._vol_save_job)
        self._vol_save_job = self.after(1000, self._save_app_settings)

    def _add_color_row(self, parent, row, label, initial_color, command):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid(row=row, column=0, padx=10, pady=2, sticky="ew")
        f.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(f, text=label, font=ctk.CTkFont(size=11)).grid(row=0, column=0, sticky="w")
        btn = tk.Button(f, bg=initial_color, width=4, relief="flat",
                        cursor="hand2", command=command)
        btn.grid(row=0, column=1)
        setattr(self, f"_color_btn_{label.replace(' ', '_')}", btn)

    # ── Right panel ────────────────────────────────────────────────────────────

    def _build_right_panel(self):
        frame = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10,
                             border_width=1, border_color=CYAN)
        frame.grid(row=1, column=2, padx=(6, 12), pady=10, sticky="nsew")
        frame.grid_rowconfigure(1, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(frame, text="LIVE PREVIEW & RENDER",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=CYAN).grid(row=0, column=0, pady=(10, 4), padx=10, sticky="w")

        preview_card = ctk.CTkFrame(frame, fg_color=CARD, corner_radius=8)
        preview_card.grid(row=1, column=0, padx=10, pady=4, sticky="nsew")
        preview_card.grid_rowconfigure(0, weight=1)
        preview_card.grid_columnconfigure(0, weight=1)

        self._preview_canvas = tk.Canvas(preview_card, bg="#0A0A0A", highlightthickness=0)
        self._preview_canvas.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        ctrl_row = ctk.CTkFrame(frame, fg_color="transparent")
        ctrl_row.grid(row=2, column=0, padx=10, pady=4, sticky="ew")
        ctrl_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(ctrl_row, text="Press again to stop preview",
                     font=ctk.CTkFont(size=10), text_color="gray60").grid(row=0, column=0, sticky="w")
        self._preview_btn = ctk.CTkButton(
            ctrl_row, text="▶ PREVIEW", width=110,
            fg_color=GREEN, hover_color="#1E8449",
            command=self._toggle_preview,
        )
        self._preview_btn.grid(row=0, column=1, padx=(6, 0))

        ctk.CTkFrame(frame, height=2, fg_color=CYAN).grid(
            row=3, column=0, padx=10, pady=6, sticky="ew")

        # Output folder selector
        out_row = ctk.CTkFrame(frame, fg_color="transparent")
        out_row.grid(row=4, column=0, padx=10, pady=(0, 4), sticky="ew")
        out_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(out_row, text="Output:", font=ctk.CTkFont(size=11),
                     text_color="gray70").grid(row=0, column=0, padx=(0, 4))
        self._output_folder_var = tk.StringVar(value="Not set — will ask each time")
        ctk.CTkLabel(out_row, textvariable=self._output_folder_var,
                     font=ctk.CTkFont(size=10), text_color="gray60",
                     wraplength=220, justify="left").grid(row=0, column=1, sticky="w")
        ctk.CTkButton(out_row, text="SET", width=45, height=26,
                      fg_color=CARD, hover_color="#1a4a8a",
                      command=self._select_output_folder).grid(row=0, column=2, padx=(4, 0))

        ctk.CTkButton(
            frame, text="GENERATE FINAL VIDEO",
            font=ctk.CTkFont(size=15, weight="bold"), height=50,
            fg_color=PURPLE, hover_color="#7D3C98",
            command=self._start_render,
        ).grid(row=5, column=0, padx=10, pady=(0, 6), sticky="ew")

        ctk.CTkLabel(frame, text="RENDER PROGRESS",
                     font=ctk.CTkFont(size=11), text_color="gray60").grid(
            row=6, column=0, padx=10, sticky="w")

        self._progress_var = tk.DoubleVar(value=0)
        self._progress_bar = ctk.CTkProgressBar(frame, variable=self._progress_var,
                                                  progress_color=PURPLE, height=18)
        self._progress_bar.grid(row=7, column=0, padx=10, pady=(0, 10), sticky="ew")
        self._progress_bar.set(0)

        self._log_box = ctk.CTkTextbox(frame, height=130, fg_color=CARD,
                                        font=ctk.CTkFont(family="Consolas", size=10),
                                        text_color="gray80", state="disabled")
        self._log_box.grid(row=8, column=0, padx=10, pady=(0, 10), sticky="ew")

    # ── Script actions ─────────────────────────────────────────────────────────

    def _parse_script_data(self, data) -> Optional[list]:
        if isinstance(data, list):
            return data
        for key in SCRIPT_KEYS:
            if key in data and isinstance(data[key], list):
                return data[key]
        return None

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
            lines = self._parse_script_data(data)
            if not lines:
                messagebox.showerror("Format Error",
                    f"Expected a list under key {SCRIPT_KEYS} or a root JSON array.")
                return
            self.script_lines = lines
            self._json_path_var.set(Path(path).name)
            self._update_script_preview()
            self._log(f"Loaded {len(lines)} lines from {Path(path).name}")
            self._check_missing_avatars()
        except Exception as e:
            messagebox.showerror("Error", f"Could not load JSON:\n{e}")

    def _convert_json(self):
        """Parse raw JSON pasted in the textbox."""
        raw = self._script_text.get("1.0", "end").strip()
        if not raw:
            messagebox.showwarning("Empty", "Text area is empty.")
            return
        try:
            data = json.loads(raw)
            lines = self._parse_script_data(data)
            if not lines:
                messagebox.showerror("Format Error",
                    f"Expected a list under key {SCRIPT_KEYS} or a root JSON array.")
                return
            self.script_lines = lines
            self._json_path_var.set(f"Converted ({len(lines)} lines from paste)")
            self._update_script_preview()
            self._log(f"Converted {len(lines)} lines from pasted JSON")
            self._check_missing_avatars()
        except json.JSONDecodeError as e:
            messagebox.showerror("JSON Error", f"Invalid JSON:\n{e}")

    def _update_script_preview(self):
        self._script_text.delete("1.0", "end")
        for line in self.script_lines:
            char = line.get("character", "?")
            text = line.get("text", "")
            self._script_text.insert("end", f"{char}: {text}\n\n")

    # ── Asset actions ──────────────────────────────────────────────────────────

    def _select_bg_folder(self):
        folder = filedialog.askdirectory(title="Select Background Videos Folder")
        if folder:
            self.bg_folder = folder
            self._refresh_video_list()
            self._save_app_settings()

    def _refresh_video_list(self):
        if not self.bg_folder:
            return
        seen = set()
        videos = []
        for p in Path(self.bg_folder).iterdir():
            if p.suffix.lower() in VIDEO_EXTS and p.name.lower() not in seen:
                seen.add(p.name.lower())
                videos.append(p)
        self._bg_video_paths = sorted(videos, key=lambda p: p.name.lower())
        names = [p.name for p in self._bg_video_paths] or ["-- no videos found --"]
        self._bg_video_menu.configure(values=names)
        self._bg_video_var.set(names[0])
        self._bg_label.configure(
            text=f"{Path(self.bg_folder).name}/ ({len(self._bg_video_paths)} videos)",
            text_color="gray80",
        )
        self._log(f"BG folder: {Path(self.bg_folder).name} ({len(self._bg_video_paths)} videos)")

    def _select_avatars_folder(self):
        folder = filedialog.askdirectory(title="Select Avatars Folder")
        if not folder:
            return
        self.avatars_folder = folder
        pngs = self._list_pngs(folder)
        self._avatars_label.configure(
            text=f"{Path(folder).name}/ ({len(pngs)} avatars)",
            text_color="gray80",
        )
        self._show_avatar_thumbnails(pngs)
        self._log(f"Avatars folder: {Path(folder).name} ({len(pngs)} PNGs)")
        self._auto_assign_avatars(pngs)
        self._check_missing_avatars()
        self._save_app_settings()

    def _list_pngs(self, folder: str) -> list[Path]:
        """Return deduplicated PNG list (fixes Windows double-listing bug)."""
        seen = set()
        pngs = []
        for p in Path(folder).iterdir():
            if p.suffix.lower() == ".png" and p.name.lower() not in seen:
                seen.add(p.name.lower())
                pngs.append(p)
        return sorted(pngs, key=lambda p: p.name.lower())

    def _show_avatar_thumbnails(self, pngs: list[Path]):
        for widget in self._avatar_strip_frame.winfo_children():
            widget.destroy()
        self._thumb_refs = []
        for png in pngs[:8]:
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
        for line in self.script_lines:
            if line.get("avatar"):
                continue
            char = line.get("character", "").lower()
            for png in pngs:
                if char in png.stem.lower() or png.stem.lower() in char:
                    line["avatar"] = str(png)
                    break

    def _check_missing_avatars(self):
        if not self.script_lines or not self.avatars_folder:
            return
        pngs = self._list_pngs(self.avatars_folder)
        png_stems = {p.stem.lower() for p in pngs}
        missing = set()
        for line in self.script_lines:
            char = line.get("character", "")
            if not line.get("avatar"):
                cl = char.lower()
                if not any(cl in stem or stem in cl for stem in png_stems):
                    missing.add(char)
        for char in sorted(missing):
            self._log(f"[AVATAR] No avatar for '{char}' — add {char}.png to avatars folder")

    def _select_music_folder(self):
        folder = filedialog.askdirectory(title="Select Background Music Folder")
        if folder:
            self.music_folder = folder
            self._refresh_music_list()
            self._save_app_settings()

    def _refresh_music_list(self):
        if not self.music_folder:
            return
        seen = set()
        music = []
        for p in Path(self.music_folder).iterdir():
            if p.suffix.lower() in AUDIO_EXTS and p.name.lower() not in seen:
                seen.add(p.name.lower())
                music.append(p)
        self._music_paths = sorted(music, key=lambda p: p.name.lower())
        names = ["-- no music --"] + [p.name for p in self._music_paths]
        self._music_menu.configure(values=names)
        self._music_var.set(names[1] if len(names) > 1 else names[0])
        self._music_label.configure(
            text=f"{Path(self.music_folder).name}/ ({len(self._music_paths)} files)",
            text_color="gray80",
        )
        self._log(f"Music folder: {Path(self.music_folder).name} ({len(self._music_paths)} files)")

    # ── Project save / load ────────────────────────────────────────────────────

    def _save_project(self):
        name = self._project_name_var.get().strip() or "my_project"
        path = filedialog.asksaveasfilename(
            title="Save Project",
            defaultextension=".json",
            filetypes=[("Project files", "*.json")],
            initialfile=f"{name}.json",
        )
        if not path:
            return
        state = {
            "project_name": name,
            "script_lines": self.script_lines,
            "bg_folder": self.bg_folder,
            "bg_video": self._bg_video_var.get(),
            "avatars_folder": self.avatars_folder,
            "music_folder": self.music_folder,
            "music_file": self._music_var.get(),
            "music_volume": self._music_vol_var.get(),
            "font_color": self.font_color,
            "stroke_color": self.stroke_color,
            "highlight_color": self.highlight_color,
            "max_words": self._max_words_var.get(),
            "resolution": self._resolution_var.get(),
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            self._log(f"Project saved: {Path(path).name}")
        except Exception as e:
            messagebox.showerror("Save Error", str(e))

    def _load_project(self):
        path = filedialog.askopenfilename(
            title="Load Project",
            filetypes=[("Project files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                state = json.load(f)

            self._project_name_var.set(state.get("project_name", "my_project"))
            self.script_lines = state.get("script_lines", [])
            self.font_color    = state.get("font_color",    DEFAULT_FONT_COLOR)
            self.stroke_color  = state.get("stroke_color",  DEFAULT_STROKE_COLOR)
            self.highlight_color = state.get("highlight_color", DEFAULT_HIGHLIGHT_COLOR)
            self._max_words_var.set(state.get("max_words", DEFAULT_MAX_WORDS))
            self._resolution_var.set(state.get("resolution", DEFAULT_RESOLUTION))

            for label, attr in [("Default_Font", "font_color"),
                                 ("Stroke", "stroke_color"),
                                 ("Speaking_Highlight", "highlight_color")]:
                btn = getattr(self, f"_color_btn_{label}", None)
                if btn:
                    btn.configure(bg=getattr(self, attr))

            bg_folder = state.get("bg_folder")
            if bg_folder and Path(bg_folder).exists():
                self.bg_folder = bg_folder
                self._refresh_video_list()
                saved_video = state.get("bg_video", "")
                if saved_video in [p.name for p in self._bg_video_paths]:
                    self._bg_video_var.set(saved_video)

            av_folder = state.get("avatars_folder")
            if av_folder and Path(av_folder).exists():
                self.avatars_folder = av_folder
                pngs = self._list_pngs(av_folder)
                self._avatars_label.configure(
                    text=f"{Path(av_folder).name}/ ({len(pngs)} avatars)",
                    text_color="gray80",
                )
                self._show_avatar_thumbnails(pngs)

            music_folder = state.get("music_folder")
            if music_folder and Path(music_folder).exists():
                self.music_folder = music_folder
                self._refresh_music_list()
                saved_music = state.get("music_file", "")
                if saved_music in [p.name for p in self._music_paths]:
                    self._music_var.set(saved_music)
                vol = state.get("music_volume", 0.15)
                self._music_vol_var.set(vol)
                self._music_vol_label.configure(text=f"{int(vol * 100)}%")

            if self.script_lines:
                self._update_script_preview()

            self._log(f"Project loaded: {Path(path).name}")
        except Exception as e:
            messagebox.showerror("Load Error", str(e))

    # ── Color pickers ──────────────────────────────────────────────────────────

    def _pick_color(self, attr: str, btn_attr: str):
        from tkinter import colorchooser
        color = colorchooser.askcolor(color=getattr(self, attr), title="Pick color")[1]
        if color:
            setattr(self, attr, color)
            btn = getattr(self, btn_attr, None)
            if btn:
                btn.configure(bg=color)
            self._save_app_settings()

    def _pick_font_color(self):      self._pick_color("font_color",      "_color_btn_Default_Font")
    def _pick_stroke_color(self):    self._pick_color("stroke_color",    "_color_btn_Stroke")
    def _pick_highlight_color(self): self._pick_color("highlight_color", "_color_btn_Speaking_Highlight")

    # ── TTS status ─────────────────────────────────────────────────────────────

    def _on_tts_engine_change(self, value: str):
        """Called when user picks a TTS engine from the dropdown."""
        engine_map = {
            "auto":            "auto",
            "gtts (Greek)":    "gtts",
            "xtts-v2 (best)":  "xtts",
            "edge-tts":        "edge-tts",
            "pyttsx3":         "pyttsx3",
        }
        key = engine_map.get(value, "auto")
        wav = self._xtts_wav_var.get()
        wav = wav if wav != "(no file — uses default)" else None
        set_engine(key, xtts_speaker_wav=wav)

        # Show/hide XTTS speaker row
        if key == "xtts":
            self._xtts_row.grid()
        else:
            self._xtts_row.grid_remove()

        self._update_tts_status()
        self._save_app_settings()

    def _pick_xtts_wav(self):
        path = filedialog.askopenfilename(
            title="Select voice reference audio (5-30 sec)",
            filetypes=[("Audio files", "*.wav *.mp3 *.m4a *.flac"), ("All files", "*.*")],
        )
        if path:
            self._xtts_wav_var.set(path)
            wav = path if path != "(no file — uses default)" else None
            set_engine("xtts", xtts_speaker_wav=wav)
            self._save_app_settings()

    def _update_tts_status(self):
        status = check_status()
        parts = []
        if status["xtts"]:
            parts.append("XTTS-v2")
        if status["gtts"]:
            parts.append("gTTS")
        if status["edge_tts"]:
            parts.append("edge-tts")
        if status["pyttsx3"]:
            parts.append("pyttsx3")

        if not parts:
            msg = "TTS: NO engine! pip install edge-tts"
            self._tts_status_var.set(msg)
            return

        active = self._tts_engine_var.get() if hasattr(self, "_tts_engine_var") else "auto"
        msg = f"TTS: {' | '.join(parts)}  [active: {active}]"
        self._tts_status_var.set(msg)

    # ── Preview toggle ─────────────────────────────────────────────────────────

    def _toggle_preview(self):
        if self._preview_running:
            self._preview_running = False
            self._preview_btn.configure(text="▶ PREVIEW", fg_color=GREEN, hover_color="#1E8449")
            return

        if not self.script_lines:
            messagebox.showwarning("No Script", "Please load a JSON script first.")
            return

        self._preview_running = True
        self._preview_btn.configure(text="■ STOP", fg_color=RED, hover_color="#C0392B")
        self._preview_thread = threading.Thread(target=self._preview_loop, daemon=True)
        self._preview_thread.start()

    def _preview_loop(self):
        max_words = self._max_words_var.get()
        canvas_w  = self._preview_canvas.winfo_width()  or 300
        canvas_h  = self._preview_canvas.winfo_height() or 480
        font_size = max(36, canvas_w // 8)

        for line in self.script_lines:
            if not self._preview_running:
                break
            words = line.get("text", "").split()
            if not words:
                continue
            for i in range(0, len(words), max_words):
                if not self._preview_running:
                    break
                chunk = words[i: i + max_words]
                for active in range(len(chunk)):
                    if not self._preview_running:
                        break
                    frame = generate_preview_frame(
                        " ".join(chunk), active,
                        canvas_w, canvas_h, font_size,
                        self.font_color, self.stroke_color, self.highlight_color,
                    )
                    tk_img = ImageTk.PhotoImage(frame)

                    def _upd(img=tk_img, cw=canvas_w, ch=canvas_h):
                        self._preview_canvas.delete("all")
                        self._preview_canvas.create_image(cw // 2, ch // 2,
                                                           image=img, anchor="center")
                        self._preview_image = img

                    self.after(0, _upd)
                    time.sleep(0.4)

        self._preview_running = False
        self.after(0, lambda: self._preview_btn.configure(
            text="▶ PREVIEW", fg_color=GREEN, hover_color="#1E8449"))

    # ── Render pipeline ────────────────────────────────────────────────────────

    def _get_selected_bg_video(self) -> Optional[str]:
        sel = self._bg_video_var.get()
        for p in self._bg_video_paths:
            if p.name == sel:
                return str(p)
        return None

    def _select_output_folder(self):
        folder = filedialog.askdirectory(title="Select Output Folder for Videos")
        if folder:
            self.output_folder = folder
            self._output_folder_var.set(Path(folder).name + "/")
            self._save_app_settings()
            self._log(f"Output folder: {folder}")

    def _get_selected_music(self) -> Optional[str]:
        sel = self._music_var.get()
        if sel.startswith("--"):
            return None
        for p in self._music_paths:
            if p.name == sel:
                return str(p)
        return None

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

        project_name = self._project_name_var.get().strip() or "brainrot_output"

        if self.output_folder and Path(self.output_folder).exists():
            # Use saved output folder + project name (no dialog)
            base = Path(self.output_folder) / f"{project_name}.mp4"
            # Auto-increment if file exists
            out = base
            counter = 1
            while out.exists():
                out = Path(self.output_folder) / f"{project_name}_{counter}.mp4"
                counter += 1
            output_path = str(out)
        else:
            # Fall back to save dialog if no output folder set
            output_path = filedialog.asksaveasfilename(
                title="Save Video As",
                defaultextension=".mp4",
                filetypes=[("MP4 video", "*.mp4")],
                initialfile=f"{project_name}.mp4",
            )
            if not output_path:
                return

        width, height = RESOLUTIONS[self._resolution_var.get()]
        bg_video   = self._get_selected_bg_video()
        music_path = self._get_selected_music()
        music_vol  = self._music_vol_var.get()

        self._progress_bar.set(0)
        self._log("=== Starting render pipeline ===")
        if music_path:
            self._log(f"Music: {Path(music_path).name} @ {int(music_vol * 100)}%")

        self._render_thread = threading.Thread(
            target=self._render_pipeline,
            args=(output_path, width, height, bg_video, music_path, music_vol),
            daemon=True,
        )
        self._render_thread.start()

    def _render_pipeline(self, output_path, width, height, bg_video, music_path, music_vol):
        from config import TEMP_DIR
        max_words = self._max_words_var.get()
        lines = [dict(l) for l in self.script_lines]

        self._log("Phase 1/3: Generating TTS audio...")
        self._set_progress(0.0)
        lines = generate_all_lines(
            lines, TEMP_DIR / "tts_audio", log=self._log,
            progress_cb=lambda d, t: self._set_progress(d / t / 3),
        )
        self._log(f"TTS done. {sum(1 for l in lines if l.get('audio_path'))} files.")

        self._log("Phase 2/3: Transcribing with Whisper...")
        self._set_progress(1 / 3)
        lines = transcribe_all_lines(
            lines, max_words=max_words, log=self._log,
            progress_cb=lambda d, t: self._set_progress(1/3 + d / t / 3),
        )
        self._log("Whisper done.")

        self._log("Phase 3/3: Rendering video...")
        self._set_progress(2 / 3)
        success = render_video(
            lines,
            bg_folder=self.bg_folder,
            bg_video_path=bg_video,
            music_path=music_path,
            music_volume=music_vol,
            output_path=output_path,
            width=width,
            height=height,
            max_words=max_words,
            font_color=self.font_color,
            stroke_color=self.stroke_color,
            highlight_color=self.highlight_color,
            log=self._log,
            progress_cb=lambda s, t: self._set_progress(2/3 + s / t / 3),
        )
        self._set_progress(1.0)

        if success:
            self._log(f"=== DONE! Saved to: {output_path} ===")
            self.after(0, lambda: messagebox.showinfo("Done!", f"Video saved:\n{output_path}"))
        else:
            self._log("=== RENDER FAILED. Check logs. ===")
            self.after(0, lambda: messagebox.showerror(
                "Render Failed", "Check the log for details."))

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _log(self, msg: str):
        def _append():
            self._log_box.configure(state="normal")
            self._log_box.insert("end", msg + "\n")
            self._log_box.see("end")
            self._log_box.configure(state="disabled")
            self._status_var.set(msg[-100:])
        self.after(0, _append)

    def _set_progress(self, value: float):
        self.after(0, lambda: self._progress_bar.set(max(0.0, min(1.0, value))))

    # ── Paste helpers ──────────────────────────────────────────────────────────

    def _paste_to_textbox(self, event=None):
        """Paste clipboard text into the script textbox."""
        try:
            text = self.clipboard_get()
            try:
                self._script_text.insert("insert", text)
            except Exception:
                self._script_text.insert("end", text)
        except Exception:
            pass
        return "break"

    def _show_right_click_menu(self, event):
        """Context menu with Cut/Copy/Paste/Select All on the textbox."""
        menu = tk.Menu(self, tearoff=0, bg=CARD, fg="white",
                       activebackground=PURPLE, activeforeground="white",
                       relief="flat", bd=0)
        tb = self._script_text._textbox
        menu.add_command(label="Paste",      command=self._paste_to_textbox)
        menu.add_command(label="Cut",        command=lambda: tb.event_generate("<<Cut>>"))
        menu.add_command(label="Copy",       command=lambda: tb.event_generate("<<Copy>>"))
        menu.add_separator()
        menu.add_command(label="Select All", command=lambda: tb.tag_add("sel", "1.0", "end"))
        menu.tk_popup(event.x_root, event.y_root)

    # ── App settings (persistent between sessions) ─────────────────────────────

    def _save_app_settings(self):
        """Silently save folder paths and styling to disk."""
        try:
            settings = {
                "bg_folder":      self.bg_folder,
                "bg_video":       self._bg_video_var.get(),
                "avatars_folder": self.avatars_folder,
                "music_folder":   self.music_folder,
                "music_file":     self._music_var.get(),
                "music_volume":   self._music_vol_var.get(),
                "font_color":     self.font_color,
                "stroke_color":   self.stroke_color,
                "highlight_color":self.highlight_color,
                "max_words":      self._max_words_var.get(),
                "resolution":     self._resolution_var.get(),
                "tts_engine":     self._tts_engine_var.get() if hasattr(self, "_tts_engine_var") else "auto",
                "xtts_wav":       self._xtts_wav_var.get() if hasattr(self, "_xtts_wav_var") else "",
                "output_folder":  self.output_folder,
            }
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2)
        except Exception:
            pass  # Never block the UI for a settings write failure

    def _load_app_settings(self):
        """Restore folder paths and styling from the last session."""
        if not SETTINGS_FILE.exists():
            return
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                s = json.load(f)
        except Exception:
            return

        # Restore colors
        self.font_color      = s.get("font_color",      DEFAULT_FONT_COLOR)
        self.stroke_color    = s.get("stroke_color",    DEFAULT_STROKE_COLOR)
        self.highlight_color = s.get("highlight_color", DEFAULT_HIGHLIGHT_COLOR)
        for label, attr in [("Default_Font", "font_color"),
                             ("Stroke", "stroke_color"),
                             ("Speaking_Highlight", "highlight_color")]:
            btn = getattr(self, f"_color_btn_{label}", None)
            if btn:
                btn.configure(bg=getattr(self, attr))

        # Restore sliders / dropdowns
        self._max_words_var.set(s.get("max_words", DEFAULT_MAX_WORDS))
        res = s.get("resolution", DEFAULT_RESOLUTION)
        if res in RESOLUTIONS:
            self._resolution_var.set(res)

        vol = s.get("music_volume", 0.15)
        self._music_vol_var.set(vol)
        self._music_vol_label.configure(text=f"{int(vol * 100)}%")

        # Restore output folder
        out_folder = s.get("output_folder")
        if out_folder and Path(out_folder).exists() and hasattr(self, "_output_folder_var"):
            self.output_folder = out_folder
            self._output_folder_var.set(Path(out_folder).name + "/")

        # Restore TTS engine
        tts_engine = s.get("tts_engine", "auto")
        if hasattr(self, "_tts_engine_var"):
            self._tts_engine_var.set(tts_engine)
            xtts_wav = s.get("xtts_wav", "")
            if xtts_wav and Path(xtts_wav).exists() and hasattr(self, "_xtts_wav_var"):
                self._xtts_wav_var.set(xtts_wav)
            self._on_tts_engine_change(tts_engine)

        # Restore BG videos folder
        bg_folder = s.get("bg_folder")
        if bg_folder and Path(bg_folder).exists():
            self.bg_folder = bg_folder
            self._refresh_video_list()
            saved_video = s.get("bg_video", "")
            if saved_video in [p.name for p in self._bg_video_paths]:
                self._bg_video_var.set(saved_video)

        # Restore avatars folder
        av_folder = s.get("avatars_folder")
        if av_folder and Path(av_folder).exists():
            self.avatars_folder = av_folder
            pngs = self._list_pngs(av_folder)
            self._avatars_label.configure(
                text=f"{Path(av_folder).name}/ ({len(pngs)} avatars)",
                text_color="gray80",
            )
            self._show_avatar_thumbnails(pngs)

        # Restore music folder
        music_folder = s.get("music_folder")
        if music_folder and Path(music_folder).exists():
            self.music_folder = music_folder
            self._refresh_music_list()
            saved_music = s.get("music_file", "")
            if saved_music in [p.name for p in self._music_paths]:
                self._music_var.set(saved_music)

        self._log("Settings restored from last session.")

    def _on_close(self):
        """Save settings then exit."""
        self._save_app_settings()
        self.destroy()


if __name__ == "__main__":
    app = BrainrotApp()
    app.mainloop()
