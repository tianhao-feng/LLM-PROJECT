import os
import unittest
from unittest.mock import Mock, patch

from autofpga.llm_client import LLMClient, LLMSettings


class LLMClientTests(unittest.TestCase):
    def test_openai_compatible_chat_parses_content(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}

        with patch.dict(os.environ, {"TEST_API_KEY": "secret"}), patch("requests.post", return_value=response) as post:
            client = LLMClient(
                LLMSettings(
                    provider="deepseek",
                    model="deepseek-chat",
                    base_url="https://api.example.com",
                    api_key_env="TEST_API_KEY",
                )
            )

            self.assertEqual(client.chat("hello"), "ok")
            self.assertEqual(post.call_args.args[0], "https://api.example.com/chat/completions")
            self.assertIn("Authorization", post.call_args.kwargs["headers"])

    def test_openai_compatible_chat_reports_missing_key(self):
        with patch.dict(os.environ, {}, clear=True):
            client = LLMClient(LLMSettings(provider="deepseek", api_key_env="MISSING_KEY"))

            result = client.chat("hello")

            self.assertIn("未配置 API Key", result)

    def test_ollama_chat_parses_content(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"message": {"content": "local-ok"}}

        with patch("requests.post", return_value=response) as post:
            client = LLMClient(
                LLMSettings(
                    provider="ollama",
                    model="qwen2.5-coder:7b",
                    base_url="http://localhost:11434",
                )
            )

            self.assertEqual(client.chat("hello"), "local-ok")
            self.assertEqual(post.call_args.args[0], "http://localhost:11434/api/chat")

    def test_ollama_embedding_parses_vector(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"embedding": [0.1, 0.2, 0.3]}

        with patch("requests.post", return_value=response):
            client = LLMClient(LLMSettings(embedding_provider="ollama"))

            self.assertEqual(client.embedding("hello"), [0.1, 0.2, 0.3])


if __name__ == "__main__":
    unittest.main()
