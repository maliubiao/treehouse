#!/usr/bin/env python
"""终端聊天机器人UI实现

提供基于prompt_toolkit的交互式聊天界面，支持:
- 流式响应显示
- Markdown语法高亮
- 命令补全
- 护眼主题配色
"""

import argparse
import os
import sys
import traceback

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.lexers import PygmentsLexer
from prompt_toolkit.styles import Style
from pygments.lexers.markup import MarkdownLexer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from llm_query import GPTContextProcessor, ModelSwitch


# 定义UI样式
class EyeCareStyle:
    """护眼主题配色方案"""

    def __init__(self):
        self.styles = {
            # 基础界面元素
            "": "#4CAF50",  # 默认文本颜色
            "prompt": "#4CAF50 bold",
            "input": "#4CAF50",
            "output": "#81C784",
            "status": "#4CAF50",
            # 自动补全菜单
            "completion.current": "bg:#4CAF50 #ffffff",
            "completion": "bg:#E8F5E9 #4CAF50",
            "progress-button": "bg:#C8E6C9",
            "progress-bar": "bg:#4CAF50",
            # 滚动条
            "scrollbar.button": "bg:#E8F5E9",
            "scrollbar": "bg:#4CAF50",
            # Markdown渲染
            "markdown.heading": "#4CAF50 bold",
            "markdown.code": "#4CAF50",
            "markdown.list": "#4CAF50",
            "markdown.blockquote": "#81C784",
            "markdown.link": "#4CAF50 underline",
            # GPT响应相关
            "gpt.response": "#81C784",
            "gpt.prefix": "#4CAF50 bold",
            # 特殊符号
            "special-symbol": "#4CAF50 italic",
        }

    def invalidation_hash(self):
        """生成样式哈希值用于缓存失效检测"""
        return hash(frozenset(self.styles.items()))


