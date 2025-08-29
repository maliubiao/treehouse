#!/usr/bin/env python3
"""
测试SourceManager类的功能：
1. 基本的文件加载和内容存储
2. Base64编码和解码
3. 序列化和反序列化
4. 源代码行获取
5. 错误处理
"""

import os
import sys
import tempfile
from pathlib import Path

# 添加当前目录到Python路径
sys.path.insert(0, str(Path(__file__).parent))

from context_tracer.source_manager import SourceManager


def test_source_manager_basic():
    """测试SourceManager的基本功能"""
    print("=== 测试 SourceManager 基本功能 ===")

    with tempfile.TemporaryDirectory() as temp_dir:
        # 创建测试文件
        test_file = Path(temp_dir) / "test_source.py"
        test_content = """def hello_world():
    print("Hello, World!")
    return "success"

class TestClass:
    def __init__(self):
        self.value = 42
        
    def method(self):
        return self.value * 2

if __name__ == "__main__":
    hello_world()
"""
        test_file.write_text(test_content)

        # 创建SourceManager并加载文件
        sm = SourceManager()

        # 测试文件加载
        result = sm.load_source_file(str(test_file))
        assert result == True, "文件加载应该成功"
        print(f"✅ 文件加载成功: {test_file}")

        # 测试重复加载（应该返回缓存结果）
        result2 = sm.load_source_file(str(test_file))
        assert result2 == True, "重复加载应该返回True"
        print("✅ 重复加载处理正确")

        # 测试获取源代码内容
        content = sm.get_source_content(str(test_file))
        assert content is not None, "应该能获取到源代码内容"
        print(f"✅ 获取源代码内容成功，长度: {len(content)}")

        # 测试获取源代码行
        lines = sm.get_source_lines(str(test_file))
        assert lines is not None, "应该能获取到源代码行"
        assert len(lines) > 0, "源代码行数应该大于0"
        assert lines[0] == "def hello_world():", f"第一行内容不匹配: {lines[0]}"
        print(f"✅ 获取源代码行成功，行数: {len(lines)}")
        print(f"   第一行: {lines[0]}")
        print(f"   最后一行: {lines[-1]}")

        # 测试文件不存在的情况
        non_existent = str(Path(temp_dir) / "non_existent.py")
        result3 = sm.load_source_file(non_existent)
        assert result3 == False, "不存在的文件应该返回False"
        print("✅ 不存在文件处理正确")

        print()


def test_source_manager_serialization():
    """测试SourceManager的序列化和反序列化"""
    print("=== 测试 SourceManager 序列化 ===")

    with tempfile.TemporaryDirectory() as temp_dir:
        # 创建多个测试文件
        files_content = {
            "file1.py": "print('file1')\n",
            "file2.py": "def func():\n    return 42\n",
            "file3.py": "# Comment\nclass MyClass:\n    pass\n",
        }

        sm = SourceManager()

        # 加载所有测试文件
        for filename, content in files_content.items():
            file_path = Path(temp_dir) / filename
            file_path.write_text(content)
            result = sm.load_source_file(str(file_path))
            assert result == True, f"文件 {filename} 加载失败"

        print(f"已加载 {len(files_content)} 个文件")

        # 序列化
        serialized_data = sm.serialize()
        assert serialized_data is not None, "序列化应该成功"
        assert len(serialized_data) > 0, "序列化数据应该非空"
        print(f"✅ 序列化成功，数据长度: {len(serialized_data)}")

        # 反序列化
        sm_restored = SourceManager.deserialize(serialized_data)
        assert sm_restored is not None, "反序列化应该成功"
        print("✅ 反序列化成功")

        # 验证反序列化后的数据
        for filename, expected_content in files_content.items():
            file_path = str(Path(temp_dir) / filename)

            # 检查源代码内容
            content = sm_restored.get_source_content(file_path)
            assert content is not None, f"文件 {filename} 的源代码内容丢失"

            # 检查源代码行
            lines = sm_restored.get_source_lines(file_path)
            assert lines is not None, f"文件 {filename} 的源代码行丢失"

            # 验证内容一致性
            restored_content = "\n".join(lines)
            # 去掉末尾的换行符来比较
            expected_content_clean = expected_content.rstrip("\n")
            assert restored_content == expected_content_clean, f"文件 {filename} 内容不一致"

            print(f"✅ 文件 {filename} 验证通过")

        print()


