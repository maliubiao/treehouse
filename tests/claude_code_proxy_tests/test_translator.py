import json
import unittest
from pathlib import Path

from tools.claude_code_proxy.models_anthropic import AnthropicRequest
from tools.claude_code_proxy.request_translator import translate_anthropic_to_openai


class TestRequestTranslator(unittest.TestCase):
    """Unit tests for the request translation logic."""

    def test_translation_from_sample_file(self) -> None:
        """
        Tests the translation logic by loading the sample request file,
        translating it, and asserting key properties of the output. This test
        is aligned with the `sample_anthropic_request.json` file.
        """
        # Load the sample request
        test_file_path = Path(__file__).parent / "sample_anthropic_request.json"
        with open(test_file_path, "r", encoding="utf-8") as f:
            sample_data = json.load(f)

        anthropic_request = AnthropicRequest.model_validate(sample_data)

        # Perform the translation
        openai_request = translate_anthropic_to_openai(anthropic_request, "gpt-4o")

        # Assertions for the OpenAI request
        self.assertEqual(openai_request.model, "gpt-4o")
        self.assertIs(openai_request.stream, False)
        self.assertEqual(openai_request.temperature, 0.7)
        self.assertEqual(openai_request.max_tokens, 4096)
        self.assertEqual(len(openai_request.messages), 4)

        # 1. System Message
        self.assertEqual(openai_request.messages[0].role, "system")
        self.assertIn(
            "You are a helpful assistant that provides weather information.", openai_request.messages[0].content
        )

        # 2. First User Message
        self.assertEqual(openai_request.messages[1].role, "user")
        self.assertEqual(openai_request.messages[1].content, "What is the weather in San Francisco?")

        # 3. Assistant Message (with tool_call)
        self.assertEqual(openai_request.messages[2].role, "assistant")
        self.assertEqual(openai_request.messages[2].content, "Of course, I can check the weather for you.")
        self.assertIsNotNone(openai_request.messages[2].tool_calls)
        self.assertEqual(len(openai_request.messages[2].tool_calls), 1)
        tool_call = openai_request.messages[2].tool_calls[0]
        self.assertEqual(tool_call.id, "toolu_01A09q90qw90lq917835lqas")
        self.assertEqual(tool_call.function.name, "get_weather")
        self.assertEqual(tool_call.function.arguments, '{"city": "San Francisco"}')

        # 4. Tool Message (result of the tool call)
        self.assertEqual(openai_request.messages[3].role, "tool")
        self.assertEqual(openai_request.messages[3].tool_call_id, "toolu_01A09q90qw90lq917835lqas")
        self.assertEqual(openai_request.messages[3].content, '{"temperature": 72, "unit": "fahrenheit"}')

    def test_complex_conversation_translation(self) -> None:
        """
        Tests translation of a complex, multi-turn conversation with multiple
        tool uses and results, using `request_one.json`.
        """
        test_file_path = Path(__file__).parent / "request_one.json"
        with open(test_file_path, "r", encoding="utf-8") as f:
            sample_data = json.load(f)

        anthropic_request = AnthropicRequest.model_validate(sample_data)
        openai_request = translate_anthropic_to_openai(anthropic_request, "gpt-4o")

        # Basic assertions
        self.assertEqual(openai_request.model, "gpt-4o")
        # The 17 messages in the Anthropic request translate to 20 OpenAI messages (including system prompt).
        self.assertEqual(len(openai_request.messages), 20)

        # System prompt
        self.assertEqual(openai_request.messages[0].role, "system")
        self.assertIn("You are Claude Code", openai_request.messages[0].content)

        # First user message (multiple text blocks)
        self.assertEqual(openai_request.messages[1].role, "user")
        self.assertIn("<system-reminder>", openai_request.messages[1].content)
        self.assertIn("hello", openai_request.messages[1].content)

        # First assistant message
        self.assertEqual(openai_request.messages[2].role, "assistant")
        self.assertEqual(openai_request.messages[2].content, "Hello! How can I help you today?")

        # User message
        self.assertEqual(openai_request.messages[3].role, "user")

        # Assistant message with tool use
        self.assertEqual(openai_request.messages[4].role, "assistant")
        self.assertEqual(
            openai_request.messages[4].content,
            "I'll analyze this program's functionality. Let me first explore the codebase to understand what we're working with.",
        )
        self.assertIsNotNone(openai_request.messages[4].tool_calls)
        self.assertEqual(len(openai_request.messages[4].tool_calls), 1)
        self.assertEqual(openai_request.messages[4].tool_calls[0].function.name, "LS")

        # User message with tool result -> becomes OpenAI 'tool' role message
        self.assertEqual(openai_request.messages[5].role, "tool")
        self.assertEqual(openai_request.messages[5].tool_call_id, "LS_0")
        self.assertIn("DEBUG_TUTORIAL.md", openai_request.messages[5].content)

        # Assistant with multiple tool uses
        self.assertEqual(openai_request.messages[6].role, "assistant")
        self.assertEqual(
            openai_request.messages[6].content,
            "Let me examine the main entry point and key files to understand the program's purpose:",
        )
        self.assertIsNotNone(openai_request.messages[6].tool_calls)
        self.assertEqual(len(openai_request.messages[6].tool_calls), 3)
        self.assertEqual(openai_request.messages[6].tool_calls[0].id, "Read_1")
        self.assertEqual(openai_request.messages[6].tool_calls[1].id, "Read_2")
        self.assertEqual(openai_request.messages[6].tool_calls[2].id, "Read_3")

        # Multiple tool results in one user message are split into multiple tool messages
        self.assertEqual(openai_request.messages[7].role, "tool")
        self.assertEqual(openai_request.messages[7].tool_call_id, "Read_1")
        self.assertIn("find_program_entrypoints", openai_request.messages[7].content)

        self.assertEqual(openai_request.messages[8].role, "tool")
        self.assertEqual(openai_request.messages[8].tool_call_id, "Read_2")
        self.assertIn("LLDB AI Debugging Tools", openai_request.messages[8].content)

        self.assertEqual(openai_request.messages[9].role, "tool")
        self.assertEqual(openai_request.messages[9].tool_call_id, "Read_3")
        self.assertIn("CommandValidator", openai_request.messages[9].content)


if __name__ == "__main__":
    unittest.main()
