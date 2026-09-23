"""Vision agent: screen capture, UI boundary parsing, precise mouse/text operations.

Uses pyautogui + opencv-python under the hood, with lazy imports so the
module is safe to import even when those libraries are missing.
"""

from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass
from typing import Optional

from homelab_ai.config import logger

# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------
_IMPORTS: dict = {}

def _lazy(mod: str):
    if mod not in _IMPORTS:
        try:
            _IMPORTS[mod] = __import__(mod)
        except ImportError:
            return None
    return _IMPORTS[mod]


@dataclass
class UIRegion:
    """Describes a rectangular region on screen."""
    left: int
    top: int
    width: int
    height: int
    label: str = ""

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.width // 2, self.top + self.height // 2)

    @property
    def area(self) -> int:
        return self.width * self.height


class VisionAgent:
    """Take screenshots, find UI elements, and interact with non-CLI programs.

    Usage::

        va = VisionAgent()
        path = va.capture_screen()
        region = va.locate_image("button.png")
        if region:
            va.click(region.center[0], region.center[1])
        va.type_text("hello world")
    """

    def __init__(self, confidence: float = 0.8):
        self.confidence = confidence

    # ---- Screenshot ---------------------------------------------------------

    def capture_screen(self, save_path: str = "") -> str:
        """Take a full-screen screenshot and return its file path.

        Uses mss for reliable cross-platform capture (no gnome-screenshot needed).
        """
        mss_lib = _lazy("mss")
        if not mss_lib:
            return "Error: mss not installed (required for screenshots)."
        try:
            path = save_path or os.path.join(tempfile.gettempdir(),
                                             f"screenshot_{int(time.time())}.png")
            with mss_lib.MSS() as sct:
                sct.shot(output=path)
            size = os.path.getsize(path)
            logger.info("Screenshot saved: %s (%d bytes)", path, size)
            return path
        except Exception as exc:
            logger.error("Screenshot failed: %s", exc)
            return f"Error: {exc}"

    def capture_region(self, left: int, top: int, width: int, height: int,
                       save_path: str = "") -> str:
        """Capture a specific screen region using mss."""
        mss_lib = _lazy("mss")
        if not mss_lib:
            return "Error: mss not installed."
        try:
            path = save_path or os.path.join(tempfile.gettempdir(),
                                             f"region_{int(time.time())}.png")
            with mss_lib.MSS() as sct:
                monitor = {"left": left, "top": top, "width": width, "height": height}
                sct_img = sct.grab(monitor)
                from PIL import Image
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                img.save(path)
            return path
        except Exception as exc:
            return f"Error: {exc}"

    # ---- UI element location ------------------------------------------------

    def locate_image(self, image_path: str) -> Optional[UIRegion]:
        """Find an image on screen via template matching (pyautogui → OpenCV).

        Returns a UIRegion or None.
        """
        if not os.path.exists(image_path):
            logger.warning("Image not found: %s", image_path)
            return None
        pag = _lazy("pyautogui")
        if not pag:
            logger.warning("pyautogui not installed")
            return None
        try:
            pos = pag.locateOnScreen(image_path, confidence=self.confidence)
            if pos:
                return UIRegion(left=pos.left, top=pos.top,
                                width=pos.width, height=pos.height,
                                label=os.path.basename(image_path))
            return None
        except Exception as exc:
            logger.error("locate_image error: %s", exc)
            return None

    def locate_all_images(self, image_path: str) -> list[UIRegion]:
        """Find all occurrences of an image on screen."""
        if not os.path.exists(image_path):
            return []
        pag = _lazy("pyautogui")
        if not pag:
            return []
        try:
            positions = pag.locateAllOnScreen(image_path, confidence=self.confidence)
            return [
                UIRegion(left=p.left, top=p.top, width=p.width, height=p.height,
                         label=os.path.basename(image_path))
                for p in positions
            ]
        except Exception as exc:
            logger.error("locate_all_images error: %s", exc)
            return []

    def find_text_region(self, text: str) -> Optional[UIRegion]:
        """Attempt to find a text label on screen using OpenCV template matching.

        Note: this is a basic heuristic — it creates a simple image of the text
        and tries to match it. For production, use OCR (tesseract) instead.
        """
        cv2 = _lazy("cv2")
        if not cv2:
            logger.warning("opencv-python not installed")
            return None
        try:
            import numpy as np
            from PIL import Image, ImageDraw, ImageFont

            # Render the text to a small image
            font = ImageFont.load_default()
            dummy = Image.new("RGB", (1, 1))
            draw = ImageDraw.Draw(dummy)
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            if tw < 1 or th < 1:
                return None
            tmpl = Image.new("RGB", (tw + 4, th + 4), color="white")
            draw = ImageDraw.Draw(tmpl)
            draw.text((2, 2), text, fill="black", font=font)
            template = np.array(tmpl)
            template_gray = cv2.cvtColor(template, cv2.COLOR_RGB2GRAY)

            # Screenshot with mss and match
            mss_lib = _lazy("mss")
            if not mss_lib:
                return None
            from PIL import Image as PILImage
            with mss_lib.MSS() as sct:
                sct_img = sct.grab(sct.monitors[0])
                screen = np.array(PILImage.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX"))
            screen_gray = cv2.cvtColor(screen, cv2.COLOR_RGB2GRAY)

            result = cv2.matchTemplate(screen_gray, template_gray, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val >= self.confidence:
                return UIRegion(left=max_loc[0], top=max_loc[1],
                                width=tw, height=th, label=text)
            return None
        except Exception as exc:
            logger.error("find_text_region error: %s", exc)
            return None

    # ---- Screen parsing -----------------------------------------------------

    def get_screen_size(self) -> tuple[int, int]:
        """Return (width, height) of the primary monitor."""
        mss_lib = _lazy("mss")
        if mss_lib:
            try:
                with mss_lib.MSS() as sct:
                    m = sct.monitors[0]
                    return (m["width"], m["height"])
            except Exception:
                pass
        pag = _lazy("pyautogui")
        if pag:
            try:
                return pag.size()
            except Exception:
                pass
        return (0, 0)

    def get_ui_boundaries(self) -> list[UIRegion]:
        """Parse visual UI boundaries by detecting distinct colour regions.

        Uses OpenCV to segment the screen into rectangular regions.
        """
        cv2 = _lazy("cv2")
        if not cv2:
            return []
        try:
            import numpy as np
            from PIL import Image

            # Take screenshot with mss
            mss_lib = _lazy("mss")
            if not mss_lib:
                return []
            with mss_lib.MSS() as sct:
                sct_img = sct.grab(sct.monitors[0])
                screen = np.array(Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX"))
            gray = cv2.cvtColor(screen, cv2.COLOR_RGB2GRAY)
            edges = cv2.Canny(gray, 50, 150)
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL,
                                           cv2.CHAIN_APPROX_SIMPLE)
            regions = []
            for cnt in contours:
                x, y, w, h = cv2.boundingRect(cnt)
                if w * h < 500:          # skip tiny speckles
                    continue
                regions.append(UIRegion(x, y, w, h))
            regions.sort(key=lambda r: r.area, reverse=True)
            return regions[:50]           # return top 50
        except Exception as exc:
            logger.error("get_ui_boundaries error: %s", exc)
            return []

    # ---- Mouse & keyboard interaction ---------------------------------------

    def click(self, x: int, y: int, button: str = "left") -> str:
        """Click at (x, y)."""
        pag = _lazy("pyautogui")
        if not pag:
            return "Error: pyautogui not installed."
        try:
            pag.click(x, y, button=button)
            return f"Clicked ({x}, {y}) with {button}."
        except Exception as exc:
            return f"Error clicking: {exc}"

    def double_click(self, x: int, y: int) -> str:
        """Double-click at (x, y)."""
        pag = _lazy("pyautogui")
        if not pag:
            return "Error: pyautogui not installed."
        try:
            pag.doubleClick(x, y)
            return f"Double-clicked ({x}, {y})."
        except Exception as exc:
            return f"Error: {exc}"

    def right_click(self, x: int, y: int) -> str:
        """Right-click at (x, y)."""
        return self.click(x, y, button="right")

    def type_text(self, text: str, interval: float = 0.05) -> str:
        """Type text with a small delay between keystrokes."""
        pag = _lazy("pyautogui")
        if not pag:
            return "Error: pyautogui not installed."
        try:
            pag.typewrite(text, interval=interval)
            return f"Typed {len(text)} characters."
        except Exception as exc:
            return f"Error typing: {exc}"

    def press_key(self, key: str) -> str:
        """Press a single key (e.g. 'enter', 'tab', 'escape')."""
        pag = _lazy("pyautogui")
        if not pag:
            return "Error: pyautogui not installed."
        try:
            pag.press(key)
            return f"Pressed '{key}'."
        except Exception as exc:
            return f"Error: {exc}"

    def hotkey(self, *keys: str) -> str:
        """Press a combination of keys (e.g. hotkey('ctrl', 'c'))."""
        pag = _lazy("pyautogui")
        if not pag:
            return "Error: pyautogui not installed."
        try:
            pag.hotkey(*keys)
            return f"Hotkey {'+'.join(keys)} pressed."
        except Exception as exc:
            return f"Error: {exc}"

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int,
             duration: float = 0.3) -> str:
        """Click and drag from (start_x, start_y) to (end_x, end_y)."""
        pag = _lazy("pyautogui")
        if not pag:
            return "Error: pyautogui not installed."
        try:
            pag.moveTo(start_x, start_y)
            pag.drag(end_x - start_x, end_y - start_y, duration=duration)
            return f"Dragged from ({start_x},{start_y}) to ({end_x},{end_y})."
        except Exception as exc:
            return f"Error: {exc}"

    # ---- Convenience --------------------------------------------------------

    def status_summary(self) -> str:
        """Return a one-line summary of what the agent can do."""
        pag_ok = bool(_lazy("pyautogui"))
        cv_ok = bool(_lazy("cv2"))
        parts = [
            f"mss={'OK' if bool(_lazy('mss')) else 'MISSING'}",
            f"pyautogui={'OK' if bool(_lazy('pyautogui')) else 'MISSING'}",
            f"opencv={'OK' if bool(_lazy('cv2')) else 'MISSING'}",
        ]
        sw, sh = self.get_screen_size()
        parts.append(f"screen={sw}x{sh}")
        return "VisionAgent: " + " | ".join(parts)
