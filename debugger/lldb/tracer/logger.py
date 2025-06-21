import atexit
import logging
import time
from collections import deque


class LogManager:
    class RelativeTimeFilter(logging.Filter):
        def __init__(self, start_time):
            super().__init__()
            self.start_time = start_time

        def filter(self, record):
            # 计算相对时间（毫秒）
            elapsed_ms = (time.perf_counter() - self.start_time) * 1000
            record.relative_time = elapsed_ms
            return True

    class BufferedHandler(logging.Handler):
        def __init__(self, buffer_size=10, target_handler=None):
            super().__init__()
            self.buffer = deque(maxlen=buffer_size)
            self.target_handler = target_handler
            self._register_atexit()

        def _register_atexit(self):
            atexit.register(self.flush)

        def emit(self, record):
            # 格式化日志记录但不立即输出
            msg = self.format(record)
            self.buffer.append(msg)
            if len(self.buffer) >= self.buffer.maxlen:
                self.flush()

        def flush(self):
            if not self.buffer:
                return

            # 合并缓冲区中的所有日志记录
            combined_msg = "\n".join(self.buffer)
            self.buffer.clear()

            # 使用目标处理器输出合并后的日志
            if self.target_handler:
                self.target_handler.stream.write(combined_msg + "\n")
                self.target_handler.flush()

        def setTarget(self, target_handler):
            self.target_handler = target_handler

    def __init__(self, config, logfile=None):
        self.config = config
        self.logfile = logfile
        self.logger = logging.getLogger("Tracer")
        self.logger.setLevel(logging.DEBUG)
        # 记录启动时间戳
        self.start_time = time.perf_counter()
        self.buffered_handler = None
        self._init_logger()

    def _init_logger(self):
        # 清除所有现有处理器
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)

        # 清除旧的时间过滤器
        for f in self.logger.filters[:]:
            if isinstance(f, LogManager.RelativeTimeFilter):
                self.logger.removeFilter(f)

        # 添加新的相对时间过滤器
        time_filter = LogManager.RelativeTimeFilter(self.start_time)
        self.logger.addFilter(time_filter)

        # 使用相对时间的日志格式
        # formatter = logging.Formatter("[%(relative_time)12.3f] %(message)s")
        formatter = logging.Formatter("%(message)s")

        # 如果指定了日志文件，只添加文件处理器
        if self.logfile:
            file_handler = logging.FileHandler(self.logfile)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)
        # 否则添加带缓冲的控制台处理器
        else:
            # 创建底层实际处理器
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)

            # 根据配置决定是否使用缓冲
            buffer_size = self.config.get("log_buffer_size", 10)
            if buffer_size > 1:
                self.buffered_handler = LogManager.BufferedHandler(
                    buffer_size=buffer_size, target_handler=console_handler
                )
                self.logger.addHandler(self.buffered_handler)
            else:
                self.logger.addHandler(console_handler)

    # 常用日志方法代理
    def debug(self, msg, *args, **kwargs):
        self.logger.debug(msg, *args, **kwargs)

    def info(self, msg, *args, **kwargs):
        self.logger.info(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        self.logger.warning(msg, *args, **kwargs)

    def error(self, msg, *args, **kwargs):
        self.logger.error(msg, *args, **kwargs)

    def critical(self, msg, *args, **kwargs):
        self.logger.critical(msg, *args, **kwargs)

    def exception(self, msg, *args, **kwargs):
        self.logger.exception(msg, *args, **kwargs)

    def flush(self):
        """手动刷新日志缓冲区"""
        if self.buffered_handler:
            self.buffered_handler.flush()
        for handler in self.logger.handlers:
            handler.flush()

    def log_target_info(self, target):
        if not self.config.get("log_target_info"):
            return

        self.logger.debug("Target info:")
        self.logger.debug("  Triple: %s", target.GetTriple())
        self.logger.debug("  Address byte size: %s", target.GetAddressByteSize())
        self.logger.debug("  Byte order: %s", target.GetByteOrder())
        self.logger.debug("  Code byte size: %s", target.GetCodeByteSize())
        self.logger.debug("  Data byte size: %s", target.GetDataByteSize())
        self.logger.debug("  ABI name: %s", target.GetABIName())

        executable = target.GetExecutable()
        if executable:
            self.logger.debug("  Executable: %s", executable.fullpath)

        platform = target.GetPlatform()
        if platform:
            self.logger.debug("  Platform: %s", platform.GetName())

    def log_module_info(self, module):
        if not self.config.get("log_module_info"):
            return

        self.logger.debug("Module info:")
        self.logger.debug("  File: %s", module.GetFileSpec().fullpath)
        self.logger.debug("  UUID: %s", module.GetUUIDString())
        self.logger.debug("  Num symbols: %s", module.GetNumSymbols())
        self.logger.debug("  Num sections: %s", module.GetNumSections())
        self.logger.debug("  Num compile units: %s", module.GetNumCompileUnits())

    def log_breakpoint_info(self, bp):
        if not self.config.get("log_breakpoint_details"):
            return

        self.logger.debug("Breakpoint info:")
        self.logger.debug("  ID: %s", bp.GetID())
        self.logger.debug("  Enabled: %s", bp.IsEnabled())
        self.logger.debug("  One shot: %s", bp.IsOneShot())
        self.logger.debug("  Internal: %s", bp.IsInternal())
        self.logger.debug("  Hardware: %s", bp.IsHardware())
        self.logger.debug("  Condition: %s", bp.GetCondition())
        self.logger.debug("  Hit count: %s", bp.GetHitCount())
        self.logger.debug("  Num locations: %s", bp.GetNumLocations())


# 注册全局退出处理函数
atexit.register(lambda: logging.shutdown())
