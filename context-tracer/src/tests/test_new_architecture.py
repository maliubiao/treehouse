#!/usr/bin/env python3
"""
测试新架构：FileManager和SourceManager分离
1. 测试FileManager只负责文件ID映射
2. 测试SourceManager只负责源代码存储
3. 测试两者在V4容器格式中的协作
4. 测试向后兼容性
5. 测试与TraceLogic的集成
"""

import os
import sys
import tempfile
from pathlib import Path

# 添加当前目录到Python路径
sys.path.insert(0, str(Path(__file__).parent))

from context_tracer.container import DataContainerReader, DataContainerWriter, EventType, FileManager, TraceEvent
from context_tracer.source_manager import SourceManager
from context_tracer.tracer import TraceConfig, TraceLogic
from context_tracer.tracer_common import TraceTypes


def test_manager_separation():
    """测试FileManager和SourceManager的职责分离"""
    print("=== 测试 FileManager 和 SourceManager 职责分离 ===")

    with tempfile.TemporaryDirectory() as temp_dir:
        # 创建测试文件
        test_files = {
            "module1.py": "def func1():\n    return 'hello'\n",
            "module2.py": "class MyClass:\n    def __init__(self):\n        self.value = 42\n",
            "script.py": "#!/usr/bin/env python3\nprint('Hello, World!')\n",
        }

        file_paths = {}
        for filename, content in test_files.items():
            file_path = Path(temp_dir) / filename
            file_path.write_text(content)
            file_paths[filename] = str(file_path)

        # 测试FileManager职责
        file_manager = FileManager()

        # FileManager应该只管理文件路径到ID的映射
        file_ids = {}
        for filename, file_path in file_paths.items():
            file_id = file_manager.get_id(file_path)
            file_ids[filename] = file_id

            # 验证映射关系
            assert file_manager.get_path(file_id) == file_path
            print(f"✅ FileManager映射: {filename} -> ID {file_id}")

        # 验证FileManager不存储源代码内容（新架构）
        assert not hasattr(file_manager, "_source_content") or len(getattr(file_manager, "_source_content", {})) == 0
        print("✅ FileManager不存储源代码内容")

        # 测试SourceManager职责
        source_manager = SourceManager()

        # SourceManager应该只管理源代码内容
        for filename, file_path in file_paths.items():
            result = source_manager.load_source_file(file_path)
            assert result == True, f"SourceManager加载文件 {filename} 失败"

            # 验证源代码内容
            content = source_manager.get_source_content(file_path)
            assert content is not None, f"SourceManager未存储 {filename} 的内容"

            lines = source_manager.get_source_lines(file_path)
            assert lines is not None, f"SourceManager无法获取 {filename} 的行"
            assert len(lines) > 0, f"SourceManager获取的 {filename} 行数为0"

            print(f"✅ SourceManager存储: {filename} ({len(lines)} 行)")

        # 验证两者的独立性
        # FileManager应该不知道源代码内容
        for filename in test_files:
            file_id = file_ids[filename]
            file_path = file_paths[filename]

            # FileManager只能通过读取文件获取源代码（fallback机制）
            fm_lines = file_manager.get_source_lines(file_id)
            assert fm_lines is not None, f"FileManager无法读取 {filename}"

            # SourceManager直接从缓存获取
            sm_lines = source_manager.get_source_lines(file_path)
            assert sm_lines is not None, f"SourceManager无法获取 {filename}"

            # 内容应该一致
            assert fm_lines == sm_lines, f"FileManager和SourceManager的 {filename} 内容不一致"

        print("✅ 职责分离测试通过\n")