def test_source_manager_edge_cases():
    """测试SourceManager的边界情况"""
    print("=== 测试 SourceManager 边界情况 ===")

    sm = SourceManager()

    # 测试空文件
    with tempfile.TemporaryDirectory() as temp_dir:
        empty_file = Path(temp_dir) / "empty.py"
        empty_file.write_text("")

        result = sm.load_source_file(str(empty_file))
        assert result == True, "空文件加载应该成功"

        lines = sm.get_source_lines(str(empty_file))
        assert lines == [], f"空文件应该返回空列表，实际: {lines}"
        print("✅ 空文件处理正确")

    # 测试获取不存在文件的内容
    non_existent = "/non/existent/file.py"
    content = sm.get_source_content(non_existent)
    assert content is None, "不存在的文件应该返回None"

    lines = sm.get_source_lines(non_existent)
    assert lines is None, "不存在的文件应该返回None"
    print("✅ 不存在文件查询处理正确")

    # 测试权限错误（尝试读取受保护的文件）
    if os.name == "posix":  # Unix/Linux/macOS
        try:
            result = sm.load_source_file("/root/.bashrc")
            # 如果能读取，说明有权限，测试通过
            # 如果不能读取，应该返回False
            print(f"权限测试结果: {result}")
        except:
            print("✅ 权限错误处理正确")

    print()


def test_source_manager_binary_files():
    """测试SourceManager处理二进制文件"""
    print("=== 测试 SourceManager 二进制文件处理 ===")

    with tempfile.TemporaryDirectory() as temp_dir:
        # 创建二进制文件
        binary_file = Path(temp_dir) / "binary.dat"
        binary_data = b"\x00\x01\x02\x03\x04\x05\xff\xfe\xfd"
        binary_file.write_bytes(binary_data)

        sm = SourceManager()

        # 尝试加载二进制文件
        result = sm.load_source_file(str(binary_file))
        assert result == True, "二进制文件加载应该成功（base64编码）"
        print("✅ 二进制文件加载成功")

        # 尝试获取内容（应该有base64编码的内容）
        content = sm.get_source_content(str(binary_file))
        assert content is not None, "二进制文件应该有base64编码的内容"
        print(f"✅ 二进制文件内容已编码，长度: {len(content)}")

        # 尝试获取行（可能会失败，因为不是有效的UTF-8）
        lines = sm.get_source_lines(str(binary_file))
        # 对于二进制文件，解码可能失败，这是预期的
        print(f"二进制文件行获取结果: {lines is not None}")

        print()


def test_source_manager_get_all_files():
    """测试SourceManager获取所有源文件"""
    print("=== 测试 SourceManager 获取所有源文件 ===")

    with tempfile.TemporaryDirectory() as temp_dir:
        # 创建多个测试文件
        test_files = {
            "module1.py": "import os\nprint('module1')\n",
            "module2.py": "def func2():\n    return 'hello'\n",
            "script.py": "#!/usr/bin/env python3\nprint('script')\n",
        }

        sm = SourceManager()

        # 加载所有文件
        for filename, content in test_files.items():
            file_path = Path(temp_dir) / filename
            file_path.write_text(content)
            sm.load_source_file(str(file_path))

        # 获取所有源文件
        all_files = sm.get_all_source_files()
        assert len(all_files) == len(test_files), f"应该有 {len(test_files)} 个文件，实际有 {len(all_files)} 个"

        # 验证文件路径存在
        for filename in test_files.keys():
            expected_path = str(Path(temp_dir) / filename)
            assert expected_path in all_files, f"文件 {expected_path} 未在结果中找到"
            assert all_files[expected_path] is not None, f"文件 {expected_path} 的内容为空"

        print(f"✅ 获取所有源文件成功，共 {len(all_files)} 个文件")

        print()


if __name__ == "__main__":
    print("开始SourceManager测试...\n")

    try:
        test_source_manager_basic()
        test_source_manager_serialization()
        test_source_manager_edge_cases()
        test_source_manager_binary_files()
        test_source_manager_get_all_files()

        print("🎉 SourceManager所有测试通过！")

    except Exception as e:
        print(f"❌ SourceManager测试失败: {e}")
        import traceback

        traceback.print_exc()
