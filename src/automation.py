"""
Mac-specific desktop automation using pyautogui, pyperclip, and AppleScript.

Target application: Notes (macOS)

How the three tools are used together:
  - pyautogui  moves the mouse and clicks (launches Notes, creates new note)
  - pyperclip  puts the post text on the clipboard so we can paste it in one
               shot — faster and Unicode-safe compared to typing char by char
  - osascript  (AppleScript via subprocess) handles app lifecycle (quit,
               activate, check if running) because macOS doesn't expose a
               simple Python API for window management
"""

import logging
import subprocess
import time
from pathlib import Path
from typing import Optional

import pyautogui
import pyperclip

logger = logging.getLogger(__name__)

pyautogui.FAILSAFE = True   # safety valve: move mouse to top-left to abort
pyautogui.PAUSE    = 0.05   # small gap between every pyautogui call

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
    time.sleep(0.6)     # give macOS a moment to finish hiding the windows


# ------------------------------------------------------------------ #
#  App lifecycle                                                       #
# ------------------------------------------------------------------ #

def launch_notes(x: int, y: int) -> bool:
    """
    Move the mouse to (x, y) and double-click to open Notes from its desktop alias.

    If Notes doesn't appear within 8 seconds we fall back to `open -a Notes`
    so the script keeps running even if the double-click was slightly off.
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


def create_new_note() -> bool:
    """Press Cmd+N inside Notes to open a fresh, empty note."""
    _bring_to_front()
    time.sleep(0.3)
    pyautogui.hotkey("command", "n")
    time.sleep(0.5)
    logger.info("New note ready")
    return True


def paste_content(text: str) -> bool:
    """
    Copy `text` to the clipboard and paste it into the active Notes window.

    We use the clipboard (copy → Cmd+V) instead of typing character by character
    because it handles all Unicode correctly and is much faster.
    """
    try:
        _bring_to_front()
        time.sleep(0.2)

        # Select everything and clear it before pasting
        pyautogui.hotkey("command", "a")
        time.sleep(0.1)
        pyautogui.press("delete")
        time.sleep(0.1)

        pyperclip.copy(text)
        pyautogui.hotkey("command", "v")
        time.sleep(0.3)

        logger.info(f"Pasted {len(text)} characters into the note")
        return True

    except pyautogui.FailSafeException:
        logger.warning("Failsafe triggered during paste — aborting")
        return False
    except Exception as e:
        logger.error(f"Error while pasting content: {e}")
        return False


def save_txt_file(content: str, filepath: Path) -> bool:
    """
    Write the post content to a plain-text .txt file on disk.

    Notes saves its notes in its own iCloud/local database and doesn't offer
    a 'Save As .txt' option, so we write the file ourselves.
    """
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(content, encoding="utf-8")
        if filepath.exists():
            logger.info(f"File written: {filepath.name}")
            return True
        logger.error(f"File missing after write: {filepath}")
        return False
    except Exception as e:
        logger.error(f"Error writing file {filepath.name}: {e}")
        return False


def close_note() -> None:
    """
    Close the current note with Cmd+W.
    Notes auto-saves so there's no save dialog to handle.
    """
    _bring_to_front()
    time.sleep(0.1)
    pyautogui.hotkey("command", "w")
    time.sleep(0.3)
    logger.info("Note closed")


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


def _bring_to_front() -> None:
    """Bring the Notes window to the front so keyboard events go to it."""
    _run_applescript(f'tell application "{APP_NAME}" to activate')
