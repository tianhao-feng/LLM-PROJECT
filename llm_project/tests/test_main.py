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

    def test_board_pins_file_cli_override(self):
        config = merge_config(parse_args(["--board-pins-file", "knowledge_base/boards/demo.json"]))

        self.assertEqual(config["board_pins_file"], "knowledge_base/boards/demo.json")

    def test_llm_trace_cli_override(self):
        config = merge_config(parse_args(["--llm-trace", "--llm-trace-file", "runs/trace.jsonl"]))

        self.assertTrue(config["llm_trace"])
        self.assertEqual(config["llm_trace_file"], "runs/trace.jsonl")

    def test_doctor_cli_args(self):
        args = parse_args(["--doctor", "--doctor-strict", "--doctor-json", "--doctor-smoke"])

        self.assertTrue(args.doctor)
        self.assertTrue(args.doctor_strict)
        self.assertTrue(args.doctor_json)
        self.assertTrue(args.doctor_smoke)

    def test_audit_examples_cli_args(self):
        args = parse_args(["--audit-examples", "--examples-dir", "fixtures", "--audit-json", "--case-index"])

        self.assertTrue(args.audit_examples)
        self.assertEqual(args.examples_dir, "fixtures")
        self.assertTrue(args.audit_json)
        self.assertTrue(args.case_index)

    def test_audit_cases_cli_alias_args(self):
        args = parse_args(["--audit-cases", "--case-index-file", "examples/index.json"])

        self.assertTrue(args.audit_cases)
        self.assertEqual(args.case_index_file, "examples/index.json")

    def test_capture_case_evidence_cli_args(self):
        args = parse_args(["--capture-case-evidence", "examples/demo", "--manifest", "run_manifest.json", "--copy-manifest"])

        self.assertEqual(args.capture_case_evidence, "examples/demo")
        self.assertEqual(args.manifest, "run_manifest.json")
        self.assertTrue(args.copy_manifest)

    def test_regression_cases_cli_args(self):
        args = parse_args(["--regression-cases", "--regression-tools", "iverilog,modelsim", "--regression-report", "report.json"])

        self.assertTrue(args.regression_cases)
        self.assertEqual(args.regression_tools, "iverilog,modelsim")
        self.assertEqual(args.regression_report, "report.json")

    def test_audit_prompts_cli_args(self):
        args = parse_args(["--audit-prompts", "--audit-json"])

        self.assertTrue(args.audit_prompts)
        self.assertTrue(args.audit_json)

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

    def test_doctor_bypasses_pipeline(self):
        report = {"overall": "ok", "python": "3.x", "platform": "test", "items": []}
        with patch("autofpga.main.collect_doctor_report", return_value=report) as doctor, patch(
            "autofpga.main.configure_llm_from_context"
        ) as configure, patch("autofpga.main.run_pipeline") as pipeline:
            main(["--doctor"])

        doctor.assert_called_once()
        configure.assert_not_called()
        pipeline.assert_not_called()

    def test_audit_examples_bypasses_pipeline(self):
        report = {"total": 1, "passed": 1, "failed": 0, "results": []}
        with patch("autofpga.main.audit_examples", return_value=report) as audit, patch(
            "autofpga.main.configure_llm_from_context"
        ) as configure, patch("autofpga.main.run_pipeline") as pipeline:
            main(["--audit-examples"])

        audit.assert_called_once()
        configure.assert_not_called()
        pipeline.assert_not_called()

    def test_audit_cases_alias_bypasses_pipeline_and_writes_index(self):
        report = {"total": 1, "passed": 1, "failed": 0, "results": []}
        with patch("autofpga.main.audit_examples", return_value=report) as audit, patch(
            "autofpga.main.configure_llm_from_context"
        ) as configure, patch("autofpga.main.run_pipeline") as pipeline:
            main(["--audit-cases", "--case-index"])

        audit.assert_called_once()
        self.assertTrue(audit.call_args.kwargs["write_index"])
        configure.assert_not_called()
        pipeline.assert_not_called()

    def test_audit_examples_fails_when_no_examples_found(self):
        report = {"total": 0, "passed": 0, "failed": 0, "results": []}
        with patch("autofpga.main.audit_examples", return_value=report), patch(
            "autofpga.main.configure_llm_from_context"
        ), patch("autofpga.main.run_pipeline"):
            with self.assertRaises(SystemExit):
                main(["--audit-examples"])

    def test_capture_case_evidence_bypasses_pipeline(self):
        result = {"evidence_path": "examples/demo/run_evidence.json", "copied_manifest": "", "validation_problems": []}
        with patch("autofpga.main.capture_case_evidence", return_value=result) as capture, patch(
            "autofpga.main.configure_llm_from_context"
        ) as configure, patch("autofpga.main.run_pipeline") as pipeline:
            main(["--capture-case-evidence", "examples/demo", "--manifest", "run_manifest.json"])

        capture.assert_called_once()
        configure.assert_not_called()
        pipeline.assert_not_called()

    def test_regression_cases_bypasses_pipeline(self):
        report = {"total": 1, "passed": 1, "failed": 0, "tools": ["iverilog"], "results": [], "report_file": "report.json"}
        with patch("autofpga.main.run_case_regression", return_value=report) as regression, patch(
            "autofpga.main.configure_llm_from_context"
        ) as configure, patch("autofpga.main.run_pipeline") as pipeline:
            main(["--regression-cases", "--regression-tools", "iverilog"])

        regression.assert_called_once()
        configure.assert_not_called()
        pipeline.assert_not_called()

    def test_audit_prompts_bypasses_pipeline(self):
        report = {"total": 5, "passed": 5, "failed": 0, "results": []}
        with patch("autofpga.main.audit_prompt_templates", return_value=report) as audit, patch(
            "autofpga.main.configure_llm_from_context"
        ) as configure, patch("autofpga.main.run_pipeline") as pipeline:
            main(["--audit-prompts"])

        audit.assert_called_once()
        configure.assert_not_called()
        pipeline.assert_not_called()


if __name__ == "__main__":
    unittest.main()
