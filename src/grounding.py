"""
Visual icon grounding — finds a desktop icon by vision alone.

Two-stage cascaded approach:

Stage 1 — Multi-scale template matching (OpenCV)
  We slide a reference crop of the icon across the screenshot at six different
  zoom levels (0.5x to 2.0x).  This handles macOS's Small/Medium/Large icon
  size setting and Retina vs non-Retina displays.  Fast (~50 ms) and precise
  when the reference image is available.

Stage 2 — OCR text-label detection (Tesseract, fallback)
  Every desktop icon has a text label directly below it.  We preprocess the
  screenshot to make that text stand out (denoise → contrast boost → binarise),
  then run Tesseract in sparse-text mode to find the label.  Once we know where
  the label is, we estimate the icon center as being ~48 px ABOVE it.
  This stage works with NO reference image — only the target name is needed —
  so it generalises to any icon or button described in plain English.

Both stages include configurable retry logic with delays between attempts.

Retina / HiDPI note
-------------------
pyautogui.screenshot() captures at physical pixel resolution (2x on Retina
Macs), but pyautogui.moveTo() / doubleClick() work in logical coordinates
(half that resolution).  All coordinates returned by detect() are already
converted to logical space via get_screen_scale(), so callers can pass them
directly to pyautogui without any further adjustment.
"""

import logging
import time
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
import pytesseract
from PIL import Image

from .utils import capture_screenshot, get_screen_scale

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE = Path(__file__).parent.parent / "assets" / "notes_icon.png"


