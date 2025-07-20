from pathlib import Path
from typing import ClassVar

# Define the base path for prompts relative to this file's location.
# This makes the prompt loading logic robust to where the script is run from.
_PROMPT_DIR = Path(__file__).parent.parent / "prompts"


class FixerPromptGenerator:
    """
    A centralized class for generating various prompts used in the test-fixing workflow.

    This class encapsulates the logic for loading prompt templates from files and
    formatting them with dynamic data, making the main workflow code cleaner and
    the prompt engineering process more modular and manageable.
    """

    # Class variables to hold the loaded template texts, avoiding repeated file I/O.
    _analyze_failure_template: ClassVar[str] = ""
    _generate_fix_template: ClassVar[str] = ""

    @classmethod
    def _load_template(cls, template_name: str) -> str:
        """Loads a prompt template from the filesystem."""
        template_path = _PROMPT_DIR / template_name
        try:
            return template_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            # Provide a sensible fallback if the template file is missing.
            print(f"Warning: Prompt template at '{template_path}' not found. Using a basic fallback.")
            if "analyze" in template_name:
                return "Please analyze the cause of the failure based on the provided logs and context."
            if "generate_fix" in template_name:
                return "Please generate a code patch to fix the issue based on the provided analysis."
            return "Please analyze and fix the issue."

    @classmethod
    def _get_analyze_failure_template(cls) -> str:
        """Lazily loads and caches the analysis prompt template."""
        if not cls._analyze_failure_template:
            cls._analyze_failure_template = cls._load_template("unittest_analyze_failure.py.prompt")
        return cls._analyze_failure_template

    @classmethod
    def _get_generate_fix_template(cls) -> str:
        """Lazily loads and caches the fix generation prompt template."""
        if not cls._generate_fix_template:
            cls._generate_fix_template = cls._load_template("unittest_generate_fix.py.prompt")
        return cls._generate_fix_template

    @classmethod
    def create_direct_fix_prompt(cls, trace_log: str, user_req: str) -> str:
        """
        Generates a prompt for a direct, one-step fix.

        Args:
            trace_log: The detailed trace log of the failed test run.
            user_req: The user's specific requirement for the fix.

        Returns:
            A formatted prompt string for the LLM.
        """
        if not user_req:
            user_req = "分析并解决用户遇到的问题，修复test_*符号中的错误"

        return f"""
请根据以下tracer的报告, 分析问题原因并直接修复testcase相关问题。请以中文回复, 需要注意# Debug 后的取值反映了真实的运行数据。

**重要指令**：在修复代码时，请不要在代码中添加任何解释性注释。只提供纯粹的代码修改，不要在代码中包含分析或理由。

用户的要求: {user_req}
[trace log start]
{trace_log}
[trace log end]
"""

    @classmethod
    def create_analysis_prompt(cls, trace_log: str) -> str:
        """
        Generates a prompt for the failure analysis step (Step 1 of a two-step fix).

        Args:
            trace_log: The detailed trace log of the failed test run.

        Returns:
            A formatted prompt string for the LLM.
        """
        analyze_prompt_template = cls._get_analyze_failure_template()
        return f"""
{analyze_prompt_template}
[trace log start]
{trace_log}
[trace log end]
"""

    @classmethod
    def create_fix_from_analysis_prompt(cls, trace_log: str, analysis_text: str, user_directive: str) -> str:
        """
        Generates a prompt for the fix generation step (Step 2 of a two-step fix).

        This prompt includes the original analysis to provide context for the fix.

        Args:
            trace_log: The detailed trace log of the failed test run.
            analysis_text: The AI-generated analysis of the failure.
            user_directive: The final command from the user on how to proceed with the fix.

        Returns:
            A formatted prompt string for the LLM.
        """
        fix_prompt_template = cls._get_generate_fix_template()
        return f"""
{fix_prompt_template}

[技术专家的分析报告]
{analysis_text}
[用户最终指令]
{user_directive}

**重要指令**：在修复代码时，请不要在代码中添加任何解释性注释。只提供纯粹的代码修改，不要在代码中包含分析或理由。

[trace log start]
{trace_log}
[trace log end]
"""
