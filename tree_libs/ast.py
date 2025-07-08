import importlib
from abc import ABC
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

if TYPE_CHECKING:
    from tree import SymbolTrie
import re
import zlib
from abc import abstractmethod

from tree_sitter import Language, Node, Parser, Query

# 定义语言名称常量
C_LANG = "c"
PYTHON_LANG = "python"
JAVASCRIPT_LANG = "javascript"
TYPESCRIPT_LANG = "typescript"
TYPESCRIPT_TSX_LANG = "typescript_tsx"
JAVA_LANG = "java"
GO_LANG = "go"
SHELL_LANG = "bash"
CPP_LANG = "cpp"

# 文件后缀到语言名称的映射
SUPPORTED_LANGUAGES = {
    ".c": C_LANG,
    ".h": C_LANG,
    ".py": PYTHON_LANG,
    ".js": JAVASCRIPT_LANG,
    ".ts": TYPESCRIPT_LANG,
    ".tsx": TYPESCRIPT_TSX_LANG,
    ".java": JAVA_LANG,
    ".go": GO_LANG,
    ".sh": SHELL_LANG,
    ".cpp": CPP_LANG,
    ".cc": CPP_LANG,
    ".cxx": CPP_LANG,
}

# 各语言的查询语句映射
LANGUAGE_QUERIES = {}


# 定义Tree-sitter节点类型常量
class NodeTypes:
    MODULE = "module"
    TRANSLATION_UNIT = "translation_unit"
    COMPOUND_STATEMENT = "compound_statement"
    CLASS_DEFINITION = "class_definition"
    FUNCTION_DEFINITION = "function_definition"
    DECORATED_DEFINITION = "decorated_definition"
    EXPRESSION_STATEMENT = "expression_statement"
    IMPORT_STATEMENT = "import_statement"
    IMPORT_FROM_STATEMENT = "import_from_statement"
    C_DEFINE = "preproc_def"
    C_INCLUDE = "preproc_include"
    C_DECLARATION = "declaration"
    GO_SOURCE_FILE = "source_file"
    GO_IMPORT_DECLARATION = "import_declaration"
    GO_CONST_DECLARATION = "const_declaration"
    GO_VAR_DECLARATION = "var_declaration"
    GO_TYPE_DECLARATION = "type_declaration"
    GO_FUNC_DECLARATION = "function_declaration"
    GO_METHOD_DECLARATION = "method_declaration"
    GO_PACKAGE_CLAUSE = "package_clause"
    GO_FIELD_IDENTIFIER = "field_identifier"
    GO_PARAMETER_LIST = "parameter_list"
    GO_TYPE_IDENTIFIER = "type_identifier"
    GO_PARAMETER_DECLARATION = "parameter_declaration"
    COMMENT = "comment"
    BLOCK = "block"
    BODY = "body"
    STRING = "string"
    IDENTIFIER = "identifier"
    ASSIGNMENT = "assignment"
    IF_STATEMENT = "if_statement"
    CALL = "call"
    ATTRIBUTE = "attribute"
    NAME = "name"
    WORD = "word"
    C_POINTER_DECLARATOR = "pointer_declarator"
    FUNCTION_DECLARATOR = "function_declarator"
    COMPARISON_OPERATOR = "comparison_operator"
    TYPED_PARAMETER = "typed_parameter"
    TYPED_DEFAULT_PARAMETER = "typed_default_parameter"
    GENERIC_TYPE = "generic_type"
    UNION_TYPE = "union_type"
    GO_IMPORT_SPEC = "import_spec"
    GO_IMPORT_SPEC_LIST = "import_spec_list"
    GO_PACKAGE_IDENTIFIER = "package_identifier"
    GO_INTERPRETED_STRING_LITERAL = "interpreted_string_literal"
    GO_BLANK_IDENTIFIER = "blank_identifier"
    GO_TYPE_SPEC = "type_spec"
    GO_POINTER_TYPE = "pointer_type"
    GO_QUALIFIED_TYPE = "qualified_type"
    CPP_NAMESPACE = "namespace"
    CPP_NAMESPACE_IDENTIFIER = "namespace_identifier"
    CPP_NAMESPACE_DEFINITION = "namespace_definition"
    CPP_CLASS_SPECIFIER = "class_specifier"
    CPP_TEMPLATE_DECLARATION = "template_declaration"
    CPP_ACCESS_SPECIFIER = "access_specifier"
    CPP_FIELD_IDENTIFIER = "field_identifier"
    CPP_FIELD_DEFINITION = "field_definition"
    CPP_INIT_DECLARATOR = "init_declarator"
    CPP_QUALIFIED_IDENTIFIER = "qualified_identifier"
    CPP_REFERENCE_DECLARATOR = "reference_declarator"
    CPP_OPERATOR_NAME = "operator_name"
    C_STRUCT_SPECFIER = "struct_specifier"
    C_TYPE_IDENTIFIER = "type_identifier"
    CPP_FRIEND_DECLARATION = "friend_declaration"
    C_ATTRIBUTE_DECLARATION = "attribute_declaration"
    C_ARRAY_DECLARATOR = "array_declarator"
    JS_FUNCTION_DECLARATION = "function_declaration"
    JS_CLASS_DECLARATION = "class_declaration"
    JS_FUNCTION_EXPRESSION = "function_expression"
    JS_LEXICAL_DECLARATION = "lexical_declaration"
    JS_VARIABLE_DECLARATION = "variable_declaration"
    JS_VARIABLE_DECLARATOR = "variable_declarator"
    JS_ARROW_FUNCTION = "arrow_function"
    JS_GENERATOR_FUNCTION_DECLARATION = "generator_function_declaration"
    JS_METHOD_DEFINITION = "method_definition"
    JS_PROPERTY_IDENTIFIER = "property_identifier"
    JS_OBJECT = "object"
    JS_PROGRAM = "program"
    TS_TYPE_ALIAS_DECLARATION = "type_alias_declaration"
    TS_INTERFACE_DECLARATION = "interface_declaration"
    TS_ENUM_DECLARATION = "enum_declaration"
    TS_MODULE_DECLARATION = "module_declaration"
    TS_DECLARE_FUNCTION = "declare_function"
    TS_ABSTRACT_CLASS_DECLARATION = "abstract_class_declaration"
    TS_ABSTRACT_METHOD_SIGNATURE = "abstract_method_signature"
    TS_PUBLIC_FIELD_DEFINITION = "public_field_definition"
    TS_ACCESSIBILITY_MODIFIER = "accessibility_modifier"
    TS_TYPE_ANNOTATION = "type_annotation"
    TS_PREDEFINED_TYPE = "predefined_type"
    TS_UNION_TYPE = "union_type"
    TS_LITERAL_TYPE = "literal_type"
    TS_OPTIONAL_CHAIN = "optional_chain"
    TS_AS_EXPRESSION = "as_expression"
    TS_SATISFIES_EXPRESSION = "satisfies_expression"
    TS_TYPE_IDENTIFIER = "type_identifier"
    TS_NAMESPACE = "internal_module"
    TS_EXPORT_STATEMENT = "export_statement"

    @staticmethod
    def is_module(node_type):
        return node_type in (
            NodeTypes.MODULE,
            NodeTypes.TRANSLATION_UNIT,
            NodeTypes.GO_SOURCE_FILE,
            NodeTypes.JS_PROGRAM,
            NodeTypes.TS_MODULE_DECLARATION,
        )

    @staticmethod
    def is_import(node_type):
        return node_type in (
            NodeTypes.IMPORT_STATEMENT,
            NodeTypes.IMPORT_FROM_STATEMENT,
            NodeTypes.GO_IMPORT_DECLARATION,
        )

    @staticmethod
    def is_structure_tree_node(node_type):
        return node_type in (
            NodeTypes.C_STRUCT_SPECFIER,
            NodeTypes.CPP_CLASS_SPECIFIER,
            NodeTypes.CPP_TEMPLATE_DECLARATION,
            NodeTypes.CPP_NAMESPACE_DEFINITION,
            NodeTypes.CLASS_DEFINITION,
            NodeTypes.FUNCTION_DEFINITION,
            NodeTypes.DECORATED_DEFINITION,
            NodeTypes.GO_FUNC_DECLARATION,
            NodeTypes.GO_METHOD_DECLARATION,
            NodeTypes.GO_TYPE_DECLARATION,
            NodeTypes.TS_TYPE_ALIAS_DECLARATION,
            NodeTypes.TS_INTERFACE_DECLARATION,
            NodeTypes.TS_ENUM_DECLARATION,
            NodeTypes.TS_ABSTRACT_CLASS_DECLARATION,
        )

    @staticmethod
    def is_statement(node_type):
        return node_type in (
            NodeTypes.EXPRESSION_STATEMENT,
            NodeTypes.IF_STATEMENT,
            NodeTypes.CALL,
            NodeTypes.ASSIGNMENT,
            NodeTypes.TS_AS_EXPRESSION,
            NodeTypes.TS_SATISFIES_EXPRESSION,
        )

    @staticmethod
    def is_identifier(node_type):
        return node_type in (
            NodeTypes.IDENTIFIER,
            NodeTypes.NAME,
            NodeTypes.WORD,
            NodeTypes.GO_PACKAGE_IDENTIFIER,
            NodeTypes.GO_BLANK_IDENTIFIER,
            NodeTypes.GO_TYPE_IDENTIFIER,
            NodeTypes.TS_TYPE_ANNOTATION,
        )

    @staticmethod
    def is_type(node_type):
        return node_type in (
            NodeTypes.TYPED_PARAMETER,
            NodeTypes.TYPED_DEFAULT_PARAMETER,
            NodeTypes.GENERIC_TYPE,
            NodeTypes.UNION_TYPE,
            NodeTypes.TS_UNION_TYPE,
            NodeTypes.TS_LITERAL_TYPE,
            NodeTypes.TS_PREDEFINED_TYPE,
        )