class IconGrounder:
    """
    Locate a desktop icon and return its center coordinates (x, y).

    Returned coordinates are always in logical screen space so they can be
    passed directly to pyautogui without any Retina/HiDPI adjustment.

    Usage:
        grounder = IconGrounder(target_name="Notes")
        x, y, confidence = grounder.detect_with_retry()
    """

    def __init__(
        self,
        target_name: str = "Notes",
        template_path: Optional[Path] = None,
        template_threshold: float = 0.75,
        ocr_threshold: float = 0.55,
    ):
        self.target_name        = target_name
        self.target_lower       = target_name.lower()
        self.template_threshold = template_threshold
        self.ocr_threshold      = ocr_threshold
        self.template_gray: Optional[np.ndarray] = None

        template_file = template_path or DEFAULT_TEMPLATE
        if template_file.exists():
            img = cv2.imread(str(template_file))
            if img is not None:
                self.template_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                logger.info(f"Template image loaded: {template_file.name}  {self.template_gray.shape}")
        if self.template_gray is None:
            logger.info("No template image — will use OCR only")

    # ------------------------------------------------------------------ #
    #  Public methods                                                      #
    # ------------------------------------------------------------------ #

    def detect(
        self,
        screenshot: Optional[np.ndarray] = None,
    ) -> Tuple[Optional[int], Optional[int], float]:
        """
        Try to find the icon in a single screenshot.

        Returns (x, y, confidence) on success where (x, y) are logical screen
        coordinates ready to pass to pyautogui.  Returns (None, None, 0.0) if
        the icon could not be located.
        """
        if screenshot is None:
            screenshot = capture_screenshot()

        # Convert pixel coords → logical coords for Retina/HiDPI displays.
        # On a standard 1:1 display scale == 1.0 and this is a no-op.
        scale = get_screen_scale(screenshot)

        # Stage 1: template matching — fast, uses the reference image
        if self.template_gray is not None:
            px, py, confidence = self._run_template_match(screenshot)
            if confidence >= self.template_threshold:
                x, y = int(px / scale), int(py / scale)
                logger.info(f"[template match]  found at ({x}, {y})  conf={confidence:.3f}")
                return x, y, confidence
            logger.debug(
                f"[template match]  conf={confidence:.3f} too low (need {self.template_threshold})"
            )

        # Stage 2: OCR — slower, but works without a reference image
        px, py, confidence = self._run_ocr_detection(screenshot)
        if px is not None and confidence >= self.ocr_threshold:
            x, y = int(px / scale), int(py / scale)
            logger.info(f"[OCR detection]  found at ({x}, {y})  conf={confidence:.3f}")
            return x, y, confidence

        logger.warning(f"Icon '{self.target_name}' not found by template or OCR")
        return None, None, 0.0

    def detect_with_retry(
        self,
        max_retries: int = 3,
        delay: float = 1.0,
    ) -> Tuple[Optional[int], Optional[int], float]:
        """
        Call detect() up to max_retries times, capturing a fresh screenshot
        each time and waiting `delay` seconds between failed attempts.
        """
        for attempt in range(1, max_retries + 1):
            logger.info(f"Detection attempt {attempt} of {max_retries}")
            x, y, confidence = self.detect()
            if x is not None:
                return x, y, confidence
            if attempt < max_retries:
                logger.info(f"Not found — retrying in {delay}s")
                time.sleep(delay)
        logger.error(f"Icon not found after {max_retries} attempts")
        return None, None, 0.0

    # ------------------------------------------------------------------ #
    #  Stage 1: template matching                                          #
    # ------------------------------------------------------------------ #

    def _run_template_match(
        self, screenshot: np.ndarray
    ) -> Tuple[int, int, float]:
        """
        Slide the template across the screenshot at multiple zoom levels and
        return the location with the highest normalised cross-correlation score.

        Coordinates returned are in screenshot pixel space (not yet scaled).
        """
        gray_screen = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
        tpl_h, tpl_w = self.template_gray.shape

        best_confidence = 0.0
        best_x, best_y  = 0, 0

        for scale in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
            scaled_w = int(tpl_w * scale)
            scaled_h = int(tpl_h * scale)

            if scaled_w > gray_screen.shape[1] or scaled_h > gray_screen.shape[0]:
                continue

            scaled_template = cv2.resize(
                self.template_gray, (scaled_w, scaled_h), interpolation=cv2.INTER_CUBIC
            )
            match_result = cv2.matchTemplate(gray_screen, scaled_template, cv2.TM_CCOEFF_NORMED)
            _, max_score, _, top_left = cv2.minMaxLoc(match_result)

            if max_score > best_confidence:
                best_confidence = max_score
                best_x = top_left[0] + scaled_w // 2
                best_y = top_left[1] + scaled_h // 2

        return best_x, best_y, best_confidence

    # ------------------------------------------------------------------ #
    #  Stage 2: OCR text-label detection                                  #
    # ------------------------------------------------------------------ #

    def _run_ocr_detection(
        self, screenshot: np.ndarray
    ) -> Tuple[Optional[int], Optional[int], float]:
        """
        Read the text labels on the desktop with Tesseract and find the one
        that most closely matches the target icon name.

        Coordinates returned are in screenshot pixel space (not yet scaled).
        """
        preprocessed = self._preprocess_for_ocr(screenshot)

        try:
            ocr_data = pytesseract.image_to_data(
                Image.fromarray(preprocessed),
                output_type=pytesseract.Output.DICT,
                config="--psm 11",
            )
        except Exception as e:
            logger.error(f"Tesseract failed: {e}")
            return None, None, 0.0

        best_score = 0.0
        best_x, best_y = None, None

        for i, word in enumerate(ocr_data.get("text", [])):
            word = word.strip()
            if not word:
                continue

            similarity = self._name_similarity(word)
            if similarity <= 0.0:
                continue

            ocr_confidence = max(0.0, float(ocr_data["conf"][i])) / 100.0
            score = similarity * 0.9 + ocr_confidence * 0.1

            if score > best_score:
                best_score = score
                label_x = ocr_data["left"][i]
                label_y = ocr_data["top"][i]
                label_w = ocr_data["width"][i]
                label_h = ocr_data["height"][i]
                best_x = label_x + label_w // 2
                best_y = max(0, label_y - max(label_h * 2, 48))

        return best_x, best_y, best_score

    # ------------------------------------------------------------------ #
    #  Image preprocessing                                                 #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _preprocess_for_ocr(image: np.ndarray) -> np.ndarray:
        """
        Prepare the screenshot so Tesseract can read desktop icon labels
        regardless of wallpaper colour or macOS theme (light / dark).

        Pipeline:
          1. Grayscale          — remove colour noise
          2. Bilateral filter   — smooth noise while keeping text edges sharp
          3. CLAHE              — boost local contrast so faint text pops
          4. Otsu binarisation  — give Tesseract a clean black-and-white image
        """
        gray      = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        denoised  = cv2.bilateralFilter(gray, 9, 75, 75)
        clahe     = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        contrast  = clahe.apply(denoised)
        _, binary = cv2.threshold(contrast, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return binary

    # ------------------------------------------------------------------ #
    #  Text similarity                                                     #
    # ------------------------------------------------------------------ #

    def _name_similarity(self, word: str) -> float:
        """
        Score how closely an OCR-detected word matches the target icon name.

        Returns a value in [0, 1]:
          1.0  — exact match (e.g. "Notes" == "Notes")
          0.85 — one is a prefix of the other (handles truncated labels)
          0.65 — one contains the other (e.g. "iNotes" or "Notes ")
          0.4  — 70%+ character overlap (catches OCR typos like "N0tes")
          0.0  — no meaningful match
        """
        candidate = word.lower().strip()
        target    = self.target_lower

        if candidate == target:
            return 1.0
        if candidate.startswith(target) or target.startswith(candidate):
            return 0.85
        if target in candidate or candidate in target:
            return 0.65
        overlap_ratio = sum(c in target for c in candidate) / max(len(target), 1)
        if len(candidate) > 0 and overlap_ratio >= 0.7:
            return 0.4
        return 0.0