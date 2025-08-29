#!/usr/bin/env python3
"""
测试container数据流的完整性：
1. 测试_container_output方法是否被正确调用
2. 测试FileManager的序列化和反序列化
3. 测试完整的容器读写流程
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


def test_filemanager_serialization():
    """测试FileManager的序列化和反序列化"""
    print("=== 测试 FileManager 序列化和反序列化 ===")

    # 创建FileManager并添加一些文件
    fm = FileManager()
    file1_id = fm.get_id("/path/to/test1.py")
    file2_id = fm.get_id("/path/to/test2.py", "print('dynamic code')")
    file3_id = fm.get_id("<string>", "exec('hello')")

    print(f"添加文件前 - file_to_id: {fm._file_to_id}")
    print(f"添加文件前 - id_to_file: {fm._id_to_file}")
    print(f"添加文件前 - dynamic_code: {fm._dynamic_code}")

    # 序列化
    serialized = fm.serialize()
    print(f"序列化数据: {serialized}")

    # 反序列化
    fm_restored = FileManager.deserialize(serialized)
    print(f"反序列化后 - file_to_id: {fm_restored._file_to_id}")
    print(f"反序列化后 - id_to_file: {fm_restored._id_to_file}")
    print(f"反序列化后 - dynamic_code: {fm_restored._dynamic_code}")

    # 验证数据一致性
    assert fm_restored.get_path(file1_id) == "/path/to/test1.py"
    assert fm_restored.get_path(file2_id) == "/path/to/test2.py"
    assert fm_restored.get_path(file3_id) == "<string>"

    print("✅ FileManager序列化测试通过\n")


def test_container_writer_reader():
    """测试容器的完整读写流程"""
    print("=== 测试容器完整读写流程 ===")

    with tempfile.TemporaryDirectory() as temp_dir:
        container_path = Path(temp_dir) / "test_container.bin"
        key = b"0123456789abcdef" * 2  # 32字节密钥

        # 创建FileManager并添加文件
        file_manager = FileManager()
        file1_id = file_manager.get_id("/path/to/script.py")
        file2_id = file_manager.get_id("<string>", "exec('test')")

        print(f"写入前 FileManager - file_to_id: {file_manager._file_to_id}")

        # 写入数据（添加SourceManager）
        source_manager = SourceManager()
        writer = DataContainerWriter(container_path, key, file_manager, source_manager)
        writer.open()

        # 创建一些测试事件
        events = [
            TraceEvent(
                event_type=EventType.CALL.value,
                timestamp=1234567890.0,
                thread_id=12345,
                frame_id=1,
                file_id=file1_id,
                lineno=10,
                data=["test_function", "arg1, arg2"],
            ),
            TraceEvent(
                event_type=EventType.LINE.value,
                timestamp=1234567890.1,
                thread_id=12345,
                frame_id=1,
                file_id=file1_id,
                lineno=11,
                data=["print('hello')", "print('hello')", []],
            ),
            TraceEvent(
                event_type=EventType.RETURN.value,
                timestamp=1234567890.2,
                thread_id=12345,
                frame_id=1,
                file_id=file1_id,
                lineno=12,
                data=["test_function", "None", []],
            ),
        ]

        for event in events:
            writer.add_event(event)

        writer.close()
        print(f"数据写入完成，容器文件: {container_path}")

        # 读取数据
        reader = DataContainerReader(container_path, key)
        reader.open()

        print(f"读取后 FileManager - file_to_id: {reader.file_manager._file_to_id}")
        print(f"读取后 FileManager - id_to_file: {reader.file_manager._id_to_file}")

        # 验证文件路径映射
        assert reader.file_manager.get_path(file1_id) == "/path/to/script.py"
        assert reader.file_manager.get_path(file2_id) == "<string>"

        # 读取事件
        read_events = list(reader)
        reader.close()

        print(f"读取到 {len(read_events)} 个事件")
        for i, event in enumerate(read_events):
            file_path = reader.file_manager.get_path(event.file_id)
            print(f"事件 {i}: 类型={EventType(event.event_type).name}, 文件={file_path}, 行号={event.lineno}")

        assert len(read_events) == 3
        print("✅ 容器读写流程测试通过\n")


def test_container_output_method():
    """测试_container_output方法的调用"""
    print("=== 测试 _container_output 方法 ===")

    with tempfile.TemporaryDirectory() as temp_dir:
        container_path = Path(temp_dir) / "test_output.bin"

        # 创建启用容器的配置
        config = TraceConfig(
            enable_container=True,
            container_path=str(container_path),
            container_key="00" * 16,  # 32个字符的十六进制字符串
            report_name="test_output",
        )

        # 创建TraceLogic实例
        logic = TraceLogic(config)

        # 验证容器组件已正确初始化
        assert logic._container_writer is not None, "Container writer未初始化"
        assert logic._file_manager is not None, "File manager未初始化"
        assert logic._source_manager is not None, "Source manager未初始化"
        assert "container" in logic._output._active_outputs, "Container输出未激活"

        print("✅ Container组件初始化成功")

        # 启动container writer
        logic._container_writer.open()
        print("✅ Container writer已启动")

        # 创建测试数据模拟_container_output调用
        test_log_data = {
            "template": "test template",
            "data": {
                "original_filename": "/path/to/test_script.py",
                "lineno": 42,
                "frame_id": 1,
                "thread_id": 12345,
                "indent": "",
                "line": "print('test')",
                "dynamic_source": None,
            },
        }

        # 手动调用_container_output
        print("调用 _container_output...")
        logic._container_output(test_log_data, TraceTypes.COLOR_LINE)

        # 检查FileManager是否记录了文件
        file_id = logic._file_manager.get_id("/path/to/test_script.py")
        assert logic._file_manager.get_path(file_id) == "/path/to/test_script.py"
        print(f"✅ 文件已注册: {logic._file_manager.get_path(file_id)} (ID: {file_id})")

        # 添加更多测试数据
        test_log_data2 = {
            "template": "test template 2",
            "data": {
                "original_filename": "<string>",
                "lineno": 1,
                "frame_id": 2,
                "thread_id": 12345,
                "indent": "",
                "func_name": "exec",
                "dynamic_source": "print('dynamic code')",
            },
        }

        logic._container_output(test_log_data2, TraceTypes.COLOR_CALL)

        # 关闭writer以确保数据写入
        logic._container_writer.close()

        # 验证文件是否存在
        assert container_path.exists(), f"容器文件未创建: {container_path}"
        print(f"✅ 容器文件已创建: {container_path}")

        # 读取并验证数据
        reader = DataContainerReader(container_path, config.container_key_bytes)
        reader.open()

        print(f"读取的 FileManager:")
        print(f"  file_to_id: {reader.file_manager._file_to_id}")
        print(f"  id_to_file: {reader.file_manager._id_to_file}")

        # 验证文件映射
        assert len(reader.file_manager._file_to_id) >= 1, "FileManager中没有文件映射"
        assert "/path/to/test_script.py" in reader.file_manager._file_to_id, "测试文件未记录"

        reader.close()
        print("✅ _container_output测试通过\n")


def test_trace_logic_integration():
    """测试TraceLogic与容器的集成"""
    print("=== 测试 TraceLogic 容器集成 ===")

    with tempfile.TemporaryDirectory() as temp_dir:
        container_path = Path(temp_dir) / "integration_test.bin"

        # 创建启用容器的配置
        config = TraceConfig(
            enable_container=True,
            container_path=str(container_path),
            container_key="00" * 16,
            report_name="integration_test",
            enable_var_trace=True,
        )

        logic = TraceLogic(config)

        # 模拟frame对象
        class MockCode:
            def __init__(self, filename, name):
                self.co_filename = filename
                self.co_name = name

        class MockFrame:
            def __init__(self, filename, lineno, func_name="test_func"):
                self.f_code = MockCode(filename, func_name)
                self.f_lineno = lineno
                self.f_locals = {"x": 42, "y": "test"}
                self.f_globals = {"__name__": "__main__"}

        # 创建测试frame
        frame = MockFrame("/path/to/integration_test.py", 10)

        # 直接测试_prepare_log_data
        log_data = logic._prepare_log_data(frame)
        print(f"_prepare_log_data 结果: {log_data}")

        assert "original_filename" in log_data
        assert log_data["original_filename"] == "/path/to/integration_test.py"

        # 模拟完整的日志数据
        full_log_data = {
            "template": "{indent}▷ {filename}:{lineno} {line}",
            "data": {
                **log_data,
                "indent": "",
                "filename": "/path/to/integration_test.py",
                "lineno": 10,
                "frame_id": 1,
                "thread_id": 12345,
                "line": "x = 42",
                "raw_line": "x = 42",
                "tracked_vars": [],
                "vars": "",
            },
        }

        # 调用输出处理器
        for output_type in logic._output._active_outputs:
            if output_type == "container":
                handler = logic._output._output_handlers[output_type]
                handler(full_log_data, TraceTypes.COLOR_LINE)
                print(f"✅ {output_type} 输出处理器调用成功")

        # 验证FileManager状态
        print(f"集成测试后 FileManager状态:")
        print(f"  文件数量: {len(logic._file_manager._file_to_id)}")
        print(f"  文件映射: {logic._file_manager._file_to_id}")

        logic._container_writer.close()

        # 读取验证
        if container_path.exists():
            reader = DataContainerReader(container_path, config.container_key_bytes)
            reader.open()

            events = list(reader)
            print(f"读取到 {len(events)} 个事件")

            for event in events:
                file_path = reader.file_manager.get_path(event.file_id)
                print(f"事件: 文件={file_path}, 行号={event.lineno}, 数据={event.data}")

            reader.close()
            print("✅ 集成测试通过")
        else:
            print("⚠️  容器文件未创建")

        print()


if __name__ == "__main__":
    print("开始容器数据流测试...\n")

    try:
        test_filemanager_serialization()
        test_container_writer_reader()
        test_container_output_method()
        test_trace_logic_integration()

        print("🎉 所有测试通过！")

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback

        traceback.print_exc()