class ParserLoader:
    def __init__(self):
        self._parsers = {}
        self._languages = {}
        self._queries = {}
        self.lang = None

    def _get_language(self, lang_name: str):
        """动态加载对应语言的 Tree-sitter 模块"""
        if lang_name in self._languages:
            return self._languages[lang_name]

        module_name = f"tree_sitter_{lang_name}"
        if lang_name == TYPESCRIPT_LANG:
            module = importlib.import_module("tree_sitter_typescript")
            return getattr(module, "language_typescript")
        elif lang_name == TYPESCRIPT_TSX_LANG:
            module = importlib.import_module("tree_sitter_typescript")
            return getattr(module, "language_tsx")
        else:
            try:
                lang_module = importlib.import_module(module_name)
            except ImportError as exc:
                raise ImportError(
                    f"Language parser for '{lang_name}' not installed. Try: pip install {module_name.replace('_', '-')}"
                ) from exc
            return lang_module.language

    def get_parser(self, file_path: str) -> tuple[Parser, Query, str]:
        """根据文件路径获取对应的解析器和查询对象"""
        suffix = Path(file_path).suffix.lower()
        lang_name = SUPPORTED_LANGUAGES.get(suffix)
        if not lang_name:
            raise ValueError(f"不支持的文件类型: {suffix}")

        if lang_name in self._parsers:
            return self._parsers[lang_name], None, lang_name
        self.lang = lang_name

        language = self._get_language(lang_name)
        lang = Language(language())
        lang_parser = Parser(lang)

        # 根据语言类型获取对应的查询语句
        query_source = LANGUAGE_QUERIES.get(lang_name)
        if query_source:
            query = Query(lang, query_source)
            self._queries[lang_name] = query
        else:
            query = None
        self._parsers[lang_name] = lang_parser
        return lang_parser, query, lang_name


def calculate_crc32_hash(text: str) -> int:
    """计算字符串的CRC32哈希值"""
    return zlib.crc32(text.encode("utf-8"))


class ParserUtil:
    def __init__(self, parser_loader: ParserLoader):
        """初始化解析器工具类"""
        self.parser_loader = parser_loader
        self.node_processor = NodeProcessor()
        self.code_map_builder = CodeMapBuilder(None, self.node_processor, lang=parser_loader.lang)
        self._source_code = None

    def prepare_root_node(self, file_path: str):
        """获取文件的根节点"""
        parser, _, lang_name = self.parser_loader.get_parser(file_path)
        self.node_processor.lang_spec = find_spec_for_lang(lang_name)
        self.code_map_builder.lang = lang_name
        with open(file_path, "rb") as f:
            source_code = f.read()
        self._source_code = source_code
        tree = parser.parse(source_code)
        root_node = tree.root_node
        self.code_map_builder.root_node = root_node
        return root_node

    def get_symbol_paths(self, file_path: str, debug: bool = False):
        """解析代码文件并返回所有符号路径及对应代码和位置信息"""
        root_node = self.prepare_root_node(file_path)
        results = []
        code_map = {}
        if is_node_module(root_node.type) and len(root_node.children) != 0:
            self.code_map_builder.process_import_block(root_node, code_map, self._source_code, results)
        self.code_map_builder.traverse(root_node, [], [], code_map, self._source_code, results)
        return results, code_map

    def update_symbol_trie(self, file_path: str, symbol_trie: "SymbolTrie"):
        """更新符号前缀树，将文件中的所有符号插入到前缀树中"""
        paths, code_map = self.get_symbol_paths(file_path)
        for path in paths:
            info = code_map[path]
            symbol_info = self.code_map_builder.build_symbol_info(info, file_path)
            symbol_trie.insert(path, symbol_info)

    def find_symbols_by_location(self, code_map: dict, line: int, column: int) -> list[dict]:
        """根据行列位置查找对应的符号信息列表，按嵌套层次排序（最内层在前）"""
        return self.code_map_builder.find_symbols_by_location(code_map, line, column)

    def find_symbols_for_locations(
        self,
        code_map: dict,
        locations: list[tuple[int, int]],
        max_context_size: int = 16 * 1024,
        include_class_context: bool = True,
    ) -> dict[str, dict]:
        """批量处理位置并返回符号名到符号信息的映射"""
        return self.code_map_builder.find_symbols_for_locations(
            code_map,
            locations,
            max_context_size=max_context_size,
            include_class_context=include_class_context,
        )

    def symbol_at_line(self, line: int) -> dict:
        return self.code_map_builder.build_symbol_info_at_line(line)

    def near_symbol_at_line(self, line: int) -> dict:
        return self.code_map_builder.build_near_symbol_info_at_line(line)

    def lookup_symbols(self, file_path: str, symbols: list[str]):
        """根据文件路径列表查找符号"""
        _, code_map = self.get_symbol_paths(file_path)
        m = {}
        n = {}
        for path in symbols:
            path_backup = path
            symbol_info = code_map.get(path, None)
            if symbol_info:
                m[path] = code_map[path]
                m[path]["block_content"] = m[path]["code"].encode("utf-8")
                continue
            for _ in range(path.count(".")):
                path = path[: path.rfind(".")]
                symbol_info = code_map.get(path, None)
                symbol_info["block_content"] = symbol_info["code"].encode("utf-8")
                if symbol_info:
                    n[path_backup] = (path, symbol_info)
                    break
            if not symbol_info:
                # 使用整个文件作为符号信息
                with open(file_path, "rb") as f:
                    file_bytes = f.read()
                file_size = len(file_bytes)
                symbol_info = {
                    "block_content": file_bytes,
                    "block_range": (0, file_size),
                    "start_line": 0,
                    "file_path": file_path,
                }
                n[path_backup] = ("module", symbol_info)
        return m, n

    def print_symbol_paths(self, file_path: str):
        """打印文件中的所有符号路径及对应代码和位置信息"""
        paths, code_map = self.get_symbol_paths(file_path)
        for path in paths:
            info = code_map[path]
            print(
                f"{path}:\n"
                f"代码位置: 第{info['start_line'] + 1}行{info['start_col'] + 1}列 "
                f"到 第{info['end_line'] + 1}行{info['end_col'] + 1}列\n"
                f"调用列表: {[call['name'] for call in info['calls']]}\n"
                f"代码内容:\n{info['code']}\n"
            )


