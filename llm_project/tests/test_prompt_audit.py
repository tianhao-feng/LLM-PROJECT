import os
import unittest
import uuid

from autofpga.prompt_audit import audit_prompt_template, audit_prompt_templates, extract_template_variables


def reset_tmp(name):
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "codex_test_tmp", f"{name}_{uuid.uuid4().hex}")
    os.makedirs(path)
    return path


class PromptAuditTests(unittest.TestCase):
    def test_extract_template_variables(self):
        variables = extract_template_variables("Hello {name}, build {module.name} and {ports[0]}")

        self.assertEqual(variables, {"name", "module", "ports"})

    def test_current_prompt_templates_pass_audit(self):
        report = audit_prompt_templates()

        self.assertGreaterEqual(report["total"], 5)
        self.assertEqual(report["failed"], 0, report)

    def test_prompt_template_audit_reports_missing_metadata_and_keyword(self):
        result = audit_prompt_template("coder_module.md", "Prompt-Name: coder_module\n{sys_spec}\n")

        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("Prompt-Version" in problem for problem in result["problems"]))
        self.assertTrue(any("missing variables" in problem for problem in result["problems"]))
        self.assertTrue(any("missing required keyword" in problem for problem in result["problems"]))


if __name__ == "__main__":
    unittest.main()
