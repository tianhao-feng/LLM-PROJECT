import unittest
from unittest.mock import patch

from autofpga.config import DEFAULT_CONFIG, build_context
from autofpga.main import main, merge_config, parse_args


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

    def test_rag_cli_overrides(self):
        config = merge_config(
            parse_args(
                [
                    "--rag-top-k",
                    "7",
                    "--rag-candidate-k",
                    "31",
                    "--rag-reindex",
                    "--rag-clear-index",
                    "--rag-hide-sources",
                    "--rag-dry-run",
                    "--rag-source",
                    "knowledge_base",
                ]
            )
        )

        self.assertEqual(config["rag_top_k"], 7)
        self.assertEqual(config["rag_candidate_k"], 31)
        self.assertTrue(config["rag_reindex"])
        self.assertTrue(config["rag_clear_index"])
        self.assertFalse(config["rag_show_sources"])
        self.assertTrue(config["rag_dry_run"])
        self.assertEqual(config["rag_sources"], ["knowledge_base"])

    def test_rag_query_cli_args(self):
        args = parse_args(["--rag-query", "create_clock usage", "--rag-skill", "TABLE"])

        self.assertEqual(args.rag_query, "create_clock usage")
        self.assertEqual(args.rag_skill, "TABLE")

    def test_rag_query_bypasses_pipeline(self):
        with patch("autofpga.main.configure_llm_from_context"), patch("autofpga.main.execute_rag_skill") as rag, patch(
            "autofpga.main.run_pipeline"
        ) as pipeline:
            main(["--rag-query", "create_clock usage", "--rag-skill", "CONCEPT"])

        rag.assert_called_once()
        self.assertEqual(rag.call_args.args[1], "create_clock usage")
        self.assertEqual(rag.call_args.args[2], "CONCEPT")
        pipeline.assert_not_called()

    def test_rag_dump_index_bypasses_pipeline(self):
        with patch("autofpga.main.configure_llm_from_context"), patch("autofpga.main.dump_rag_index") as dump, patch(
            "autofpga.main.run_pipeline"
        ) as pipeline:
            main(["--rag-dump-index"])

        dump.assert_called_once()
        pipeline.assert_not_called()


if __name__ == "__main__":
    unittest.main()
