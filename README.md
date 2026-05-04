# Vision-Based Desktop Automation — macOS

Fetches 10 blog posts from the JSONPlaceholder API and saves each one both as
a **note in the Notes app** and as a **plain-text `.txt` file** on your Desktop,
by visually locating and launching Notes through a desktop alias icon.

---

## How it works

### Grounding (the core challenge)

The script locates the Notes icon purely by vision — no hardcoded position.

**Stage 1 — Multi-scale template matching** (`src/grounding.py`)  
Uses OpenCV `matchTemplate` to search for a reference crop of the icon across
six zoom levels (0.5× – 2.0×). This handles different macOS icon-size settings
(Small / Medium / Large) and Retina displays.

**Stage 2 — OCR text-label detection** (fallback)  
If no template image is provided, or if Stage 1 confidence is too low, the
screenshot is preprocessed with a bilateral filter + CLAHE + Otsu threshold
pipeline and passed to Tesseract (`--psm 11` sparse-text mode). The word
"Notes" detected below the icon graphic reveals the icon center.  
This stage requires **no reference image** and works for any icon whose name
you know.

### Why Notes can't "Save As .txt"

Notes auto-saves every note in its iCloud/local database — it has no
"Save As plain text" export in its GUI. The script satisfies the file-output
requirement by writing the same post content directly to
`~/Desktop/tjm-project/post_{id}.txt` after pasting into Notes.

---

## Prerequisites

### System
```bash
# Homebrew
brew install tesseract

# macOS Permissions (System Settings → Privacy & Security):
#   Screen Recording  — for pyautogui.screenshot()
#   Accessibility     — for pyautogui mouse / keyboard control
```

### Desktop alias
Create a **Notes alias** on your Desktop:
- Open Finder → Applications → right-click **Notes** → Make Alias
- Drag the alias to the Desktop

### Python environment
```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync
```

### Template image (optional but recommended for faster / more reliable detection)
1. Take a screenshot of the Notes alias icon on your desktop
2. Crop it to just the icon graphic (≈ 64 × 64 px)
3. Save as `assets/notes_icon.png`

Without this file the grounder falls back to OCR only.

---

## Usage

```bash
# Test API fetch only — no UI interaction
uv run python main.py --dry-run

# Test icon detection only — saves an annotated screenshot
uv run python main.py --demo

# Full automation
uv run python main.py
```

**Emergency abort:** move the mouse to the top-left corner of the screen.

---

## Generating the 3 deliverable screenshots

The spec requires annotated screenshots with the icon detected in three
positions. Use `--demo` mode:

```bash
# 1. Drag the Notes alias to the top-left corner of your Desktop
uv run python main.py --demo
# Rename output to: screenshots/detection_topleft.png

# 2. Move alias to centre of Desktop → repeat → rename to detection_center.png
# 3. Move alias to bottom-right     → repeat → rename to detection_bottomright.png
```

---

## Output

```
~/Desktop/tjm-project/
├── post_1.txt … post_10.txt        # API posts saved as plain text
└── detection_screenshots/
    └── detection_post_N.png        # Annotated detection for each post
```

Notes app also contains the same 10 notes in your Notes library.

---

## File structure

```
.
├── main.py              # Entry point (--dry-run / --demo / full run)
├── pyproject.toml       # uv / hatchling config
├── assets/
│   └── notes_icon.png   # Optional: reference crop for template matching
├── screenshots/         # Deliverable annotated screenshots go here
└── src/
    ├── grounding.py     # IconGrounder: template matching + OCR
    ├── automation.py    # Mac automation: osascript + pyautogui + pyperclip
    ├── api_client.py    # JSONPlaceholder fetch + format
    └── utils.py         # Screenshot capture, annotation, directory helpers
```