def test_v4_container_integration():
    """测试新架构在V4容器格式中的集成"""
    print("=== 测试 V4容器格式集成 ===")

    with tempfile.TemporaryDirectory() as temp_dir:
        container_path = Path(temp_dir) / "integration_test.bin"
        key = b"0123456789abcdef" * 2

        # 创建测试源文件
        source_files = {
            "main.py": "def main():\n    print('Hello from main')\n    return 0\n",
            "utils.py": "class Utils:\n    @staticmethod\n    def helper():\n        return 'help'\n",
        }

        file_paths = {}
        for filename, content in source_files.items():
            file_path = Path(temp_dir) / filename
            file_path.write_text(content)
            file_paths[filename] = str(file_path)

        # 写入阶段：测试FileManager和SourceManager协作
        file_manager = FileManager()
        source_manager = SourceManager()

        # 注册文件到FileManager
        file_ids = {}
        for filename, file_path in file_paths.items():
            file_id = file_manager.get_id(file_path)
            file_ids[filename] = file_id

            # 加载源代码到SourceManager
            source_manager.load_source_file(file_path)

        # 添加动态代码到FileManager
        dynamic_id = file_manager.get_id("<string>", "exec('print(\"dynamic\")')")

        # 创建容器写入器
        writer = DataContainerWriter(container_path, key, file_manager, source_manager)
        writer.open()

        # 创建测试事件
        events = [
            TraceEvent(
                event_type=EventType.CALL.value,
                timestamp=1234567890.0,
                thread_id=12345,
                frame_id=1,
                file_id=file_ids["main.py"],
                lineno=1,
                data=["main", ""],
            ),
            TraceEvent(
                event_type=EventType.LINE.value,
                timestamp=1234567890.1,
                thread_id=12345,
                frame_id=1,
                file_id=file_ids["main.py"],
                lineno=2,
                data=["print('Hello from main')", "print('Hello from main')", []],
            ),
            TraceEvent(
                event_type=EventType.CALL.value,
                timestamp=1234567890.2,
                thread_id=12345,
                frame_id=2,
                file_id=file_ids["utils.py"],
                lineno=3,
                data=["helper", ""],
            ),
            TraceEvent(
                event_type=EventType.LINE.value,
                timestamp=1234567890.3,
                thread_id=12345,
                frame_id=3,
                file_id=dynamic_id,
                lineno=1,
                data=["exec('print(\"dynamic\")')", "exec('print(\"dynamic\")')", []],
            ),
        ]

        for event in events:
            writer.add_event(event)

        writer.close()
        print(f"✅ V4容器创建成功: {container_path}")

        # 读取阶段：验证数据完整性
        reader = DataContainerReader(container_path, key)
        reader.open()

        print(f"容器格式版本: {reader._format_version}")
        assert reader._format_version == 4, "应该是V4格式"

        # 验证FileManager和SourceManager都已加载
        assert reader.file_manager is not None, "FileManager未加载"
        assert reader.source_manager is not None, "SourceManager未加载"

        print(f"FileManager文件数: {len(reader.file_manager._file_to_id)}")
        print(f"SourceManager文件数: {len(reader.source_manager._source_content)}")

        # 验证文件映射
        for filename, expected_path in file_paths.items():
            file_id = file_ids[filename]
            restored_path = reader.file_manager.get_path(file_id)
            assert restored_path == expected_path, f"文件 {filename} 路径映射错误"
            print(f"✅ 文件映射恢复: {filename}")

        # 验证源代码内容
        for filename, expected_content in source_files.items():
            file_path = file_paths[filename]

            # 从SourceManager获取源代码
            restored_lines = reader.source_manager.get_source_lines(file_path)
            assert restored_lines is not None, f"源代码 {filename} 未恢复"

            restored_content = "\n".join(restored_lines)
            expected_content_clean = expected_content.rstrip("\n")
            assert restored_content == expected_content_clean, f"源代码 {filename} 内容不匹配"
            print(f"✅ 源代码恢复: {filename} ({len(restored_lines)} 行)")

        # 验证动态代码
        dynamic_lines = reader.file_manager.get_source_lines(dynamic_id)
        assert dynamic_lines is not None, "动态代码未恢复"
        assert len(dynamic_lines) == 1, "动态代码行数错误"
        assert dynamic_lines[0] == "exec('print(\"dynamic\")')", "动态代码内容错误"
        print("✅ 动态代码恢复正确")

        # 读取事件并验证
        read_events = list(reader)
        assert len(read_events) == len(events), f"事件数量不匹配: 期望{len(events)}, 实际{len(read_events)}"

        for i, event in enumerate(read_events):
            file_path = reader.file_manager.get_path(event.file_id)
            print(f"事件 {i}: 文件={file_path}, 行号={event.lineno}")

        reader.close()
        print("✅ V4容器集成测试通过\n")


