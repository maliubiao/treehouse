import os
from typing import Optional

from .i18n import _

# --- JavaScript Loader ---
# Memoize the file content to avoid repeated disk reads
_MOUSE_DETECTOR_JS_CODE: Optional[str] = None


def get_mouse_detector_js() -> str:
    """Reads and caches the mouse detector JavaScript code from its file."""
    global _MOUSE_DETECTOR_JS_CODE
    if _MOUSE_DETECTOR_JS_CODE is None:
        try:
            # The JS file is expected to be in the same directory as this script
            # after being moved by the setup process.
            script_dir = os.path.dirname(os.path.abspath(__file__))
            js_path = os.path.join(script_dir, "mouse_element_detector.js")
            with open(js_path, "r", encoding="utf-8") as f:
                _MOUSE_DETECTOR_JS_CODE = f.read()
        except FileNotFoundError:
            print(_("FATAL: JavaScript file not found at {js_path}", js_path=js_path))
            print(_("Please ensure 'mouse_element_detector.js' is present in the package directory."))
            raise
    return _MOUSE_DETECTOR_JS_CODE