class BaseNodeProcessor(ABC):
    """抽象基类，包含通用节点处理方法"""

    @staticmethod
    def find_child_by_type(node, target_type):
        """在节点子节点中查找指定类型的节点"""
        for child in node.children:
            if child.type == target_type:
                return child
        return None

    @staticmethod
    def find_child_by_field(node, field_name):
        """根据字段名查找子节点"""
        for child in node.children:
            if child.type == field_name:
                return child
        return None

    @staticmethod
    def find_identifier_in_node(node):
        """在节点中查找identifier节点"""
        for child in node.children:
            if child.type == NodeTypes.IDENTIFIER:
                return child.text.decode("utf8")
        return None

    @staticmethod
    def get_full_attribute_name(node):
        """递归获取属性调用的完整名称"""
        if node.type == NodeTypes.IDENTIFIER:
            return node.text.decode("utf8")
        if node.type == NodeTypes.ATTRIBUTE:
            obj_part = BaseNodeProcessor.get_full_attribute_name(node.child_by_field_name("object"))
            attr_part = node.child_by_field_name("attribute").text.decode("utf8")
            return f"{obj_part}.{attr_part}"
        return ""

    @staticmethod
    def get_function_name_from_call(function_node):
        """从函数调用节点中提取函数名"""
        if function_node.type == NodeTypes.IDENTIFIER:
            return function_node.text.decode("utf8")
        if function_node.type == NodeTypes.ATTRIBUTE:
            return BaseNodeProcessor.get_full_attribute_name(function_node)
        return None

    @staticmethod
    def is_standard_type(type_name: str) -> bool:
        """判断是否是标准库类型或基本类型"""
        basic_types = {
            "typing",
            "int",
            "str",
            "float",
            "bool",
            "list",
            "dict",
            "tuple",
            "set",
            "None",
            "Any",
            "Optional",
            "Union",
            "List",
            "Dict",
            "Tuple",
            "Set",
            "Type",
            "Callable",
            "Iterable",
            "Sequence",
            "Mapping",
            "TypeVar",
            "Generic",
            "Protocol",
            "runtime_checkable",
        }

        if "." in type_name:
            module_part, *rest = type_name.split(".", 1)
            if module_part == "typing":
                try:
                    return getattr(typing, rest[0].split(".", 1)[0]) is not None
                except AttributeError:
                    return False
            return module_part in {"typing", "collections", "abc"}
        return type_name in basic_types


def unnamed_symbol_at_line(line_number: int) -> str:
    """生成无名符号的名称"""
    return f"at_{line_number}"


def near_symbol_at_line(line_number: int) -> str:
    """生成无名符号的名称"""
    return f"near_{line_number}"


def line_number_from_unnamed_symbol(symbol: str) -> int:
    """从无名符号名称中提取行号"""
    matcher = re.match(r"(?:near|at)_(\d+)", symbol)
    if matcher:
        return int(matcher.group(1))
    return -1


def find_spec_for_lang(lang: str) -> "LangSpec":
    """根据语言名称查找对应的语言特定处理策略"""
    if lang == PYTHON_LANG:
        return PythonSpec()
    elif lang == JAVASCRIPT_LANG:
        return JavascriptSpec()
    elif lang == TYPESCRIPT_LANG or lang == TYPESCRIPT_TSX_LANG:
        return TypeScriptSpec()
    # elif lang == JAVASCRIPT_LANG:
    #     return JavaScriptSpec()
    # elif lang == JAVA_LANG:
    #     return JavaSpec()
    if lang == GO_LANG:
        return GoLangSpec()
    if lang in (CPP_LANG, C_LANG):
        return CPPSpec()
    return None


class LangSpec(ABC):
    """语言特定处理策略接口"""

    @abstractmethod
    def get_symbol_name(self, node: Node) -> str:
        """提取节点的符号名称"""
        raise NotImplementedError("Subclasses must implement get_symbol_name")

    @abstractmethod
    def get_function_name(self, node: Node) -> str:
        raise NotImplementedError("Subclasses must implement get_function_name")


class JavascriptSpec(LangSpec):
    """JavaScript语言特定处理策略"""

    def get_symbol_name(self, node: Node) -> str:
        if node.type == NodeTypes.JS_CLASS_DECLARATION:
            class_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.IDENTIFIER)
            if not class_name:
                class_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.TS_TYPE_IDENTIFIER)
            return class_name.text.decode("utf8") if class_name else None

        if node.type == NodeTypes.JS_METHOD_DEFINITION:
            method_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.JS_PROPERTY_IDENTIFIER)
            if method_name:
                return method_name.text.decode("utf8")
            return None

        if node.type == NodeTypes.JS_FUNCTION_DECLARATION:
            func_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.IDENTIFIER)
            return func_name.text.decode("utf8") if func_name else None

        if node.type == NodeTypes.JS_ARROW_FUNCTION:
            parent = node.parent
            if parent and parent.type == NodeTypes.JS_VARIABLE_DECLARATION:
                return BaseNodeProcessor.find_identifier_in_node(parent)
            return None

        if node.type == NodeTypes.JS_GENERATOR_FUNCTION_DECLARATION:
            func_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.IDENTIFIER)
            return func_name.text.decode("utf8") if func_name else None

        if node.type == NodeTypes.JS_METHOD_DEFINITION:
            class_node = node.parent
            if class_node and class_node.type == NodeTypes.JS_CLASS_DECLARATION:
                class_name = self.get_symbol_name(class_node)
                property_identifier = BaseNodeProcessor.find_child_by_type(node, NodeTypes.JS_PROPERTY_IDENTIFIER)
                if property_identifier:
                    method_name = property_identifier.text.decode("utf8")
                    return f"{class_name}.{method_name}" if class_name and method_name else None

        if node.type == NodeTypes.JS_LEXICAL_DECLARATION:
            declarator = BaseNodeProcessor.find_child_by_type(node, NodeTypes.JS_VARIABLE_DECLARATOR)
            if declarator and BaseNodeProcessor.find_child_by_type(declarator, NodeTypes.JS_FUNCTION_EXPRESSION):
                return BaseNodeProcessor.find_identifier_in_node(declarator)
            if declarator and BaseNodeProcessor.find_child_by_type(declarator, NodeTypes.JS_ARROW_FUNCTION):
                return BaseNodeProcessor.find_identifier_in_node(declarator)
            if declarator and BaseNodeProcessor.find_child_by_type(declarator, NodeTypes.JS_OBJECT):
                return BaseNodeProcessor.find_identifier_in_node(declarator)

        if node.type == NodeTypes.JS_ARROW_FUNCTION:
            parent = node.parent
            if parent and parent.type == NodeTypes.JS_VARIABLE_DECLARATION:
                return BaseNodeProcessor.find_identifier_in_node(parent)

        if node.type == NodeTypes.JS_VARIABLE_DECLARATION:
            return BaseNodeProcessor.find_identifier_in_node(node)

        return None

    def get_function_name(self, node: Node) -> str:
        return self.get_symbol_name(node)


