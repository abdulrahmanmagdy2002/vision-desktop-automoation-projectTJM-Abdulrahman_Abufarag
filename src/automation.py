"""
Mac-specific desktop automation using pyautogui and AppleScript.

Target application: Notes (macOS)

How the tools are used:
  - pyautogui  moves the mouse and double-clicks to launch Notes from its icon
  - osascript  (AppleScript via subprocess) handles everything else:
               creating the note, writing its content, quitting the app.
               AppleScript talks directly to Notes without needing window
               focus, which eliminates the keyboard-typing reliability issues.

Why AppleScript for content instead of clipboard paste:
  pyautogui hotkeys like Cmd+V require the target window to have keyboard
  focus.  macOS focus is not guaranteed after programmatic app launch, so
  the keys were landing outside Notes and typing literal 'v' / 'w' characters.
  AppleScript bypasses the UI layer entirely — it tells Notes what to do
  through its scripting interface regardless of which window is in front.
"""

import logging
import subprocess
import time
from pathlib import Path
from typing import Optional

import pyautogui

logger = logging.getLogger(__name__)

pyautogui.FAILSAFE = True   # safety valve: move mouse to top-left to abort
pyautogui.PAUSE    = 0.05

APP_NAME = "Notes"


# ------------------------------------------------------------------ #
#  Desktop                                                             #
# ------------------------------------------------------------------ #

def show_desktop() -> None:
    """
    Hide every visible app window so the desktop icons are fully exposed.
    We need this before every detection step so nothing is blocking the icon.
    """
    script = """
    tell application "System Events"
        repeat with proc in (every process where background only is false)
            try
                set visible of proc to false
            end try
        end repeat
    end tell
    """
    _run_applescript(script)
    time.sleep(1.5)


# ------------------------------------------------------------------ #
#  App lifecycle                                                       #
# ------------------------------------------------------------------ #

def launch_notes(x: int, y: int) -> bool:
    """
    Move the mouse to (x, y) and double-click to open Notes from its desktop alias.

    Falls back to `open -a Notes` if Notes doesn't appear within 8 seconds,
    so the script keeps running even if the double-click landed slightly off.
    """
    logger.info(f"Moving to Notes icon at ({x}, {y}) and double-clicking")
    try:
        pyautogui.moveTo(x, y, duration=0.4)
        time.sleep(0.2)
        pyautogui.doubleClick(interval=0.15)
        time.sleep(0.5)

        if _wait_for_notes(timeout=8):
            logger.info("Notes is open")
            return True

        logger.warning("Double-click timed out — trying 'open -a Notes' as fallback")
        subprocess.run(["open", "-a", APP_NAME], check=True)
        return _wait_for_notes(timeout=6)

    except pyautogui.FailSafeException:
        logger.warning("Failsafe triggered — mouse moved to corner, aborting launch")
        return False
    except Exception as e:
        logger.error(f"Error while launching Notes: {e}")
        return False


def write_note_and_save_file(content: str, filepath: Path) -> bool:
    """
    Save the post in two places:

    1. As a plain-text .txt file on the Desktop (written directly by Python).
    2. As a new note in the Notes app (created via AppleScript).

    Writing the file first means the AppleScript can read it back — this avoids
    all string-escaping problems with newlines and special characters in the
    note body.  Even if the Notes step fails, the .txt file is always saved.
    """
    # ── Step A: write the .txt file ───────────────────────────────────
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding="utf-8")
        logger.info(f"File written: {filepath.name}")
    except Exception as e:
        logger.error(f"Could not write {filepath.name}: {e}")
        return False

    # ── Step B: create the Notes note by reading back that file ───────
    posix_path = str(filepath.absolute())
    note_script = f"""
    set noteBody to (read POSIX file "{posix_path}" as «class utf8»)
    tell application "Notes"
        make new note with properties {{body: noteBody}}
    end tell
    """
    result = _run_applescript(note_script)
    if result is None:
        logger.warning("AppleScript note creation failed — but the .txt file was saved")
    else:
        logger.info("Note created in Notes app")

    return True     # .txt file is the primary deliverable


def quit_notes() -> bool:
    """Quit Notes completely so the desktop is clean for the next iteration."""
    _run_applescript(f'tell application "{APP_NAME}" to quit')
    time.sleep(0.6)
    is_gone = not _notes_is_running()
    if is_gone:
        logger.info("Notes closed")
    return is_gone


def force_quit() -> None:
    """Emergency cleanup — force-kill Notes if something went wrong."""
    subprocess.run(["killall", APP_NAME], capture_output=True)
    time.sleep(0.3)
    logger.info("Notes force-quit")


# ------------------------------------------------------------------ #
#  Private helpers                                                     #
# ------------------------------------------------------------------ #

def _run_applescript(script: str) -> Optional[str]:
    """Run an AppleScript string and return its stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=12,
        )
        if result.returncode != 0:
            logger.debug(f"AppleScript error: {result.stderr.strip()}")
            return None
        return result.stdout.strip()
    except Exception as e:
        logger.error(f"Could not run AppleScript: {e}")
        return None


def _notes_is_running() -> bool:
    """Return True if the Notes process is currently running."""
    response = _run_applescript(
        f'tell application "System Events" to (name of processes) contains "{APP_NAME}"'
    )
    return response == "true"


def _wait_for_notes(timeout: float = 8.0) -> bool:
    """Poll until Notes appears in the process list or the timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _notes_is_running():
            return True
        time.sleep(0.3)
    logger.warning(f"Notes did not start within {timeout:.0f} seconds")
    return False
