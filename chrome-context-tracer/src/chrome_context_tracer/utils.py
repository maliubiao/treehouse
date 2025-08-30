import os
import socket
from typing import Optional, Set

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


def find_free_safe_port() -> int:
    """
    Finds a free TCP port that is not in Chrome's list of unsafe ports.
    """
    # List of unsafe ports in Chrome. Not exhaustive but covers common ones.
    # Source: https://chromium.googlesource.com/chromium/src/+/main/net/base/port_util.cc
    # This list is simplified for the test's purpose.
    unsafe_ports: Set[int] = {
        1,
        7,
        9,
        11,
        13,
        15,
        17,
        19,
        20,
        21,
        22,
        23,
        25,
        37,
        42,
        43,
        53,
        77,
        79,
        87,
        95,
        101,
        102,
        103,
        104,
        109,
        110,
        111,
        113,
        115,
        117,
        119,
        123,
        135,
        139,
        143,
        179,
        389,
        427,
        465,
        512,
        513,
        514,
        515,
        526,
        530,
        531,
        532,
        540,
        556,
        563,
        587,
        601,
        636,
        993,
        995,
        2049,
        3659,
        4045,
        6000,
        6665,
        6666,
        6667,
        6668,
        6669,
    }
    while True:
        # Create a new socket to find a free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            # Get the port number assigned by the OS
            port: int = s.getsockname()[1]
        # Check if the port is safe and above the well-known ports range
        if port not in unsafe_ports and port >= 1024:
            return port