class TypeScriptSpec(JavascriptSpec):
    """TypeScript语言特定处理策略"""

    def get_symbol_name(self, node: Node) -> str:
        if node.type == NodeTypes.TS_NAMESPACE:
            namespace_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.IDENTIFIER)
            return namespace_name.text.decode("utf8") if namespace_name else None

        if node.type == NodeTypes.TS_ABSTRACT_CLASS_DECLARATION:
            class_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.TS_TYPE_IDENTIFIER)
            return class_name.text.decode("utf8") if class_name else None

        if node.type == NodeTypes.TS_ABSTRACT_METHOD_SIGNATURE:
            method_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.JS_PROPERTY_IDENTIFIER)
            if method_name:
                return f"{method_name.text.decode('utf8')}" if method_name else None
            return None

        if node.type == NodeTypes.TS_PUBLIC_FIELD_DEFINITION:
            field_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.JS_PROPERTY_IDENTIFIER)
            if field_name:
                return field_name.text.decode("utf8") if field_name else None
            return None

        if node.type == NodeTypes.TS_TYPE_ALIAS_DECLARATION:
            type_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.TS_TYPE_IDENTIFIER)
            return type_name.text.decode("utf8") if type_name else None

        if node.type == NodeTypes.TS_INTERFACE_DECLARATION:
            interface_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.TS_TYPE_IDENTIFIER)
            return interface_name.text.decode("utf8") if interface_name else None

        if node.type == NodeTypes.TS_ENUM_DECLARATION:
            enum_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.TS_TYPE_IDENTIFIER)
            return enum_name.text.decode("utf8") if enum_name else None

        if node.type == NodeTypes.TS_MODULE_DECLARATION:
            module_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.TS_TYPE_IDENTIFIER)
            return module_name.text.decode("utf8") if module_name else None

        if node.type == NodeTypes.TS_DECLARE_FUNCTION:
            func_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.IDENTIFIER)
            return func_name.text.decode("utf8") if func_name else None

        return super().get_symbol_name(node)

    def get_function_name(self, node: Node) -> str:
        return self.get_symbol_name(node)


class PythonSpec(LangSpec):
    def get_symbol_name(self, node):
        if node.type == NodeTypes.IF_STATEMENT and self.is_main_block(node):
            return "__main__"
        return None

    def get_function_name(self, node):
        return None

    @staticmethod
    def is_main_block(node):
        """判断是否是__main__块"""
        condition = BaseNodeProcessor.find_child_by_type(node, NodeTypes.COMPARISON_OPERATOR)
        if condition:
            left = BaseNodeProcessor.find_child_by_type(condition, NodeTypes.IDENTIFIER)
            right = BaseNodeProcessor.find_child_by_type(condition, NodeTypes.STRING)
            if left and left.text.decode("utf8") == "__name__" and right and "__main__" in right.text.decode("utf8"):
                return True
        return False


class CPPSpec(LangSpec):
    """C++语言特定处理策略"""

    def get_symbol_name(self, node: Node) -> Union[str, Tuple[str, str]]:
        if node.type in (NodeTypes.CPP_CLASS_SPECIFIER, NodeTypes.C_STRUCT_SPECFIER):
            return "class", self.get_cpp_class_name(node)
        if node.type == NodeTypes.CPP_NAMESPACE_DEFINITION:
            return "namespace", self.get_cpp_namespace_name(node)
        if node.type == NodeTypes.C_DECLARATION:
            if self.node_is_function(node):
                return "function", self.get_function_name(node)
            else:
                return self.get_cpp_declaration_name(node)
        if node.type == NodeTypes.CPP_FRIEND_DECLARATION:
            return self.get_friend_function_name(node)
        return None

    def get_cpp_class_name(self, node: Node):
        """从C++类定义节点中提取类名"""
        class_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.C_TYPE_IDENTIFIER)
        if class_name:
            return class_name.text.decode("utf8")
        return None

    def get_cpp_namespace_name(self, node: Node):
        """从命名空间定义节点中提取命名空间名称"""
        namespace_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.CPP_NAMESPACE_IDENTIFIER)
        if namespace_name:
            return namespace_name.text.decode("utf8")
        return None

    def get_cpp_declaration_name(self, node: Node):
        """从声明节点中提取限定名称"""
        init_declarator = BaseNodeProcessor.find_child_by_type(node, NodeTypes.CPP_INIT_DECLARATOR)
        if not init_declarator:
            return None

        # 统一处理数组声明和普通声明
        declarator = (
            BaseNodeProcessor.find_child_by_type(init_declarator, NodeTypes.C_ARRAY_DECLARATOR) or init_declarator
        )

        # 尝试获取限定标识符
        qualified_id = BaseNodeProcessor.find_child_by_type(declarator, NodeTypes.CPP_QUALIFIED_IDENTIFIER)
        if qualified_id:
            namespace = BaseNodeProcessor.find_child_by_type(qualified_id, NodeTypes.CPP_NAMESPACE_IDENTIFIER)
            identifier = BaseNodeProcessor.find_child_by_type(qualified_id, NodeTypes.IDENTIFIER)
            if namespace and identifier:
                return f"{namespace.text.decode('utf8')}.{identifier.text.decode('utf8')}"

        return BaseNodeProcessor.find_identifier_in_node(declarator)

    def get_friend_function_name(self, node: Node):
        decl = BaseNodeProcessor.find_child_by_type(node, NodeTypes.C_DECLARATION)
        return self.get_function_name(decl) if decl else None

    def node_is_function(self, node: Node):
        pointer_declarator = BaseNodeProcessor.find_child_by_type(node, NodeTypes.C_POINTER_DECLARATOR)
        if pointer_declarator:
            func_declarator = pointer_declarator.child_by_field_name("declarator")
            if func_declarator and func_declarator.type == NodeTypes.FUNCTION_DECLARATOR:
                return True
        reference_declarator = BaseNodeProcessor.find_child_by_type(node, NodeTypes.CPP_REFERENCE_DECLARATOR)
        if reference_declarator:
            func_declarator = BaseNodeProcessor.find_child_by_type(reference_declarator, NodeTypes.FUNCTION_DECLARATOR)
            if func_declarator:
                return True
        func_declarator = BaseNodeProcessor.find_child_by_type(node, NodeTypes.FUNCTION_DECLARATOR)
        if func_declarator:
            return True

    def get_function_name(self, node: Node):
        result = None
        pointer_declarator = BaseNodeProcessor.find_child_by_type(node, NodeTypes.C_POINTER_DECLARATOR)
        if pointer_declarator:
            func_declarator = pointer_declarator.child_by_field_name("declarator")
            if func_declarator and func_declarator.type == NodeTypes.FUNCTION_DECLARATOR:
                result = BaseNodeProcessor.find_identifier_in_node(func_declarator)

        if not result:
            reference_declarator = BaseNodeProcessor.find_child_by_type(node, NodeTypes.CPP_REFERENCE_DECLARATOR)
            if reference_declarator:
                func_declarator = BaseNodeProcessor.find_child_by_type(
                    reference_declarator, NodeTypes.FUNCTION_DECLARATOR
                )
                if func_declarator:
                    result = BaseNodeProcessor.find_identifier_in_node(func_declarator)
                    if not result:
                        operator_name = BaseNodeProcessor.find_child_by_type(
                            func_declarator, NodeTypes.CPP_OPERATOR_NAME
                        )
                        if operator_name:
                            result = operator_name.text.decode("utf8")

        if not result:
            func_declarator = BaseNodeProcessor.find_child_by_type(node, NodeTypes.FUNCTION_DECLARATOR)
            if func_declarator:
                qualified_id = BaseNodeProcessor.find_child_by_type(func_declarator, NodeTypes.CPP_QUALIFIED_IDENTIFIER)
                if qualified_id:
                    namespace = BaseNodeProcessor.find_child_by_type(qualified_id, NodeTypes.CPP_NAMESPACE_IDENTIFIER)
                    identifier = BaseNodeProcessor.find_child_by_type(qualified_id, NodeTypes.IDENTIFIER)
                    if namespace and identifier:
                        result = f"{namespace.text.decode('utf8')}.{identifier.text.decode('utf8')}"
                if not result:
                    result = BaseNodeProcessor.find_identifier_in_node(func_declarator)
                if not result:
                    field = BaseNodeProcessor.find_child_by_type(func_declarator, NodeTypes.CPP_FIELD_IDENTIFIER)
                    if field:
                        result = field.text.decode("utf8")
                if not result:
                    operator_name = BaseNodeProcessor.find_child_by_type(func_declarator, NodeTypes.CPP_OPERATOR_NAME)
                    if operator_name:
                        result = operator_name.text.decode("utf8")

        return result


