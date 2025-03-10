import os
from logging import getLogger

logger = getLogger(__name__)


class LanguageId:
    EXTENSION_TO_LANGUAGE = {
        # File extensions mapped to LSP language identifiers
        ".abap": "abap",
        ".bat": "bat",
        ".cmd": "bat",
        ".bib": "bibtex",
        ".clj": "clojure",
        ".cljs": "clojure",
        ".cljc": "clojure",
        ".coffee": "coffeescript",
        ".c": "c",
        ".h": "c",
        ".cpp": "cpp",
        ".hpp": "cpp",
        ".cc": "cpp",
        ".cxx": "cpp",
        ".cs": "csharp",
        ".css": "css",
        ".diff": "diff",
        ".patch": "diff",
        ".dart": "dart",
        "dockerfile": "dockerfile",
        ".ex": "elixir",
        ".exs": "elixir",
        ".erl": "erlang",
        ".hrl": "erlang",
        ".fs": "fsharp",
        ".fsi": "fsharp",
        ".fsx": "fsharp",
        ".go": "go",
        ".groovy": "groovy",
        ".gvy": "groovy",
        ".handlebars": "handlebars",
        ".hbs": "handlebars",
        ".html": "html",
        ".htm": "html",
        ".ini": "ini",
        ".java": "java",
        ".js": "javascript",
        ".jsx": "javascriptreact",
        ".json": "json",
        ".tex": "latex",
        ".less": "less",
        ".lua": "lua",
        "makefile": "makefile",
        ".mk": "makefile",
        ".md": "markdown",
        ".m": "objective-c",
        ".mm": "objective-cpp",
        ".pl": "perl",
        ".pm": "perl",
        ".php": "php",
        ".ps1": "powershell",
        ".psm1": "powershell",
        ".jade": "jade",
        ".pug": "jade",
        ".py": "python",
        ".r": "r",
        ".cshtml": "razor",
        ".rb": "ruby",
        ".rs": "rust",
        ".scss": "scss",
        ".sass": "sass",
        ".scala": "scala",
        ".shader": "shaderlab",
        ".sh": "shellscript",
        ".bash": "shellscript",
        ".zsh": "shellscript",
        ".sql": "sql",
        ".swift": "swift",
        ".ts": "typescript",
        ".tsx": "typescriptreact",
        ".tex": "tex",
        ".vb": "vb",
        ".xml": "xml",
        ".xsl": "xsl",
        ".xslt": "xsl",
        ".yaml": "yaml",
        ".yml": "yaml",
    }

    @classmethod
    def get_language_id(cls, file_path):
        """Get LSP language ID for given file path"""
        filename = os.path.basename(file_path).lower()
        if filename in cls.EXTENSION_TO_LANGUAGE:
            return cls.EXTENSION_TO_LANGUAGE[filename]

        _, ext = os.path.splitext(file_path)
        ext = ext.lower()
        return cls.EXTENSION_TO_LANGUAGE.get(ext, "plaintext")
