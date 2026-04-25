import unittest

from autofpga.config import DEFAULT_CONFIG, build_context
from autofpga.main import merge_config, parse_args


class MainConfigTests(unittest.TestCase):
    def test_ollama_provider_gets_local_defaults(self):
        config = merge_config(parse_args(["--llm-provider", "ollama"]))

        self.assertEqual(config["llm_provider"], "ollama")
        self.assertEqual(config["llm_base_url"], "http://localhost:11434")
        self.assertNotEqual(config["llm_model"], "deepseek-chat")

    def test_tool_timeout_cli_overrides(self):
        config = merge_config(
            parse_args(["--iverilog-timeout", "7", "--modelsim-timeout", "8", "--vivado-timeout", "9"])
        )

        self.assertEqual(config["iverilog_timeout"], 7)
        self.assertEqual(config["modelsim_timeout"], 8)
        self.assertEqual(config["vivado_timeout"], 9)

    def test_cli_defaults_match_build_context_tool_paths(self):
        config = merge_config(parse_args([]))
        ctx = build_context()

        self.assertEqual(config["modelsim_path"], DEFAULT_CONFIG["modelsim_path"])
        self.assertEqual(config["modelsim_path"], ctx.modelsim_path)
        self.assertEqual(config["vivado_path"], DEFAULT_CONFIG["vivado_path"])
        self.assertEqual(config["user_requirement"], DEFAULT_CONFIG["user_requirement"])

    def test_manifest_validation_cli_args(self):
        args = parse_args(["--validate-manifest", "run_manifest.json", "--expected-manifest", "expected_manifest.json"])

        self.assertEqual(args.validate_manifest, "run_manifest.json")
        self.assertEqual(args.expected_manifest, "expected_manifest.json")


if __name__ == "__main__":
    unittest.main()