class GoLangSpec(LangSpec):
    """Go语言特定处理策略"""

    def get_symbol_name(self, node) -> str:
        if node.type == NodeTypes.GO_TYPE_DECLARATION:
            return self.get_go_type_name(node)
        if node.type == NodeTypes.GO_METHOD_DECLARATION:
            return self.get_go_method_name(node)
        if node.type == NodeTypes.GO_FUNC_DECLARATION:
            return self.get_go_function_name(node)
        if node.type == NodeTypes.GO_PACKAGE_CLAUSE:
            return self.get_go_package_name(node)
        return None

    def get_function_name(self, node):
        pass

    @staticmethod
    def get_go_method_name(node):
        """从Go方法声明节点中提取方法名，格式为(ReceiverType).MethodName"""
        find_child = BaseNodeProcessor.find_child_by_type
        parameter_list = find_child(node, NodeTypes.GO_PARAMETER_LIST)
        if not parameter_list:
            return None
        parameter_declaration = find_child(parameter_list, NodeTypes.GO_PARAMETER_DECLARATION)
        if not parameter_declaration:
            return None

        type_node = find_child(parameter_declaration, NodeTypes.GO_TYPE_IDENTIFIER)
        if not type_node:
            pointer_type = find_child(parameter_declaration, NodeTypes.GO_POINTER_TYPE)
            if pointer_type:
                type_node = find_child(pointer_type, NodeTypes.GO_TYPE_IDENTIFIER)
                if not type_node:
                    type_node = find_child(pointer_type, NodeTypes.GO_QUALIFIED_TYPE)
        method_name = None

        # 查找方法名
        func_identifier = find_child(node, NodeTypes.GO_FIELD_IDENTIFIER)
        if func_identifier:
            method_name = func_identifier.text.decode("utf8")

        if not method_name or not type_node:
            return None

        return f"{type_node.text.decode('utf8')}.{method_name}"

    @staticmethod
    def get_go_function_name(node):
        """从Go函数声明节点中提取函数名"""
        func_identifier = BaseNodeProcessor.find_child_by_type(node, NodeTypes.IDENTIFIER)
        if func_identifier:
            return func_identifier.text.decode("utf8")
        return None

    @staticmethod
    def get_go_package_name(node):
        """从Go包声明节点中提取包名"""
        package_name = BaseNodeProcessor.find_child_by_type(node, NodeTypes.GO_PACKAGE_IDENTIFIER)
        if package_name:
            return package_name.text.decode("utf8")
        return None

    @staticmethod
    def get_go_type_name(node):
        """从Go类型声明节点中提取类型名"""
        for child in node.children:
            if child.type == NodeTypes.GO_TYPE_SPEC:
                for sub_child in child.children:
                    if sub_child.type == NodeTypes.GO_TYPE_IDENTIFIER:
                        return sub_child.text.decode("utf8")
        return None


class NodeProcessor(BaseNodeProcessor):
    """节点处理器，使用语言特定策略处理节点"""

    def __init__(self, lang_spec: LangSpec = None):
        self.lang_spec = lang_spec

    def get_symbol_name(self, node) -> Union[str, Tuple[str, str]]:
        """提取节点的符号名称"""
        if not hasattr(node, "type"):
            return None
        if node.type == NodeTypes.CLASS_DEFINITION:
            return self.get_class_name(node)
        if node.type in NodeTypes.FUNCTION_DEFINITION:
            return self.get_function_name(node)
        if node.type == NodeTypes.ASSIGNMENT:
            return self.get_assignment_name(node)

        if self.lang_spec:
            return self.lang_spec.get_symbol_name(node)
        return None

    def get_class_name(self, node):
        """从类定义节点中提取类名"""
        for child in node.children:
            if child.type == NodeTypes.IDENTIFIER:
                return child.text.decode("utf8")
        return None

    def get_function_name(self, node):
        """从函数定义节点中提取函数名"""
        if node.type == NodeTypes.FUNCTION_DEFINITION:
            name_node = BaseNodeProcessor.find_child_by_field(node, NodeTypes.NAME)
            if name_node:
                return name_node.text.decode("utf8")
            word_node = BaseNodeProcessor.find_child_by_type(node, NodeTypes.WORD)
            if word_node:
                return word_node.text.decode("utf8")
            identifier_node = BaseNodeProcessor.find_child_by_type(node, NodeTypes.IDENTIFIER)
            if identifier_node:
                return identifier_node.text.decode("utf8")
        if self.lang_spec:
            return self.lang_spec.get_function_name(node)
        return BaseNodeProcessor.find_identifier_in_node(node)

    @staticmethod
    def get_assignment_name(node):
        """从赋值节点中提取变量名"""
        identifier = BaseNodeProcessor.find_child_by_type(node, NodeTypes.IDENTIFIER)
        if identifier:
            return identifier.text.decode("utf8")

        left = node.child_by_field_name("left")
        if left and left.type == NodeTypes.IDENTIFIER:
            return left.text.decode("utf8")
        return None


