#!/usr/bin/env python3
"""
测试V4容器格式：FileManager存储在文件末尾
"""

import os
import sys
import tempfile
from pathlib import Path

# 添加当前目录到Python路径
sys.path.insert(0, str(Path(__file__).parent))

from context_tracer.container import DataContainerReader, DataContainerWriter, EventType, FileManager, TraceEvent
from context_tracer.source_manager import SourceManager


def test_v4_format_filemanager_position():
    """测试V4格式的FileManager位置跟踪"""
    print("=== 测试 V4 格式 FileManager 位置跟踪 ===")

    with tempfile.TemporaryDirectory() as temp_dir:
        container_path = Path(temp_dir) / "v4_test.bin"
        key = b"0123456789abcdef" * 2  # 32字节密钥

        # 创建FileManager和SourceManager
        file_manager = FileManager()
        source_manager = SourceManager()
        file1_id = file_manager.get_id("/path/to/v4_test.py")
        file2_id = file_manager.get_id("<string>", "print('v4 test')")

        # 写入数据
        writer = DataContainerWriter(container_path, key, file_manager, source_manager)
        writer.open()

        # 创建测试事件
        events = [
            TraceEvent(
                event_type=EventType.CALL.value,
                timestamp=1234567890.0,
                thread_id=12345,
                frame_id=1,
                file_id=file1_id,
                lineno=10,
                data=["v4_function", "arg1"],
            ),
            TraceEvent(
                event_type=EventType.LINE.value,
                timestamp=1234567890.1,
                thread_id=12345,
                frame_id=1,
                file_id=file1_id,
                lineno=11,
                data=["x = 1", "x = 1", []],
            ),
            TraceEvent(
                event_type=EventType.RETURN.value,
                timestamp=1234567890.2,
                thread_id=12345,
                frame_id=1,
                file_id=file1_id,
                lineno=12,
                data=["v4_function", "None", []],
            ),
        ]

        for event in events:
            writer.add_event(event)

        writer.close()
        print(f"V4容器文件创建: {container_path}")

        # 读取并验证V4格式
        reader = DataContainerReader(container_path, key)
        reader.open()

        print(f"格式版本: {reader._format_version}")
        print(f"元数据位置: {reader._metadata_position}")

        # 验证元数据位置不为0
        assert reader._metadata_position > 0, "元数据位置应为非零值"

        # 验证FileManager和SourceManager都已加载
        assert reader.file_manager is not None, "FileManager应该已加载"
        assert reader.source_manager is not None, "SourceManager应该已加载"

        # 读取所有事件
        read_events = list(reader)
        print(f"读取到 {len(read_events)} 个事件")

        # 验证事件数量
        assert len(read_events) == 3, f"应读取3个事件，实际读取{len(read_events)}个"

        # 验证文件路径映射
        for i, event in enumerate(read_events):
            file_path = reader.file_manager.get_path(event.file_id)
            print(f"事件 {i}: 文件={file_path}, 行号={event.lineno}")
            assert file_path is not None, f"事件 {i} 的文件路径不应为None"

        reader.close()
        print("✅ V4格式测试通过\n")


def test_v4_format_empty_container():
    """测试空的V4容器"""
    print("=== 测试 空V4容器 ===")

    with tempfile.TemporaryDirectory() as temp_dir:
        container_path = Path(temp_dir) / "empty_v4_test.bin"
        key = b"0123456789abcdef" * 2

        # 创建空的FileManager和SourceManager
        file_manager = FileManager()
        source_manager = SourceManager()

        # 写入空容器
        writer = DataContainerWriter(container_path, key, file_manager, source_manager)
        writer.open()
        writer.close()

        print(f"空V4容器文件创建: {container_path}")

        # 读取空容器
        reader = DataContainerReader(container_path, key)
        reader.open()

        print(f"格式版本: {reader._format_version}")
        print(f"元数据位置: {reader._metadata_position}")

        # 验证管理器已加载
        assert reader.file_manager is not None, "FileManager应该已加载"
        assert reader.source_manager is not None, "SourceManager应该已加载"

        # 对于空容器，元数据位置应该大于0（总是会写入元数据）
        read_events = list(reader)
        print(f"读取到 {len(read_events)} 个事件")

        assert len(read_events) == 0, "空容器应读取0个事件"

        reader.close()
        print("✅ 空V4容器测试通过\n")


if __name__ == "__main__":
    print("开始V4格式测试...\n")

    try:
        test_v4_format_filemanager_position()
        test_v4_format_empty_container()

        print("🎉 V4格式所有测试通过！")

    except Exception as e:
        print(f"❌ V4格式测试失败: {e}")
        import traceback

        traceback.print_exc()
