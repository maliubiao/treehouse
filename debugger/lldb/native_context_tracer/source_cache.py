import hashlib
import logging
import os

import lldb


class SourceCacheManager:
    """管理源文件过滤的缓存系统（TSV格式）"""

    def __init__(self, target, logger, config_manager):
        self.target = target
        self.logger = logger
        self.config_manager = config_manager
        self.cache_dir = config_manager.config.get("cache_dir", "cache")
        os.makedirs(self.cache_dir, exist_ok=True)

    def get_cache_file_path(self, module_path):
        """获取缓存文件路径（TSV格式）"""
        module_name = os.path.basename(module_path)
        return os.path.join(self.cache_dir, f"source_cache_{module_name}.tsv")

    def compute_file_hash(self, file_path):
        """计算文件哈希值用于验证缓存有效性"""
        if not os.path.exists(file_path):
            return None

        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    def save_cache(self, module, symbols_info):
        """保存缓存到TSV文件"""
        module_path = module.GetFileSpec().fullpath
        cache_file = self.get_cache_file_path(module_path)

        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                # 写入头部信息
                f.write(f"module_path\t{module_path}\n")
                f.write(f"file_hash\t{self.compute_file_hash(module_path)}\n")
                f.write(f"uuid\t{module.GetUUIDString()}\n")

                # 写入符号数据
                for symbol_name, start_addr, end_addr in symbols_info:
                    f.write(f"{symbol_name}\t{start_addr}\t{end_addr}\n")

            self.logger.info("Saved source cache for %s", os.path.basename(module_path))
        except Exception as e:
            self.logger.error("Failed to save cache: %s", str(e))

    def load_cache(self, module):
        """从TSV缓存文件加载数据"""
        module_path = module.GetFileSpec().fullpath
        cache_file = self.get_cache_file_path(module_path)

        if not os.path.exists(cache_file):
            return None

        try:
            symbols_info = []
            with open(cache_file, "r", encoding="utf-8") as f:
                # 读取头部信息
                headers = {}
                for i in range(3):
                    line = f.readline().strip()
                    key, value = line.split("\t", 1)
                    headers[key] = value

                # 验证缓存有效性
                current_hash = self.compute_file_hash(module_path)
                if headers.get("file_hash") != current_hash:
                    self.logger.warning("Cache invalid: file hash changed for %s", module_path)
                    return None

                if headers.get("uuid") != module.GetUUIDString():
                    self.logger.warning("Cache invalid: UUID changed for %s", module_path)
                    return None

                # 读取符号数据
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) == 3:
                        symbol_name = parts[0]
                        start_addr = int(parts[1])
                        end_addr = int(parts[2])
                        symbols_info.append((symbol_name, start_addr, end_addr))

            return symbols_info
        except Exception as e:
            self.logger.error("Error loading cache: %s", str(e))
            return None

    def apply_alsr_correction(self, symbol_info, module_load_base):
        """应用ALSR修正到符号地址"""
        corrected = []
        for symbol_name, file_start_addr, file_end_addr in symbol_info:
            corrected.append((symbol_name, file_start_addr + module_load_base, file_end_addr + module_load_base))
        return corrected