class CodeMapBuilder:
    def __init__(
        self,
        root_node: Node | None,
        node_processor: NodeProcessor,
        lang: str = PYTHON_LANG,
    ):
        self.node_processor = node_processor
        self.lang = lang
        self.root_node = root_node

    def symbol_at_line(self, line: int) -> Node | None:
        """查找指定行开始的第一个语法树节点，使用层级遍历"""
        if not self.root_node:
            return None
        queue = [self.root_node]
        while queue:
            current_node = queue.pop(0)
            start_row, _ = current_node.start_point
            if start_row == line and current_node.parent:
                return current_node
            queue.extend(current_node.children)
        return None

    def build_symbol_info_at_line(self, line: int) -> dict | None:
        """构建指定行符号的完整信息"""
        node = self.symbol_at_line(line)
        if not node:
            return None
        return self.symbol_info_from_node(node)

    def build_near_symbol_info_at_line(self, line: int) -> dict | None:
        """构建指定行附近符号的完整信息"""
        node = self.symbol_at_line(line)
        if not node:
            return None
        while (
            node
            and node.parent
            and node.parent.type != self.root_node.type
            and not NodeTypes.is_structure_tree_node(node.type)
        ):
            node = node.parent
        if not node:
            return None
        return self.symbol_info_from_node(node)

    def symbol_info_from_node(self, node: Node) -> dict:
        """从节点中提取符号信息"""
        node_info = self.get_symbol_range_info(None, node)
        symbol_info = {
            "code": node.text.decode("utf8"),
            "calls": [],
            "signature": "",
            "full_definition_hash": "",
            "type": "block",
            "start_line": node_info["start_point"][0],
            "end_line": node_info["end_point"][0],
            "block_range": (node_info["start_byte"], node_info["end_byte"]),
            "location": (
                (node_info["start_point"][0], node_info["start_point"][1]),
                (node_info["end_point"][0], node_info["end_point"][1]),
                (node_info["start_byte"], node_info["end_byte"]),
            ),
        }
        return symbol_info

    def _extract_import_block(self, node: Node):
        """提取文件开头的import块，包含注释、字符串字面量和导入语句"""
        import_block = []
        current_node = node
        while current_node and current_node.type in (
            NodeTypes.COMMENT,
            NodeTypes.IMPORT_STATEMENT,
            NodeTypes.IMPORT_FROM_STATEMENT,
            NodeTypes.EXPRESSION_STATEMENT,
            NodeTypes.GO_IMPORT_DECLARATION,
            NodeTypes.GO_PACKAGE_CLAUSE,
        ):
            if current_node.type == NodeTypes.EXPRESSION_STATEMENT:
                if current_node.children[0].type == NodeTypes.STRING:
                    import_block.append(current_node)
            else:
                import_block.append(current_node)
            current_node = current_node.next_sibling
        return import_block

    def _get_effective_node(self, node: Node):
        """获取有效的语法树节点（处理装饰器情况）"""
        if (
            node.type
            in (
                NodeTypes.FUNCTION_DEFINITION,
                NodeTypes.CPP_CLASS_SPECIFIER,
                NodeTypes.TS_INTERFACE_DECLARATION,
                NodeTypes.JS_CLASS_DECLARATION,
            )
            and node.parent
            and node.parent.type
            in (
                NodeTypes.DECORATED_DEFINITION,
                NodeTypes.CPP_TEMPLATE_DECLARATION,
                NodeTypes.TS_EXPORT_STATEMENT,
            )
        ):
            return node.parent
        return node

    def get_symbol_range_info(self, source_bytes: bytes, node: Node):
        """获取节点的代码和位置信息"""
        effective_node = self._get_effective_node(node)
        start_byte = effective_node.start_byte
        start_point = effective_node.start_point
        while node.prev_sibling and node.prev_sibling.type == NodeTypes.COMMENT:
            node = node.prev_sibling
            start_byte = node.start_byte
            start_point = node.start_point
        if source_bytes:
            # 找到行的起始位置
            line_start_byte = source_bytes.rfind(b"\n", 0, start_byte) + 1
            space_ = ord(b" ")
            tab_ = ord(b"\t")
            # 验证从行开始到当前位置都是空白字符
            if line_start_byte < start_byte:
                whitespace = source_bytes[line_start_byte:start_byte]
                if not all([c in (space_, tab_) for c in whitespace]):
                    line_start_byte = start_byte  # 如果不是纯空白，保持原位置
                else:
                    start_byte = line_start_byte
                    start_point = (start_point[0], 0)  # 列位置设为0
        return {
            "start_byte": start_byte,
            "end_byte": effective_node.end_byte,
            "start_point": start_point,
            "end_point": effective_node.end_point,
        }

    def _extract_code(self, source_bytes, start_byte, end_byte):
        """从源字节中提取代码"""
        # 找到行起始位置
        return source_bytes[start_byte:end_byte].decode("utf8")

    def _build_code_map_entry(self, path_key, code, node_info):
        """构建代码映射条目"""
        return {
            "code": code,
            "block_range": (node_info["start_byte"], node_info["end_byte"]),
            "start_line": node_info["start_point"][0],
            "start_col": node_info["start_point"][1],
            "end_line": node_info["end_point"][0],
            "end_col": node_info["end_point"][1],
            "calls": [],
            "type": "unknown",
        }

    def process_import_block(self, node, code_map, source_bytes, results):
        """处理import块"""
        import_block = self._extract_import_block(node.children[0])
        if import_block:
            first_node = import_block[0]
            last_node = import_block[-1]
            node_info = {
                "start_byte": first_node.start_byte,
                "end_byte": last_node.end_byte,
                "start_point": first_node.start_point,
                "end_point": last_node.end_point,
            }
            code = self._extract_code(source_bytes, node_info["start_byte"], node_info["end_byte"])
            code_map["__import__"] = self._build_code_map_entry("__import__", code, node_info)
            code_map["__import__"]["type"] = "import_block"
            results.append("__import__")

    def _process_symbol_node(self, node, current_symbols, current_nodes, code_map, source_bytes, results):
        """处理符号节点，返回处理后的有效节点或None"""
        symbol_name: Union[str, Tuple[str, str]] = self.node_processor.get_symbol_name(node)
        symbol_type = ""
        if isinstance(symbol_name, tuple):
            symbol_type, symbol_name = symbol_name
        if symbol_name is None:
            return None
        if not symbol_type:
            type_mapping = {
                NodeTypes.CLASS_DEFINITION: "class",
                NodeTypes.GO_TYPE_DECLARATION: "type",
                NodeTypes.GO_METHOD_DECLARATION: "method",
                NodeTypes.CPP_NAMESPACE_DEFINITION: "namespace",
                NodeTypes.CPP_TEMPLATE_DECLARATION: "template",
                NodeTypes.IF_STATEMENT: "main_block" if PythonSpec.is_main_block(node) else None,
                NodeTypes.GO_IMPORT_DECLARATION: "import_declaration",
                NodeTypes.ASSIGNMENT: "module_variable" if not current_symbols else "variable",
                NodeTypes.GO_PACKAGE_CLAUSE: "package",
                NodeTypes.C_DECLARATION: "declaration",
            }
            symbol_type = type_mapping.get(node.type)
            if symbol_type is None and NodeTypes.is_structure_tree_node(node.type):
                symbol_type = "function"

            if symbol_type is None:
                symbol_type = node.type

        effective_node = self._get_effective_node(node)
        current_symbols.append(symbol_name)
        current_nodes.append(effective_node)

        path_key = ".".join(current_symbols)
        current_node = current_nodes[-1]

        node_info = self.get_symbol_range_info(source_bytes, current_node)
        code = self._extract_code(source_bytes, node_info["start_byte"], node_info["end_byte"])
        code_entry = self._build_code_map_entry(path_key, code, node_info)
        code_entry["type"] = symbol_type
        if path_key in code_map:
            start_line = code_entry["start_line"]
            path_key = f"{path_key}_{start_line}"
        code_map[path_key] = code_entry
        results.append(path_key)
        if node.type == NodeTypes.GO_PACKAGE_CLAUSE:
            return None
        return effective_node

    def _add_call_info(self, func_name, current_symbols, code_map, node):
        """通用方法：添加调用信息到code_map"""
        if func_name and current_symbols:
            current_path = ".".join(current_symbols)
            if current_path in code_map:
                start_line, start_col = node.start_point
                end_line, end_col = node.end_point
                call_info = {
                    "name": func_name,
                    "start_point": (start_line, start_col),
                    "end_point": (end_line, end_col),
                }
                code_map[current_path]["calls"].append(call_info)

    def _extract_function_calls(self, node: Node, current_symbols, code_map):
        """提取函数调用信息并添加到当前符号的calls集合"""
        if node.type == NodeTypes.CALL:
            function_node = node.child_by_field_name("function")
            if function_node:
                func_name = self.node_processor.get_function_name_from_call(function_node)
                self._add_call_info(func_name, current_symbols, code_map, function_node)
        elif node.type == NodeTypes.ATTRIBUTE:
            func_name = self.node_processor.get_full_attribute_name(node)
            self._add_call_info(func_name, current_symbols, code_map, node)
        elif node.type == NodeTypes.C_ATTRIBUTE_DECLARATION:
            return
        elif self.lang in (C_LANG, CPP_LANG) and node.type == NodeTypes.IDENTIFIER:
            self._add_call_info(node.text.decode("utf8"), current_symbols, code_map, node)
        for child in node.children:
            self._extract_function_calls(child, current_symbols, code_map)

    def _extract_parameter_type_calls(self, node, current_symbols, code_map):
        """提取参数的类型注释中的调用信息"""
        if NodeTypes.is_type(node.type):
            type_node = node.child_by_field_name("type")
            if not type_node:
                return
            identifiers = self._collect_type_identifiers(type_node)
            for identifier in identifiers:
                type_name = identifier.text.decode("utf8")
                if not self.node_processor.is_standard_type(type_name):
                    self._add_call_info(type_name, current_symbols, code_map, identifier)

    def _collect_type_identifiers(self, node):
        """递归收集类型节点中的所有标识符"""
        identifiers = []
        if NodeTypes.is_identifier(node.type):
            identifiers.append(node)
        for child in node.children:
            identifiers.extend(self._collect_type_identifiers(child))
        return identifiers

    def traverse(self, node, current_symbols, current_nodes, code_map, source_bytes, results):
        processed_node = self._process_symbol_node(
            node, current_symbols, current_nodes, code_map, source_bytes, results
        )
        if processed_node:
            self._extract_function_calls(processed_node, current_symbols, code_map)
        self._extract_parameter_type_calls(node, current_symbols, code_map)
        for child in node.children:
            self.traverse(child, current_symbols, current_nodes, code_map, source_bytes, results)
        if processed_node:
            current_symbols.pop()
            current_nodes.pop()

    def build_symbol_info(self, info, file_path):
        """构建符号信息字典"""
        full_definition_hash = calculate_crc32_hash(info["code"])
        location = (
            (info["start_line"], info["start_col"]),
            (info["end_line"], info["end_col"]),
            info["block_range"],
        )
        return {
            "file_path": file_path,
            "signature": "",
            "full_definition_hash": full_definition_hash,
            "location": location,
            "calls": info["calls"],
        }

    def find_symbols_by_location(self, code_map: dict, line: int, column: int) -> list[dict]:
        """根据行列位置查找对应的符号信息列表，按嵌套层次排序（最内层在前）"""
        matched_symbols = []

        # 先查找包含位置的符号
        for path, info in code_map.items():
            start_line = info["start_line"]
            start_col = info["start_col"]
            end_line = info["end_line"]
            end_col = info["end_col"]

            if (start_line < line or (start_line == line and start_col <= column)) and (
                line < end_line or (line == end_line and column <= end_col)
            ):
                if info.get("type") == "variable":
                    continue
                matched_symbols.append({"symbol": path, "info": info})

        # 按嵌套深度排序
        matched_symbols.sort(
            key=lambda x: (
                -x["symbol"].count("."),
                x["symbol"].split(".")[-1].startswith("__"),
                x["symbol"],
            )
        )
        return matched_symbols

    def find_symbols_for_locations(
        self,
        code_map: dict,
        locations: list[tuple[int, int]],
        max_context_size: int = 16 * 1024,
        include_class_context: bool = True,
    ) -> dict[str, dict]:
        """批量处理位置并返回符号名到符号信息的映射"""
        sorted_symbols = sorted(
            code_map.items(),
            key=lambda item: (
                -item[1]["start_line"],
                -item[1]["start_col"],
                item[1]["end_line"],
                item[1]["end_col"],
            ),
        )
        sorted_locations = sorted(locations, key=lambda loc: (loc[0], loc[1]))

        processed_symbols = {}
        symbol_locations = {}
        total_code_size = 0

        # 存储处理后的位置信息 (line, col, symbol_path)
        processed_locations_with_symbols = []

        for line, col in sorted_locations:
            current_symbol = None
            for symbol_path, symbol_info in sorted_symbols:
                if symbol_info["type"] == "variable":
                    continue
                s_line = symbol_info["start_line"]
                s_col = symbol_info["start_col"]
                e_line = symbol_info["end_line"]
                e_col = symbol_info["end_col"]

                if (
                    (s_line <= line <= e_line)
                    and (s_col <= col if line == s_line else True)
                    and (col <= e_col if line == e_line else True)
                ):
                    current_symbol = symbol_path
                    break

            if current_symbol:
                symbol_to_process = current_symbol

                # 类上下文处理开关: 如果开启，尝试将符号从方法“升级”到其父类
                if include_class_context:
                    symbol_info = code_map[current_symbol]
                    # 仅处理函数类型且包含命名空间的符号 (e.g., "MyClass.my_method")
                    if symbol_info.get("type") == "function" and "." in current_symbol:
                        parts = current_symbol.split(".")
                        if len(parts) > 1:
                            class_path = ".".join(parts[:-1])
                            if class_path in code_map:
                                # 找到了一个父类。现在决定是否使用它。
                                class_info = code_map[class_path]
                                class_code_length = len(class_info.get("code", ""))

                                # 如果类已经被处理，或者尚未处理但可以容纳在上下文中，
                                # 我们就选择用类来代替方法。
                                if class_path in processed_symbols or (
                                    total_code_size + class_code_length <= max_context_size
                                ):
                                    symbol_to_process = class_path

                # 处理选定的符号（类或原始方法）
                symbol_info = code_map[symbol_to_process]
                if symbol_to_process not in processed_symbols:
                    code_length = len(symbol_info.get("code", ""))
                    if total_code_size + code_length > max_context_size:
                        logging.warning(f"Context size exceeded {max_context_size} bytes, stopping symbol collection")
                        break
                    processed_symbols[symbol_to_process] = symbol_info.copy()
                    total_code_size += code_length

                processed_locations_with_symbols.append((line, col, symbol_to_process))
            else:
                # 未找到完全包含该位置的符号，则查找临近符号
                symbol_info = self.build_near_symbol_info_at_line(line)
                if not symbol_info:
                    continue

                symbol_path = near_symbol_at_line(line)
                code_length = len(symbol_info.get("code", ""))
                if total_code_size + code_length > max_context_size:
                    logging.warning(f"Context size exceeded {max_context_size} bytes, stopping symbol collection")
                    break
                processed_locations_with_symbols.append((line, col, symbol_path))
                if symbol_path not in processed_symbols:
                    processed_symbols[symbol_path] = symbol_info
                    total_code_size += code_length

            if total_code_size >= max_context_size:
                break

        for line, col, symbol in processed_locations_with_symbols:
            if symbol not in symbol_locations:
                symbol_locations[symbol] = []
            symbol_locations[symbol].append((line, col))

        for symbol in processed_symbols:
            processed_symbols[symbol]["locations"] = symbol_locations.get(symbol, [])

        return processed_symbols