def test_tracer_integration():
    """测试新架构与TraceLogic的集成"""
    print("=== 测试 TraceLogic 集成 ===")

    with tempfile.TemporaryDirectory() as temp_dir:
        container_path = Path(temp_dir) / "tracer_integration.bin"

        # 创建测试源文件
        test_file = Path(temp_dir) / "test_script.py"
        test_content = """def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)

result = fibonacci(5)
print(f"Result: {result}")
"""
        test_file.write_text(test_content)

        # 创建启用容器的配置
        config = TraceConfig(
            enable_container=True,
            container_path=str(container_path),
            container_key="00" * 16,  # 32字符十六进制
            report_name="tracer_integration",
        )

        # 创建TraceLogic实例
        logic = TraceLogic(config)

        # 验证新架构组件已正确初始化
        assert logic._file_manager is not None, "FileManager未初始化"
        assert logic._source_manager is not None, "SourceManager未初始化"
        assert logic._container_writer is not None, "Container writer未初始化"

        print("✅ TraceLogic组件初始化成功")

        # 模拟TraceLogic的container输出
        logic.start()

        # 创建模拟log数据
        test_log_data = {
            "template": "{indent}▷ {filename}:{lineno} {line}",
            "data": {
                "original_filename": str(test_file),
                "lineno": 1,
                "frame_id": 1,
                "thread_id": 12345,
                "indent": "",
                "filename": str(test_file),
                "line": "def fibonacci(n):",
                "raw_line": "def fibonacci(n):",
                "tracked_vars": {},
                "dynamic_source": None,
            },
        }

        # 调用container输出
        logic._container_output(test_log_data, TraceTypes.COLOR_LINE)

        # 验证文件已注册到FileManager
        file_id = logic._file_manager.get_id(str(test_file))
        assert logic._file_manager.get_path(file_id) == str(test_file)
        print(f"✅ 文件已注册到FileManager: ID {file_id}")

        # 验证源代码已加载到SourceManager
        source_content = logic._source_manager.get_source_content(str(test_file))
        assert source_content is not None, "源代码未加载到SourceManager"

        source_lines = logic._source_manager.get_source_lines(str(test_file))
        assert source_lines is not None, "无法从SourceManager获取源代码行"
        assert len(source_lines) > 0, "SourceManager中源代码行数为0"
        assert source_lines[0] == "def fibonacci(n):", f"源代码第一行不匹配: {source_lines[0]}"
        print(f"✅ 源代码已加载到SourceManager: {len(source_lines)} 行")

        # 停止TraceLogic
        logic.stop()

        # 验证容器文件已创建
        assert container_path.exists(), f"容器文件未创建: {container_path}"
        print(f"✅ 容器文件已创建: {container_path}")

        # 读取并验证容器内容
        reader = DataContainerReader(container_path, config.container_key_bytes)
        reader.open()

        # 验证新架构数据已保存
        assert reader.file_manager is not None, "容器中FileManager未保存"
        assert reader.source_manager is not None, "容器中SourceManager未保存"

        # 验证文件映射
        restored_path = reader.file_manager.get_path(file_id)
        assert restored_path == str(test_file), "文件映射未正确保存"

        # 验证源代码内容
        restored_lines = reader.source_manager.get_source_lines(str(test_file))
        assert restored_lines is not None, "源代码未正确保存"
        assert len(restored_lines) == len(source_lines), "源代码行数不匹配"
        assert restored_lines[0] == source_lines[0], "源代码内容不匹配"

        reader.close()
        print("✅ TraceLogic集成测试通过\n")


def test_backward_compatibility():
    """测试向后兼容性（V3格式容器是否仍能读取）"""
    print("=== 测试 向后兼容性 ===")

    # 注意：这里我们主要测试V4格式的读取器能否正确处理没有SourceManager的情况
    # 真正的V3格式兼容性测试需要实际的V3格式文件

    with tempfile.TemporaryDirectory() as temp_dir:
        container_path = Path(temp_dir) / "compatibility_test.bin"
        key = b"0123456789abcdef" * 2

        # 创建只有FileManager的"兼容"容器
        file_manager = FileManager()
        source_manager = None  # 模拟没有SourceManager的情况

        file_id = file_manager.get_id("/path/to/legacy_file.py")

        # 创建容器（SourceManager为空）
        writer = DataContainerWriter(container_path, key, file_manager, source_manager)
        writer.open()

        # 添加一个简单事件
        event = TraceEvent(
            event_type=EventType.CALL.value,
            timestamp=1234567890.0,
            thread_id=12345,
            frame_id=1,
            file_id=file_id,
            lineno=10,
            data=["legacy_function", ""],
        )
        writer.add_event(event)
        writer.close()

        print(f"✅ 兼容容器创建成功: {container_path}")

        # 读取容器
        reader = DataContainerReader(container_path, key)
        reader.open()

        # 验证FileManager已加载
        assert reader.file_manager is not None, "FileManager未加载"

        # 验证SourceManager可能为None（兼容模式）
        print(f"SourceManager状态: {reader.source_manager is not None}")

        # 验证文件映射仍然工作
        restored_path = reader.file_manager.get_path(file_id)
        assert restored_path == "/path/to/legacy_file.py", "文件映射失败"

        # 读取事件
        events = list(reader)
        assert len(events) == 1, "事件读取失败"

        reader.close()
        print("✅ 向后兼容性测试通过\n")


if __name__ == "__main__":
    print("开始新架构综合测试...\n")

    try:
        test_manager_separation()
        test_v4_container_integration()
        test_tracer_integration()
        test_backward_compatibility()

        print("🎉 新架构所有测试通过！")

    except Exception as e:
        print(f"❌ 新架构测试失败: {e}")
        import traceback

        traceback.print_exc()
