import datetime
import re
from pathlib import Path
from typing import Optional

from colorama import Fore

from llm_query import ModelSwitch


class TracingModelSwitch(ModelSwitch):
    """
    A wrapper around ModelSwitch that adds logging for LLM queries.
    """

    def __init__(self, trace_llm: bool = False, trace_dir: str = "llm_traces", **kwargs):
        """
        Initializes the TracingModelSwitch.

        Args:
            trace_llm: If True, log LLM prompts and responses.
            trace_dir: Directory to save LLM traces.
            **kwargs: Arguments to pass to the parent ModelSwitch constructor.
        """
        super().__init__(**kwargs)
        self.trace_llm = trace_llm
        self.trace_run_dir: Optional[Path] = None
        if self.trace_llm:
            trace_dir_path = Path(trace_dir)
            run_timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            self.trace_run_dir = trace_dir_path / run_timestamp
            self.trace_run_dir.mkdir(parents=True, exist_ok=True)

    def query(self, model_name: str, prompt: str, **kwargs) -> str:
        """
        Executes a query and logs the prompt and response if tracing is enabled.
        """
        # The parent query method consistently returns a string.
        response_content = super().query(model_name, prompt, **kwargs)

        if self.trace_llm and self.trace_run_dir:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            # Sanitize model_name for filename
            safe_model_name = re.sub(r'[\\/*?:"<>|]', "_", model_name)
            trace_file_path = self.trace_run_dir / f"{timestamp}_{safe_model_name}.log"

            log_parts = [
                "--- PROMPT ---",
                f"Model: {model_name}",
                f"Timestamp: {datetime.datetime.now().isoformat()}",
                "----------------",
                "",
                prompt,
                "",
                "",
                "--- RESPONSE ---",
                "----------------",
                "",
                response_content,
            ]
            trace_content = "\n".join(log_parts)

            try:
                with trace_file_path.open("w", encoding="utf-8") as f:
                    f.write(trace_content)
                print(Fore.YELLOW + f"LLM trace saved to: {trace_file_path}")
            except IOError as e:
                print(Fore.RED + f"Error saving LLM trace: {e}")

        return response_content
