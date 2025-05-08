from typing import Any
import lldb


class ErrorHandler:
    ERROR_MAPPING = {
        1: "API call failed",
        2: "Context too large",
        3: "Invalid command format, use 'askgpt <command> :: <question>'",
        4: "Invalid characters detected",
        5: "Debug context collection failed",
        127: "askgpt command not found",
    }

    @staticmethod
    def classify_error(error_obj: Any) -> int:
        if isinstance(error_obj, lldb.SBCommandReturnObject) and not error_obj.Succeeded():
            error_msg = error_obj.GetError()
            if "invalid command" in error_msg.lower():
                return 3
            if "failed" in error_msg.lower():
                return 1
        if isinstance(error_obj, Exception):
            error_msg = str(error_obj)
            if "context" in error_msg.lower():
                return 5
            if "format" in error_msg.lower():
                return 3
        return 1

    @staticmethod
    def get_error_message(error_code: int) -> str:
        return ErrorHandler.ERROR_MAPPING.get(error_code, f"Unknown error: {error_code}")

    @staticmethod
    def handle(error: Any, result: lldb.SBCommandReturnObject) -> None:
        if isinstance(error, int):
            error_code = error
        else:
            error_code = ErrorHandler.classify_error(error)

        error_msg = ErrorHandler.get_error_message(error_code)
        result.SetError(error_msg)