class ChatbotUI:
    """终端聊天机器人UI类，支持流式响应、Markdown渲染和自动补全

    输入假设:
    - 环境变量GPT_KEY、GPT_MODEL、GPT_BASE_URL必须已正确配置
    - 当使用@符号补全时，prompts目录需存在于GPT_PATH环境变量指定路径下
    - 温度值设置命令参数应为0-1之间的浮点数
    """

    _COMMAND_HANDLERS = {
        "clear": lambda self: os.system("clear"),
        "help": lambda self: self.display_help(),
        "exit": lambda self: sys.exit(0),
        "temperature": lambda self, cmd: self.handle_temperature_command(cmd),
    }

    _SYMBOL_DESCRIPTIONS = [
        ("@clipboard", "插入剪贴板内容"),
        ("@tree", "显示当前目录结构"),
        ("@treefull", "显示完整目录结构"),
        ("@read", "读取文件内容"),
        ("@listen", "语音输入"),
        ("@symbol:", "插入特殊符号(如@symbol:check)"),
    ]

    _COMMAND_LIST = [
        ("/clear", "清空屏幕内容", "/clear"),
        ("/help", "显示本帮助信息", "/help"),
        ("/exit", "退出程序", "/exit"),
        ("/temperature", "设置生成温度(0-1)", "/temperature 0.8"),
    ]

    def __init__(self, gpt_processor: GPTContextProcessor = None, model="architect"):
        """初始化UI组件和配置
        Args:
            gpt_processor: GPT上下文处理器实例，允许依赖注入便于测试
            model: 要使用的语言模型名称
        """
        self.style = self._configure_style()
        self.session = PromptSession(style=self.style)
        self.bindings = self._setup_keybindings()
        self.console = Console()
        self.temperature = 0.6
        self.gpt_processor = gpt_processor or GPTContextProcessor()
        self.model = model
        self.model_switch = ModelSwitch()
        self.model_switch.select(model)

    def __str__(self) -> str:
        return (
            f"ChatbotUI(temperature={self.temperature}, "
            f"style={self.style.styles}, "
            f"gpt_processor={type(self.gpt_processor).__name__})"
        )

    def _configure_style(self) -> Style:
        """配置终端样式为护眼风格"""
        return Style.from_dict(EyeCareStyle().styles)

    def _setup_keybindings(self) -> KeyBindings:
        """设置快捷键绑定"""
        bindings = KeyBindings()
        bindings.add("escape")(self._exit_handler)
        bindings.add("c-c")(self._exit_handler)
        bindings.add("c-l")(self._clear_screen_handler)
        return bindings

    def _exit_handler(self, event):
        event.app.exit()

    def _clear_screen_handler(self, event):
        event.app.renderer.clear()

    def handle_command(self, cmd: str):
        """处理斜杠命令
        Args:
            cmd: 用户输入的命令字符串，需以/开头
        """
        cmd_parts = cmd.split(maxsplit=1)
        base_cmd = cmd_parts[0]

        if base_cmd not in self._COMMAND_HANDLERS:
            self.console.print(f"[red]未知命令: {cmd}[/]")
            return

        try:
            if base_cmd == "temperature":
                self._COMMAND_HANDLERS[base_cmd](self, cmd)
            else:
                self._COMMAND_HANDLERS[base_cmd](self)
        except Exception as e:
            self.console.print(f"[red]命令执行失败: {str(e)}[/]")

    def display_help(self):
        """显示详细的帮助信息"""
        self._print_command_help()
        self._print_symbol_help()

    def _print_command_help(self):
        """输出命令帮助表格"""
        table = Table(show_header=True, header_style="bold #4CAF50", box=None)
        table.add_column("命令", width=15, style="#4CAF50")
        table.add_column("描述", style="#4CAF50")
        table.add_column("示例", style="dim #4CAF50")

        for cmd, desc, example in self._COMMAND_LIST:
            table.add_row(Text(cmd, style="#4CAF50 bold"), desc, Text(example, style="#81C784"))

        self.console.print("\n[bold #4CAF50]可用命令列表:[/]")
        self.console.print(table)

    def _print_symbol_help(self):
        """输出符号帮助表格"""
        symbol_table = Table(show_header=False, box=None, padding=(0, 1, 0, 0))
        symbol_table.add_column("符号", style="#4CAF50 bold", width=12)
        symbol_table.add_column("描述", style="#81C784")

        for symbol, desc in self._SYMBOL_DESCRIPTIONS:
            symbol_table.add_row(symbol, desc)

        self.console.print("\n[bold #4CAF50]符号功能说明:[/]")
        self.console.print(symbol_table)
        self.console.print("\n[dim #4CAF50]提示: 输入时使用Tab键触发自动补全，按Ctrl+L清屏，Esc键退出程序[/]")

    def handle_temperature_command(self, cmd: str):
        """处理温度设置命令
        Args:
            cmd: 完整的温度设置命令字符串，例如'temperature 0.8'
        """
        try:
            parts = cmd.split()
            if len(parts) == 1:
                self.console.print(f"当前temperature: {self.temperature}")
                return

            temp = float(parts[1])
            if not 0 <= temp <= 1:
                raise ValueError("temperature必须在0到1之间")

            self.temperature = temp
            self.console.print(f"temperature已设置为: {self.temperature}", style="#4CAF50")

        except (ValueError, IndexError) as e:
            self.console.print(f"[red]参数错误: {str(e)}[/]")

    def get_completer(self) -> WordCompleter:
        """获取自动补全器，支持@和/两种补全模式"""
        prompt_files = self._get_prompt_files()
        all_items = [s[0] for s in self._SYMBOL_DESCRIPTIONS] + prompt_files + [c[0] for c in self._COMMAND_LIST]

        meta_dict = {
            **{s[0]: s[1] for s in self._SYMBOL_DESCRIPTIONS},
            **{c[0]: c[1] for c in self._COMMAND_LIST},
        }

        return WordCompleter(
            words=all_items,
            meta_dict=meta_dict,
            ignore_case=True,
            # 启用句子模式补全（允许部分匹配）
            sentence=False,
            match_middle=True,
            WORD=False,
        )

    def _get_prompt_files(self) -> list:
        """获取提示文件列表"""
        prompts_dir = os.path.join(os.getenv("GPT_PATH", ""), "prompts")
        if os.path.exists(prompts_dir):
            return ["@" + f for f in os.listdir(prompts_dir)]
        return []

    def stream_response(self, prompt: str):
        """流式获取GPT响应并实时渲染Markdown
        Args:
            prompt: 用户输入的提示文本
        """
        processed_text = self.gpt_processor.process_text(prompt)
        return self.model_switch.query(
            model_name=self.model,
            prompt=processed_text,
            stream=True,
            console=self.console,
            temperature=self.temperature,
            disable_conversation_history=False,
        )

    def run(self):
        """启动聊天机器人主循环"""
        self.console.print(
            f"欢迎使用终端聊天机器人！模型: [bold]{self.model}[/bold]. 输入您的问题，按回车发送。按ESC退出",
            style="#4CAF50",
        )

        while True:
            try:
                text = self.session.prompt(
                    ">",
                    key_bindings=self.bindings,
                    completer=self.get_completer(),
                    complete_while_typing=True,
                    bottom_toolbar=lambda: (
                        f"状态: 就绪 | 模型: {self.model} | Temp: {self.temperature} | [Ctrl+L 清屏] [@ 补全] [/ 命令]"
                    ),
                    lexer=PygmentsLexer(MarkdownLexer),
                )

                if not self._process_input(text):
                    break

            except KeyboardInterrupt:
                self.console.print("\n已退出聊天。", style="#4CAF50")
                break
            except EOFError:
                self.console.print("\n已退出聊天。", style="#4CAF50")
                break
            except Exception as e:
                traceback.print_exc()
                self.console.print(f"\n[red]发生错误: {str(e)}[/]\n")

    def _process_input(self, text: str) -> bool:
        """处理用户输入，决定是否继续主循环。

        - 空输入或仅含空格的输入将被忽略。
        - 输入 'q' (不区分大小写) 将退出程序。
        - 以 '/' 开头的输入被视作命令处理。
        - 其他输入将作为提问发送给模型。

        Returns:
            bool: 返回 `True` 继续运行主循环, `False` 则退出。
        """
        stripped_text = text.strip()

        if not stripped_text:
            # 忽略空输入或纯空格输入，继续循环
            return True

        if stripped_text.lower() == "q":
            self.console.print("已退出聊天。", style="#4CAF50")
            return False

        if stripped_text.startswith("/"):
            self.handle_command(stripped_text[1:])
            return True

        self.console.print("BOT:", style="#4CAF50 bold")
        # 传递原始text，保留用户可能输入的特殊格式（如缩进）
        self.stream_response(text)
        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Terminal Chatbot UI")
    parser.add_argument(
        "-m",
        "--model",
        type=str,
        default="architect",
        help="The model to use for the chatbot (e.g., 'architect', 'gpt-4', 'deepseek').",
    )
    args = parser.parse_args()
    ChatbotUI(model=args.model).run()
