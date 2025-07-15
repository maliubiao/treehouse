#!/usr/bin/env python3
"""
SSE事件验证工具 - 用于检查原始和转换后的SSE事件是否匹配
"""

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sse_validator")


class SSEValidator:
    """SSE事件配对验证器"""

    def __init__(self, debug_dir: str = "logs/sse_debug"):
        self.debug_dir = Path(debug_dir)

    def validate_request(self, request_id: str, date_str: str = None) -> Dict[str, Any]:
        """验证单个请求的事件配对"""
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        request_dir = self.debug_dir / date_str / request_id
        if not request_dir.exists():
            return {"error": f"Request directory not found: {request_dir}"}

        raw_events_file = request_dir / "raw_events.log"
        translated_events_file = request_dir / "translated_events.log"
        metadata_file = request_dir / "metadata.json"

        if not raw_events_file.exists():
            return {"error": "Raw events file not found"}
        if not translated_events_file.exists():
            return {"error": "Translated events file not found"}

        raw_events = self._load_events(raw_events_file)
        translated_events = self._load_events(translated_events_file)

        # 基本统计
        stats = {
            "request_id": request_id,
            "raw_events_count": len(raw_events),
            "translated_events_count": len(translated_events),
            "metadata": self._load_metadata(metadata_file),
            "match_analysis": self._analyze_events(raw_events, translated_events),
        }

        return stats

    def _load_events(self, file_path: Path) -> List[Dict[str, Any]]:
        """加载SSE事件"""
        events = []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError as json_e:
                            logger.error("Failed to decode JSON from line in %s: %s", file_path, json_e, exc_info=True)
                            # Continue processing other lines even if one fails
        except OSError as os_e:  # Catches FileNotFoundError, PermissionError, etc.
            logger.error("Failed to open or read file %s: %s", file_path, os_e, exc_info=True)
        # 移除了对通用 Exception 的捕获，更具体的错误现在会向上层传播。
        return events

    def _load_metadata(self, metadata_file: Path) -> Dict[str, Any]:
        """加载metadata"""
        try:
            if metadata_file.exists():
                with open(metadata_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except json.JSONDecodeError as json_e:
            logger.error("Failed to decode JSON from metadata file %s: %s", metadata_file, json_e, exc_info=True)
        except OSError as os_e:  # Catches FileNotFoundError, PermissionError, etc.
            logger.error("Failed to open or read metadata from %s: %s", metadata_file, os_e, exc_info=True)
        # 移除了对通用 Exception 的捕获，更具体的错误现在会向上层传播。
        return {}

    def _analyze_events(self, raw_events: List[Dict], translated_events: List[Dict]) -> Dict[str, Any]:
        """分析事件匹配情况"""
        analysis = {
            "raw_reasoning_events": 0,
            "raw_text_events": 0,
            "raw_tool_events": 0,
            "translated_start_events": 0,
            "translated_delta_events": 0,
            "translated_stop_events": 0,
            "sequence_check": [],
            "warnings": [],
        }

        # 统计原始事件类型
        for event in raw_events:
            if "reasoning_content" in str(event.get("data", {})).lower():
                analysis["raw_reasoning_events"] += 1
            if "content" in event.get("data", {}):
                analysis["raw_text_events"] += 1
            if "tool_calls" in str(event.get("data", {})).lower():
                analysis["raw_tool_events"] += 1

        # 统计转换事件类型
        for event in translated_events:
            event_type = event.get("event_type", "")
            if event_type == "message_start":
                analysis["translated_start_events"] += 1
            elif event_type in ["content_block_delta", "content_block_start"]:
                analysis["translated_delta_events"] += 1
            elif event_type in ["message_stop", "content_block_stop"]:
                analysis["translated_stop_events"] += 1

        # 检查事件序列
        if not translated_events:
            analysis["warnings"].append("No translated events found")

        # 检查可能的丢失事件
        if analysis["raw_reasoning_events"] > 0 and analysis["translated_delta_events"] == 0:
            analysis["warnings"].append("Potential reasoning events lost in translation")

        return analysis

    def list_recent_requests(self, days_ahead: int = 0, days_back: int = 1) -> List[str]:
        """列出最近的请求ID"""
        today = datetime.now()
        date_dirs = []

        # Pylint E0606: Variable 'timedelta' might be used before assignment.
        # Ensure 'from datetime import timedelta' is present in the file's imports.
        for offset in range(-days_back, days_ahead + 1):
            date_dir = (today.date() - timedelta(days=offset)).strftime("%Y-%m-%d")
            if (self.debug_dir / date_dir).exists():
                date_dirs.append(date_dir)

        all_requests = []
        for date_dir in date_dirs:
            date_path = self.debug_dir / date_dir
            if date_path.exists():
                for request_dir in date_path.iterdir():
                    if request_dir.is_dir():
                        all_requests.append(f"{date_dir}/{request_dir.name}")

        return sorted(all_requests)


def main():
    parser = argparse.ArgumentParser(description="SSE事件验证工具")
    parser.add_argument("--request-id", help="要验证的请求ID")
    parser.add_argument("--date", help="日期(YYYY-MM-DD格式)")
    parser.add_argument("--list", action="store_true", help="列出最近的请求")
    parser.add_argument("--debug-dir", default="logs/sse_debug", help="调试目录路径")

    args = parser.parse_args()

    validator = SSEValidator(debug_dir=args.debug_dir)

    if args.list:
        requests = validator.list_recent_requests()
        print("最近的SSE调试记录:")
        for req in requests:
            print(f"  {req}")

    elif args.request_id:
        if args.date:
            date_str = args.date
            request_id = args.request_id
        else:
            # 处理形如"YYYY-MM-DD/request-id"的格式
            parts = args.request_id.split("/")
            if len(parts) == 2:
                date_str, request_id = parts
            else:
                date_str = datetime.now().strftime("%Y-%m-%d")
                request_id = parts[0]

        result = validator.validate_request(request_id, date_str)
        print(json.dumps(result, indent=2, ensure_ascii=False))

    else:
        parser.print_help()


if __name__ == "__main__":
    from datetime import timedelta  # Import here to avoid import issues

    main()
