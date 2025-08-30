import json
import locale
import os
import platform
import subprocess
from typing import Any, Dict

# 全局变量，用于存储加载的翻译
_translations: Dict[str, str] = {}
_language: str = "en"


def _get_system_language() -> str:
    """
    Tries to determine the system's preferred language, defaulting to 'en'.
    - On macOS, it queries system preferences, which may differ from the terminal's locale.
    - On other systems, it relies on the standard `locale` module.
    """
    # On macOS, the terminal's locale can be different from the system UI language.
    # We prioritize the system UI language, as users often expect that behavior.
    if platform.system() == "Darwin":
        try:
            # This command reads the user's preferred languages list from system preferences.
            proc = subprocess.run(
                ["defaults", "read", "-g", "AppleLanguages"],
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8",
            )
            # The output is a string like: '( "en-US", "zh-Hans-US" )'
            # We perform a simple parse to extract the first (primary) language.
            output = proc.stdout.strip()
            if output.startswith("(") and output.endswith(")"):
                # Clean up the string and split into a list of languages
                langs = output[1:-1].strip().replace('"', "").replace(" ", "").split(",")
                if langs and langs[0]:
                    primary_lang = langs[0].lower()
                    if primary_lang.startswith("zh"):
                        return "zh"
        except (FileNotFoundError, subprocess.CalledProcessError, IndexError):
            # If `defaults` command fails for any reason, fall through to locale-based detection.
            pass

    # For other systems or as a fallback for macOS
    try:
        lang_code, _ = locale.getdefaultlocale()
        if lang_code:
            if lang_code.lower().startswith("zh"):
                return "zh"
    except Exception:
        # If locale detection fails, we'll fall back to 'en'.
        pass

    return "en"


def _load_translations() -> None:
    """
    Detects the system language and loads the appropriate translation file.
    The language can be overridden by setting the `CCT_LANG` environment variable (e.g., `CCT_LANG=zh`).
    Defaults to English if the detected language is not supported or files are missing.
    """
    global _translations, _language

    # Determine language
    # 1. Environment variable override has the highest priority.
    env_lang = os.environ.get("CCT_LANG")
    if env_lang and env_lang.lower() in ["en", "zh"]:
        _language = env_lang.lower()
    else:
        # 2. Automatically detect system language using our enhanced logic.
        _language = _get_system_language()

    # Construct the path to the translation file
    locales_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")
    translation_file = os.path.join(locales_dir, f"{_language}.json")

    if os.path.exists(translation_file):
        try:
            with open(translation_file, "r", encoding="utf-8") as f:
                _translations = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load or parse translation file '{translation_file}': {e}")
            _translations = {}
    else:
        # If the file for the detected language doesn't exist, we default to English
        # by using an empty translation map, so the original keys will be used.
        if _language != "en":
            # This warning is commented out to avoid noise for users on unsupported systems.
            # print(f"Warning: Translation file for language '{_language}' not found. Falling back to English keys.")
            pass
        _translations = {}


def _(key: str, **kwargs: Any) -> str:
    """
    Translates a given key using the loaded language file and formats it with provided arguments.

    Args:
        key: The string key to translate (which is the English source string).
        **kwargs: Keyword arguments for string formatting.

    Returns:
        The translated and formatted string. Returns the key itself if not found.
    """
    # Get the translated string, default to the key itself (English)
    translated_str = _translations.get(key, key)

    # Format the string with any provided keyword arguments
    if kwargs:
        try:
            return translated_str.format(**kwargs)
        except KeyError as e:
            # This can happen if placeholders don't match between languages
            print(f"Warning: Formatting error in translation for key '{key}'. Missing placeholder: {e}")
            # Fallback to formatting the original key
            try:
                return key.format(**kwargs)
            except KeyError:
                return key

    return translated_str


# Load translations when the module is imported
_load_translations()
