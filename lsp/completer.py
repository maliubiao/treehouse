import os

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
            for f in os.listdir(cwd):
                if f.startswith(current_word):
                    yield Completion(
                        f, start_position=-len(current_word), display_meta="文件" if os.path.isfile(f) else "目录"
                    )
