# Local Brainrot Generator

Generates TikTok/Shorts-style brainrot videos locally with character voices and karaoke captions.

## Requirements

- Python 3.10+
- FFmpeg in PATH (https://ffmpeg.org/download.html)
- Internet access for edge-tts (first audio generation per session)

## Install

```bash
pip install -r requirements.txt
```

For faster Whisper on NVIDIA GPU, also install:
```bash
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
```

## Run

```bash
python gui.py
```

## JSON Script Format

```json
{
  "script": [
    {
      "character": "Peter",
      "text": "Oh my god, Lois, this is amazing!",
      "avatar": "C:/path/to/peter.png"
    },
    {
      "character": "Stewie",
      "text": "Blast! You complete imbecile, Peter.",
      "avatar": "C:/path/to/stewie.png"
    }
  ]
}
```

Supported top-level keys: `script`, `scenes`, `lines`, or a root JSON array.
The `avatar` field is optional — you can also auto-assign from the Avatars folder (filenames containing the character name will be matched automatically).

## Supported Characters & Voices

| Character | Voice (edge-tts)       |
|-----------|------------------------|
| Peter     | en-US-GuyNeural        |
| Stewie    | en-GB-RyanNeural       |
| Rick      | en-US-DavisNeural      |
| Morty     | en-US-JasonNeural      |
| Lois      | en-US-JennyNeural      |
| Meg       | en-US-AriaNeural       |
| Narrator  | en-US-AndrewNeural     |

To add more characters, edit `config.py` → `CHARACTER_VOICES`.

## Background Videos

Put any `.mp4 / .mov / .mkv` files in a folder and select it in the GUI.
The app will randomly pick one and loop it to match audio duration.
Good sources: Minecraft parkour, Subway Surfers, GTA, family guy clips (without sound).

## Avatar Images

Put `.png` files (with transparency) in a folder and select it.
Name files to include the character name (e.g. `peter_icon.png`, `stewie_face.png`) for auto-assignment.

## CPU Performance

The app uses all available CPU cores for FFmpeg encoding (`os.cpu_count()`).
On an i7-2690 v4 or similar Xeon: expect ~2–4× real-time rendering speed.
GPU (NVIDIA CUDA) speeds up Whisper transcription automatically if available.

## Troubleshooting

**"No module named edge_tts"** → `pip install edge-tts`
**"No module named faster_whisper"** → `pip install faster-whisper`
**FFmpeg not found** → Download from https://ffmpeg.org and add to PATH
**Blank captions** → Check that Whisper detected words (see log box)
**Audio sounds generic** → edge-tts needs internet. For offline: pyttsx3 is used automatically.
