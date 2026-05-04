import logging
from pathlib import Path

import cv2
import numpy as np
import pyautogui

logger = logging.getLogger(__name__)


def capture_screenshot() -> np.ndarray:
    """Take a screenshot and return it as a BGR numpy array (OpenCV format)."""
    screenshot = pyautogui.screenshot()
    rgb_array  = np.array(screenshot)
    return cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)


def get_desktop_path() -> Path:
    return Path.home() / "Desktop"


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def annotate_screenshot(
    image: np.ndarray,
    x: int,
    y: int,
    label: str = "Detected",
    confidence: float = 0.0,
    box_size: int = 72,
) -> np.ndarray:
    """
    Draw a bounding box, crosshair, and confidence label onto a screenshot.
    Returns a new image — the original is not modified.
    """
    canvas = image.copy()

    # Bounding box corners, clamped to image bounds
    x1 = max(0, x - box_size // 2)
    y1 = max(0, y - box_size // 2)
    x2 = min(image.shape[1], x + box_size // 2)
    y2 = min(image.shape[0], y + box_size // 2)

    cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 255, 0), 2)       # green box
    cv2.circle(canvas, (x, y), 5, (0, 0, 255), -1)                   # red dot at center
    cv2.line(canvas, (x - 20, y), (x + 20, y), (0, 0, 255), 1)       # horizontal crosshair
    cv2.line(canvas, (x, y - 20), (x, y + 20), (0, 0, 255), 1)       # vertical crosshair

    # Label text with a dark background so it's readable on any wallpaper
    caption    = f"{label}  conf={confidence:.2f}"
    font       = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.6
    font_thick = 2
    (text_w, text_h), _ = cv2.getTextSize(caption, font, font_scale, font_thick)
    text_y = y1 - 10 if y1 > text_h + 14 else y2 + text_h + 10
    cv2.rectangle(canvas, (x1, text_y - text_h - 4), (x1 + text_w + 6, text_y + 4), (0, 0, 0), -1)
    cv2.putText(canvas, caption, (x1 + 3, text_y), font, font_scale, (0, 255, 0), font_thick)

    return canvas
