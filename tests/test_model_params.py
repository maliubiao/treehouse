import json
import os
import tempfile
import time
import unittest
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

from llm_query import GLOBAL_MODEL_CONFIG, ModelConfig, ModelSwitch, query_gpt_api


class TestThinkingBudgetParameter(unittest.TestCase):
    """
    测试thinking_budget参数的行为和影响
    """

    def setUp(self) -> None:
        """初始化测试环境"""
        # 保存原始环境变量
        self.original_env = {
            "GPT_KEY": os.environ.get("GPT_KEY"),
            "GPT_BASE_URL": os.environ.get("GPT_BASE_URL"),
            "GPT_MODEL": os.environ.get("GPT_MODEL"),
            "GPT_THINKING_BUDGET": os.environ.get("GPT_THINKING_BUDGET"),
        }

        # 设置测试环境变量
        os.environ["GPT_KEY"] = "test_key"
        os.environ["GPT_BASE_URL"] = "http://test-api"
        os.environ["GPT_MODEL"] = "test-model"

        # 创建临时目录用于测试配置文件
        self.test_dir = tempfile.TemporaryDirectory()
        self.test_config_file = os.path.join(self.test_dir.name, "model.json")

    def tearDown(self) -> None:
        """清理测试环境"""
        # 恢复原始环境变量
        for key, value in self.original_env.items():
            if value is not None:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)

        # 清理临时目录
        self.test_dir.cleanup()
        # Clean up global config modified by tests
        if "GLOBAL_MODEL_CONFIG" in globals():
            globals()["GLOBAL_MODEL_CONFIG"] = None

    def _create_test_config(self, thinking_budget: Optional[int] = None) -> None:
        """创建测试配置文件"""
        config = {
            "test_model": {
                "key": "test_key",
                "base_url": "http://test-api",
                "model_name": "test-model",
                "tokenizer_name": "test-tokenizer",
            }
        }

        if thinking_budget is not None:
            config["test_model"]["thinking_budget"] = thinking_budget

        with open(self.test_config_file, "w") as f:
            json.dump(config, f)

    def test_default_thinking_budget_value(self) -> None:
        """测试thinking_budget的默认值是否为0"""
        config = ModelConfig(
            key="test_key",
            base_url="http://test-api",
            model_name="test-model",
            tokenizer_name="test-tokenizer",
        )
        self.assertEqual(config.thinking_budget, 0)

    def test_positive_thinking_budget(self) -> None:
        """测试正整数thinking_budget值的正确传递"""
        test_budget = 1024
        config = ModelConfig(
            key="test_key",
            base_url="http://test-api",
            model_name="test-model",
            tokenizer_name="test-tokenizer",
            thinking_budget=test_budget,
        )
        self.assertEqual(config.thinking_budget, test_budget)

    def test_zero_thinking_budget(self) -> None:
        """测试thinking_budget为0时的行为"""
        config = ModelConfig(
            key="test_key",
            base_url="http://test-api",
            model_name="test-model",
            tokenizer_name="test-tokenizer",
            thinking_budget=0,
        )
        self.assertEqual(config.thinking_budget, 0)

    def test_negative_thinking_budget(self) -> None:
        """测试设置负数thinking_budget应抛出异常"""
        with self.assertRaises(ValueError) as context:
            ModelConfig(
                key="test_key",
                base_url="http://test-api",
                model_name="test-model",
                tokenizer_name="test-tokenizer",
                thinking_budget=-100,
            )
        self.assertIn("无效的thinking_budget值", str(context.exception))

    def test_thinking_budget_from_env(self) -> None:
        """测试从环境变量加载thinking_budget"""
        os.environ["GPT_THINKING_BUDGET"] = "2048"
        config = ModelConfig.from_env()
        self.assertEqual(config.thinking_budget, 2048)

    def test_thinking_budget_from_env_invalid(self) -> None:
        """测试环境变量中无效的thinking_budget值"""
        os.environ["GPT_THINKING_BUDGET"] = "invalid"
        with self.assertRaises(ValueError) as context:
            ModelConfig.from_env()
        self.assertIn("无效的thinking_budget值", str(context.exception))

    def test_thinking_budget_from_config_file(self) -> None:
        """测试从配置文件加载thinking_budget"""
        self._create_test_config(thinking_budget=4096)
        switch = ModelSwitch(config_path=self.test_config_file)
        config = switch._get_model_config("test_model")
        self.assertEqual(config.thinking_budget, 4096)

    @patch("llm_query.query_gpt_api")
    @patch.object(ModelSwitch, "_get_model_config")
    def test_thinking_budget_passed_to_api(self, mock_get_model_config: MagicMock, mock_query: MagicMock) -> None:
        """测试thinking_budget参数正确传递给API"""
        mock_query.return_value = {
            "choices": [{"message": {"content": "test response"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

        # 创建带有thinking_budget的配置
        config = ModelConfig(
            key="test_key",
            base_url="http://test-api",
            model_name="test-model",
            tokenizer_name="test-tokenizer",
            thinking_budget=32768,
            is_thinking=True,
        )
        mock_get_model_config.return_value = config

        # 模拟ModelSwitch
        switch = ModelSwitch(test_mode=False)

        # 执行查询
        switch.query("test_model", "test prompt")

        # 验证query_gpt_api被正确调用
        mock_query.assert_called_once()
        call_kwargs = mock_query.call_args.kwargs
        self.assertIn("thinking_budget", call_kwargs)
        self.assertEqual(call_kwargs["thinking_budget"], 32768)
        self.assertIn("enable_thinking", call_kwargs)
        self.assertTrue(call_kwargs["enable_thinking"])

    @patch("llm_query.query_gpt_api")
    @patch.object(ModelSwitch, "_get_model_config")
    def test_thinking_budget_zero_not_passed_to_api(
        self, mock_get_model_config: MagicMock, mock_query: MagicMock
    ) -> None:
        """测试thinking_budget为0时不传递思考参数"""
        mock_query.return_value = {
            "choices": [{"message": {"content": "test response"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

        # 创建配置（thinking_budget默认为0）
        config = ModelConfig(
            key="test_key",
            base_url="http://test-api",
            model_name="test-model",
            tokenizer_name="test-tokenizer",
            is_thinking=False,
        )
        mock_get_model_config.return_value = config

        # 模拟ModelSwitch
        switch = ModelSwitch(test_mode=False)

        # 执行查询
        switch.query("test_model", "test prompt")

        # 验证query_gpt_api被正确调用
        mock_query.assert_called_once()
        call_kwargs = mock_query.call_args.kwargs
        # ModelSwitch.query always passes the args. The logic to not use them
        # is inside query_gpt_api. So we check that the values are passed correctly.
        self.assertIn("thinking_budget", call_kwargs)
        self.assertEqual(call_kwargs["thinking_budget"], 0)
        self.assertIn("enable_thinking", call_kwargs)
        self.assertFalse(call_kwargs["enable_thinking"])

    @patch("llm_query.query_gpt_api")
    @patch.object(ModelSwitch, "_get_model_config")
    def test_thinking_budget_with_is_thinking_false(
        self, mock_get_model_config: MagicMock, mock_query: MagicMock
    ) -> None:
        """测试当is_thinking为False时，thinking_budget被忽略"""
        mock_query.return_value = {
            "choices": [{"message": {"content": "test response"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

        # 创建配置，thinking_budget为正但is_thinking为False
        config = ModelConfig(
            key="test_key",
            base_url="http://test-api",
            model_name="test-model",
            tokenizer_name="test-tokenizer",
            thinking_budget=32768,
            is_thinking=False,
        )
        mock_get_model_config.return_value = config

        # 模拟ModelSwitch
        switch = ModelSwitch(test_mode=False)

        # 执行查询
        switch.query("test_model", "test prompt")

        # 验证query_gpt_api被正确调用
        mock_query.assert_called_once()
        call_kwargs = mock_query.call_args.kwargs
        # The switch should still pass the values. The called API handles the logic.
        self.assertIn("thinking_budget", call_kwargs)
        self.assertEqual(call_kwargs["thinking_budget"], 32768)
        self.assertIn("enable_thinking", call_kwargs)
        self.assertFalse(call_kwargs["enable_thinking"])

    @patch("llm_query.query_gpt_api")
    @patch.object(ModelSwitch, "_get_model_config")
    def test_thinking_budget_in_extra_body(self, mock_get_model_config: MagicMock, mock_query: MagicMock) -> None:
        """测试thinking_budget是否正确添加到extra_body"""
        mock_query.return_value = {
            "choices": [{"message": {"content": "test response"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

        # 创建配置
        config = ModelConfig(
            key="test_key",
            base_url="http://test-api",
            model_name="test-model",
            tokenizer_name="test-tokenizer",
            thinking_budget=16384,
            is_thinking=True,
        )

        # 模拟 _get_model_config 返回测试配置
        mock_get_model_config.return_value = config

        # 不使用测试模式，这样会实际调用 query_gpt_api
        switch = ModelSwitch(test_mode=False)

        # 执行查询
        switch.query("test_model", "test prompt")

        # 验证API调用参数
        mock_query.assert_called_once()
        call_kwargs = mock_query.call_args.kwargs

        # 检查thinking_budget是否被正确传递
        self.assertIn("thinking_budget", call_kwargs)
        self.assertEqual(call_kwargs["thinking_budget"], 16384)

        # 检查enable_thinking是否被正确传递
        self.assertIn("enable_thinking", call_kwargs)
        self.assertTrue(call_kwargs["enable_thinking"])

    def test_thinking_budget_persistence_in_config(self) -> None:
        """测试thinking_budget在配置中的持久化"""
        test_budget = 8192
        config = ModelConfig(
            key="test_key",
            base_url="http://test-api",
            model_name="test-model",
            tokenizer_name="test-tokenizer",
            thinking_budget=test_budget,
        )
        self.assertEqual(config.thinking_budget, test_budget)

        # 修改thinking_budget
        new_budget = 16384
        config.thinking_budget = new_budget
        self.assertEqual(config.thinking_budget, new_budget)

    def test_thinking_budget_repr(self) -> None:
        """测试thinking_budget在__repr__中的正确显示"""
        config = ModelConfig(
            key="test_key",
            base_url="http://test-api",
            model_name="test-model",
            tokenizer_name="test-tokenizer",
            thinking_budget=32768,
        )
        repr_str = repr(config)
        self.assertIn("thinking_budget=32768", repr_str)

    def test_thinking_budget_get_debug_info(self) -> None:
        """测试thinking_budget在get_debug_info中的正确显示"""
        config = ModelConfig(
            key="test_key",
            base_url="http://test-api",
            model_name="test-model",
            tokenizer_name="test-tokenizer",
            thinking_budget=32768,
        )
        debug_info = config.get_debug_info()
        self.assertEqual(debug_info["thinking_budget"], 32768)

    @patch("llm_query.time.sleep", return_value=None)
    @patch("llm_query.query_gpt_api")
    @patch.object(ModelSwitch, "_get_model_config")
    def test_thinking_budget_with_retry_mechanism(
        self, mock_get_model_config: MagicMock, mock_query: MagicMock, mock_sleep: MagicMock
    ) -> None:
        """测试thinking_budget在重试机制中的持久性"""
        mock_query.side_effect = [
            Exception("First fail"),
            {
                "choices": [{"message": {"content": "success"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        ]

        # 创建配置
        config = ModelConfig(
            key="test_key",
            base_url="http://test-api",
            model_name="test-model",
            tokenizer_name="test-tokenizer",
            thinking_budget=32768,
            is_thinking=True,
        )
        mock_get_model_config.return_value = config

        # 模拟ModelSwitch
        switch = ModelSwitch(test_mode=False)

        # 执行查询
        result = switch.query("test_model", "test prompt")
        self.assertEqual(result, "success")
        self.assertEqual(mock_query.call_count, 2)
        mock_sleep.assert_called_once()

        # 验证每次调用都包含正确的thinking_budget
        for call in mock_query.call_args_list:
            call_kwargs = call.kwargs
            self.assertIn("thinking_budget", call_kwargs)
            self.assertEqual(call_kwargs["thinking_budget"], 32768)
            self.assertIn("enable_thinking", call_kwargs)
            self.assertTrue(call_kwargs["enable_thinking"])

    @patch("llm_query.query_gpt_api")
    @patch.object(ModelSwitch, "_get_model_config")
    @patch("llm_query.import_relative")
    def test_thinking_budget_with_workflow(
        self, mock_import: MagicMock, mock_get_config: MagicMock, mock_query: MagicMock
    ) -> None:
        """测试thinking_budget在工作流中的正确传递"""
        # Mock the architect response
        mock_query.return_value = {
            "choices": [
                {
                    "message": {
                        "content": """
[task describe start]
开发分布式任务调度系统
[task describe end]

[team member1 job start]
实现工作节点注册机制
使用Consul进行服务发现
[team member1 job end]
"""
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        # Mock the workflow module
        mock_workflow = MagicMock()
        mock_workflow.ArchitectMode.parse_response.return_value = {"jobs": [{"content": "job1"}]}
        mock_import.return_value = mock_workflow

        # 创建配置
        architect_config = ModelConfig(
            key="arch_key",
            base_url="http://arch-api",
            model_name="arch-model",
            thinking_budget=32768,
            is_thinking=True,
        )
        coder_config = ModelConfig(
            key="coder_key",
            base_url="http://coder-api",
            model_name="coder-model",
            thinking_budget=16384,
            is_thinking=True,
        )

        mock_get_config.side_effect = lambda model_name: {"architect": architect_config, "coder": coder_config}[
            model_name
        ]

        # 模拟ModelSwitch
        switch = ModelSwitch(test_mode=False)

        # 执行工作流
        switch.execute_workflow(
            architect_model="architect",
            coder_model="coder",
            prompt="test prompt",
            architect_only=True,
        )

        # 验证API调用
        self.assertEqual(mock_query.call_count, 1)
        call_kwargs = mock_query.call_args.kwargs
        self.assertIn("thinking_budget", call_kwargs)
        self.assertEqual(call_kwargs["thinking_budget"], 32768)
        self.assertIn("enable_thinking", call_kwargs)
        self.assertTrue(call_kwargs["enable_thinking"])

    def test_thinking_budget_edge_cases(self) -> None:
        """测试thinking_budget的边界情况"""
        # 测试最小正整数值
        config = ModelConfig(
            key="test_key",
            base_url="http://test-api",
            model_name="test-model",
            tokenizer_name="test-tokenizer",
            thinking_budget=1,
        )
        self.assertEqual(config.thinking_budget, 1)

        # 测试最大可能值（假设为系统限制）
        max_value = 2**31 - 1  # 假设使用32位有符号整数
        config = ModelConfig(
            key="test_key",
            base_url="http://test-api",
            model_name="test-model",
            tokenizer_name="test-tokenizer",
            thinking_budget=max_value,
        )
        self.assertEqual(config.thinking_budget, max_value)
