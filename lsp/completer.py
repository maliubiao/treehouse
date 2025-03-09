import os
from pathlib import Path

from prompt_toolkit.completion import Completer, Completion


class LSPCompleter(Completer):
    def __init__(self, plugin_manager):
        self.plugin_manager = plugin_manager

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.split()
        if not text:
            return

        commands_meta = self.plugin_manager.get_commands_meta()

        if len(text) == 1:
            current_word = text[0].lower()
            for cmd, meta in commands_meta.items():
                if cmd.startswith(current_word):
                    display_meta = f"{meta['desc']} 参数: {' '.join(meta['params'])}"
                    yield Completion(cmd, start_position=-len(current_word), display_meta=display_meta)
            return

        cmd = text[0].lower()
        if cmd not in commands_meta:
            return

        param_index = len(text) - 2
        params = commands_meta[cmd]["params"]
        if param_index >= len(params):
            return

        param_name = params[param_index]
        current_word = text[-1]

        if param_name == "file_path":
            cwd = os.getcwd()

            # 分割目录部分和前缀
            if "/" in current_word:
                last_slash_pos = current_word.rfind("/")
                dir_part_str = current_word[: last_slash_pos + 1]
                prefix = current_word[last_slash_pos + 1 :]
            else:
                dir_part_str = ""
                prefix = current_word

            search_dir = Path(cwd) / dir_part_str

            if not search_dir.exists() or not search_dir.is_dir():
                return

            for entry in search_dir.iterdir():
                entry_name = entry.name
                if entry.is_dir():
                    entry_name += "/"
                if entry_name.startswith(prefix):
                    start_pos = -len(prefix) if prefix else 0
                    display_type = "目录" if entry.is_dir() else "文件"
                    yield Completion(entry_name, start_position=start_pos, display_meta=display_type)
