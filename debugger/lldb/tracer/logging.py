import logging


class LogManager:
    def __init__(self, config, logfile=None):
        self.config = config
        self.logfile = logfile
        self.logger = logging.getLogger("Tracer")
        self.logger.setLevel(logging.DEBUG)
        self._init_logger()

    def _init_logger(self):
        formatter = logging.Formatter("[%(asctime)s][%(thread)d][%(levelname)s][%(lineno)d] %(message)s")

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

        if self.logfile:
            file_handler = logging.FileHandler(self.logfile)
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

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
