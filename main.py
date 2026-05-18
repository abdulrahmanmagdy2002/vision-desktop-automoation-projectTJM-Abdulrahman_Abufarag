"""
Vision-Based Desktop Automation — macOS / Notes

Workflow (per post):
  1. Hide all windows so the desktop is fully visible
  2. Capture a screenshot and locate the Notes alias icon via visual grounding
  3. Save an annotated screenshot marking where the icon was found
  4. Double-click the icon to launch Notes
  5. Open a new note and paste the post content via the clipboard
  6. Write the same content to a plain-text .txt file on the Desktop
  7. Close the note and quit Notes
  8. Repeat for the next post
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import cv2

from src.api_client import fetch_posts, format_post, validate_post
from src.automation import (
    force_quit,
    launch_notes,
    quit_notes,
    show_desktop,
    write_note_and_save_file,
)
from src.grounding import IconGrounder
from src.utils import (
    annotate_screenshot,
    capture_screenshot,
    ensure_directory,
    get_desktop_path,
    get_screen_scale,
)

# ---------------------------------------------------------------------------
# Logging — goes to both the terminal and automation.log
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("automation.log"),
    ],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OUTPUT_FOLDER = "tjm-project"   # created on the Desktop
POST_LIMIT    = 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def save_detection_image(screenshot, x: int, y: int, confidence: float, path: Path) -> None:
    """Overlay a bounding box + label on the screenshot and write it to disk."""
    # (x, y) are in logical coords but the screenshot is in physical pixels.
    # On Retina that's a 2x difference — scale up so the box lands on the icon.
    scale = get_screen_scale(screenshot)
    px, py = int(x * scale), int(y * scale)
    annotated = annotate_screenshot(screenshot, px, py, label="Notes", confidence=confidence)
    cv2.imwrite(str(path), annotated)
    logger.info(f"Detection screenshot saved → {path.name}")


# ---------------------------------------------------------------------------
# --dry-run  — fetch posts and print a preview, no UI touched
# ---------------------------------------------------------------------------

def preview_posts(posts: list) -> None:
    logger.info("DRY-RUN — showing fetched posts, no automation will run")
    for i, post in enumerate(posts, 1):
        text = format_post(post)
        preview = text[:200] + ("…" if len(text) > 200 else "")
        print(f"\n--- Post {i}  (id={post['id']}) ---\n{preview}")
    print(f"\nTotal: {len(posts)} posts ready")


# ---------------------------------------------------------------------------
# --demo  — detect the icon once, save an annotated screenshot, then exit
# ---------------------------------------------------------------------------

def run_icon_demo(grounder: IconGrounder, screenshots_dir: Path) -> None:
    logger.info("DEMO — running icon detection only")
    show_desktop()
    screenshot = capture_screenshot()
    x, y, confidence = grounder.detect_with_retry(max_retries=3, delay=1.0)
    if x is None:
        logger.error("Could not find the Notes icon — make sure a Notes alias is on the Desktop")
        sys.exit(1)
    out_path = screenshots_dir / "demo_detection.png"
    save_detection_image(screenshot, x, y, confidence, out_path)
    print(f"\nNotes icon found at ({x}, {y})  confidence={confidence:.3f}")
    print(f"Annotated screenshot saved to: {out_path}\n")


# ---------------------------------------------------------------------------
# Full automation
# ---------------------------------------------------------------------------

def run_automation(
    posts: list,
    grounder: IconGrounder,
    output_dir: Path,
    screenshots_dir: Path,
) -> None:
    saved  = 0
    failed = 0

    for i, post in enumerate(posts, 1):
        logger.info("")
        logger.info("=" * 55)
        logger.info(f"Processing post {i} of {len(posts)}  (id={post['id']})")
        logger.info("=" * 55)

        try:
            # ── Step 1: show the desktop so the icon is visible ────────
            show_desktop()

            # ── Step 2: locate the Notes icon ──────────────────────────
            x, y, confidence = grounder.detect_with_retry(max_retries=3, delay=1.0)
            if x is None:
                logger.error("Notes icon not found — skipping this post")
                failed += 1
                continue

            # ── Step 3: save an annotated screenshot for the deliverable
            screenshot = capture_screenshot()
            save_detection_image(
                screenshot, x, y, confidence,
                screenshots_dir / f"detection_post_{post['id']}.png",
            )

            # ── Step 4: launch Notes by double-clicking the icon ───────
            if not launch_notes(x, y):
                logger.error("Notes did not open — skipping this post")
                failed += 1
                quit_notes()
                continue

            # ── Step 5 & 6: write note + save .txt file via AppleScript
            content  = format_post(post)
            txt_path = output_dir / f"post_{post['id']}.txt"
            if not write_note_and_save_file(content, txt_path):
                logger.error(f"Could not save post {post['id']} — skipping")
                failed += 1
                quit_notes()
                continue

            # ── Step 7: quit Notes ─────────────────────────────────────
            quit_notes()
            saved += 1
            logger.info(f"Done — post_{post['id']}.txt saved successfully")
            time.sleep(0.4)

        except KeyboardInterrupt:
            logger.info("Stopped by user (Ctrl+C)")
            force_quit()
            break
        except Exception as e:
            logger.error(f"Unexpected error on post {post['id']}: {e}", exc_info=True)
            force_quit()
            failed += 1

    # ── Summary ────────────────────────────────────────────────────────
    logger.info("")
    logger.info("=" * 55)
    logger.info(f"Finished — {saved} saved,  {failed} failed")
    logger.info(f"Files   → {output_dir}")
    logger.info(f"Screenshots → {screenshots_dir}")
    logger.info("=" * 55)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Vision-Based Desktop Automation — macOS"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch posts and print a preview without touching the UI",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Detect the Notes icon, save an annotated screenshot, then exit",
    )
    args = parser.parse_args()

    logger.info("=" * 55)
    logger.info("Vision-Based Desktop Automation — macOS")
    logger.info("=" * 55)

    # Set up output directories
    desktop      = get_desktop_path()
    output_dir   = desktop / OUTPUT_FOLDER
    screenshots_dir = output_dir / "detection_screenshots"
    ensure_directory(output_dir)
    ensure_directory(screenshots_dir)

    # Fetch posts — always needed (dry-run just prints them)
    posts = [p for p in fetch_posts(limit=POST_LIMIT) if validate_post(p)]
    if not posts:
        logger.error("No posts available — cannot continue")
        sys.exit(1)
    logger.info(f"Loaded {len(posts)} posts")

    if args.dry_run:
        preview_posts(posts)
        return

    grounder = IconGrounder(target_name="Notes")

    if args.demo:
        run_icon_demo(grounder, screenshots_dir)
        return

    run_automation(posts, grounder, output_dir, screenshots_dir)


if __name__ == "__main__":
    main()