def is_node_module(node_type):
    return NodeTypes.is_module(node_type)


def dump_tree(node, indent=0):
    prefix = "  " * indent
    node_text = node.text.decode("utf8") if node.text else ""
    # 或者根据 source_bytes 截取：node_text = source_bytes[node.start_byte:node.end_byte].decode('utf8')
    print(f"{prefix}type={node.type} [start:{node.start_byte}, end:{node.end_byte}] '{node_text}'")
    for child in node.children:
        dump_tree(child, indent + 1)


INDENT_UNIT = "    "  # 定义缩进单位


class SourceSkeleton:
    def __init__(self, parser_loader: ParserLoader):
        self.parser_loader = parser_loader

    def _get_docstring(self, node, parent_type: str):
        """根据Tree-sitter节点类型提取文档字符串"""
        if parent_type == NodeTypes.DECORATED_DEFINITION:
            for child in node.children:
                if child.type == NodeTypes.FUNCTION_DEFINITION:
                    node = child
                    parent_type = NodeTypes.FUNCTION_DEFINITION
                    break
        # 模块文档字符串：第一个连续的字符串表达式
        if is_node_module(parent_type):
            if len(node.children) > 1 and node.children[0].type == NodeTypes.EXPRESSION_STATEMENT:
                return node.children[0].text.decode("utf8")

        # 类/函数文档字符串：body中的第一个字符串表达式
        if parent_type in (NodeTypes.CLASS_DEFINITION, NodeTypes.FUNCTION_DEFINITION):
            node = node.child_by_field_name(NodeTypes.BODY)
            if node:
                if (
                    len(node.children) > 1
                    and node.children[0].type == NodeTypes.EXPRESSION_STATEMENT
                    and node.children[0].children[0].type == NodeTypes.STRING
                ):
                    return node.children[0].text.decode("utf8")
        if parent_type in (
            NodeTypes.GO_FUNC_DECLARATION,
            NodeTypes.GO_METHOD_DECLARATION,
        ):
            prev = node.prev_sibling
            comment_all = []
            while prev and prev.type == NodeTypes.COMMENT:
                comment_all.append(prev.text.decode("utf8"))
                prev = prev.prev_sibling
            return "\n".join(reversed(comment_all))
        return None

    def _capture_signature(self, node, source_bytes: bytes) -> str:
        """精确捕获定义签名（基于Tree-sitter解析结构）"""
        start = node.start_byte
        end = 0

        if node.type == NodeTypes.DECORATED_DEFINITION:
            for v in node.children:
                if v.type in (
                    NodeTypes.FUNCTION_DEFINITION,
                    NodeTypes.CLASS_DEFINITION,
                ):
                    for j, v1 in enumerate(v.children):
                        if v1.type == NodeTypes.BLOCK:
                            end = v.children[j - 1].end_byte
                            break
            if end == 0:
                dump_tree(node, source_bytes)
                raise ValueError("unknown ast")
            return source_bytes[start:end].decode("utf8")

        if node.type in (
            NodeTypes.FUNCTION_DEFINITION,
            NodeTypes.CLASS_DEFINITION,
            NodeTypes.GO_FUNC_DECLARATION,
            NodeTypes.GO_METHOD_DECLARATION,
        ):
            for j, v1 in enumerate(node.children):
                if v1.type in (NodeTypes.BLOCK, NodeTypes.COMPOUND_STATEMENT):
                    end = node.children[j - 1].end_byte
                    break
            if end == 0:
                dump_tree(node, source_bytes)
                raise ValueError("unknown ast")
            return source_bytes[start:end].decode("utf8")

        dump_tree(node, source_bytes)
        raise ValueError("unknown ast")

    def _process_node(self, node, source_bytes: bytes, indent=0, lang_name="") -> List[str]:
        """基于Tree-sitter节点类型的处理逻辑"""
        output = []
        indent_str = INDENT_UNIT * indent

        def process_module_node():
            for child in node.children:
                if child.type in [
                    NodeTypes.CLASS_DEFINITION,
                    NodeTypes.FUNCTION_DEFINITION,
                    NodeTypes.IMPORT_FROM_STATEMENT,
                    NodeTypes.EXPRESSION_STATEMENT,
                    NodeTypes.IMPORT_STATEMENT,
                    NodeTypes.DECORATED_DEFINITION,
                    NodeTypes.C_DEFINE,
                    NodeTypes.C_INCLUDE,
                    NodeTypes.C_DECLARATION,
                    NodeTypes.GO_IMPORT_DECLARATION,
                    NodeTypes.GO_CONST_DECLARATION,
                    NodeTypes.GO_TYPE_DECLARATION,
                    NodeTypes.GO_FUNC_DECLARATION,
                    NodeTypes.GO_METHOD_DECLARATION,
                    NodeTypes.GO_PACKAGE_CLAUSE,
                ]:
                    output.extend(self._process_node(child, source_bytes, lang_name=lang_name))

        def process_class_node():
            class_sig = self._capture_signature(node, source_bytes)
            output.append(f"\n{class_sig}")

            docstring = self._get_docstring(node, NodeTypes.CLASS_DEFINITION)
            if docstring:
                output.append(f'{indent_str}{INDENT_UNIT}"""{docstring}"""')

            body = node.child_by_field_name(NodeTypes.BODY)
            if body:
                for member in body.children:
                    if member.type in [
                        NodeTypes.FUNCTION_DEFINITION,
                        NodeTypes.DECORATED_DEFINITION,
                        NodeTypes.GO_IMPORT_DECLARATION,
                        NodeTypes.GO_METHOD_DECLARATION,
                    ]:
                        output.extend(self._process_node(member, source_bytes, indent + 1, lang_name=lang_name))
                    elif member.type == NodeTypes.EXPRESSION_STATEMENT:
                        code = source_bytes[member.start_byte : member.end_byte].decode("utf8")
                        output.append(f"{indent_str}{INDENT_UNIT}{code}")

        def process_function_node():
            if self.is_lang_cstyle(lang_name):
                docstring = self._get_docstring(node, node.type)
                if docstring:
                    output.append(f"{indent_str}{docstring}")

            func_sig = self._capture_signature(node, source_bytes)
            output.append(f"{indent_str}{func_sig}")

            if not self.is_lang_cstyle(lang_name):
                docstring = self._get_docstring(node, node.type)
                if docstring:
                    output.append(f"{indent_str}{INDENT_UNIT}{docstring}")

            if self.is_lang_cstyle(lang_name):
                output.append("{\n    //Placeholder\n}")
            else:
                output.append(f"{indent_str}{INDENT_UNIT}pass  # Placeholder")

        def process_other_node():
            if is_node_module(node.parent.type):
                code = source_bytes[node.start_byte : node.end_byte].decode("utf8")
                output.append(f"{code}")

        # 处理模块级元素
        if is_node_module(node.type):
            process_module_node()
        # 处理类定义
        elif node.type == NodeTypes.CLASS_DEFINITION:
            process_class_node()
        # 处理函数/方法定义
        elif node.type in [
            NodeTypes.FUNCTION_DEFINITION,
            NodeTypes.DECORATED_DEFINITION,
            NodeTypes.GO_FUNC_DECLARATION,
            NodeTypes.GO_METHOD_DECLARATION,
        ]:
            process_function_node()
        # 处理模块级赋值
        elif node.type in (
            NodeTypes.C_DEFINE,
            NodeTypes.GO_IMPORT_DECLARATION,
            NodeTypes.C_INCLUDE,
            NodeTypes.C_DECLARATION,
            NodeTypes.IMPORT_STATEMENT,
            NodeTypes.IMPORT_FROM_STATEMENT,
            NodeTypes.GO_CONST_DECLARATION,
            NodeTypes.GO_TYPE_DECLARATION,
            NodeTypes.GO_PACKAGE_CLAUSE,
        ):
            process_other_node()

        return output

    def is_lang_cstyle(self, lang_name):
        return lang_name in ("c", "cpp", "go", "java")

    def generate_framework(self, file_path: str) -> str:
        """生成符合测试样例结构的框架代码"""
        parser, _, lang_name = self.parser_loader.get_parser(file_path)

        with open(file_path, "rb") as f:
            source_bytes = f.read()

        tree = parser.parse(source_bytes)
        root = tree.root_node
        framework_lines = (
            ["// Auto-generated code skeleton\n"]
            if self.is_lang_cstyle(lang_name)
            else ["# Auto-generated code skeleton\n"]
        )
        framework_content = self._process_node(root, source_bytes, lang_name=lang_name)

        # 合并结果并优化格式
        result = "\n".join(framework_lines + framework_content)
        return re.sub(r"\n{3,}", "\n\n", result).strip() + "\n"
        # 常见二进制文件的magic number
