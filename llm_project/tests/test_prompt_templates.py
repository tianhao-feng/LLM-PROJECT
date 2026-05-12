import unittest

from autofpga.prompt_templates import load_prompt_template, parse_prompt_metadata, render_prompt


class PromptTemplateTests(unittest.TestCase):
    def test_coder_module_template_renders_core_fields(self):
        prompt = render_prompt(
            "coder_module.md",
            sys_spec="system spec",
            global_arch='{"modules": []}',
            verilog_rules="Verilog-2001 rules",
            filename="demo_top.v",
            module_name="demo_top",
            port_spec="- input 1 clk",
            description="demo module",
            retry_hint="",
        )

        self.assertIn("Prompt-Name: coder_module", prompt)
        self.assertIn("编写 `demo_top.v`", prompt)
        self.assertIn("module demo_top", prompt)
        self.assertIn("Verilog-2001 rules", prompt)

    def test_prompt_metadata_parses_name_and_version(self):
        metadata = parse_prompt_metadata(load_prompt_template("coder_module.md"))

        self.assertEqual(metadata["prompt_name"], "coder_module")
        self.assertEqual(metadata["prompt_version"], "1")

    def test_repair_module_template_renders_repair_contract(self):
        prompt = render_prompt(
            "repair_module.md",
            sys_spec="system spec",
            verilog_rules="Verilog-2001 rules",
            error_context="syntax error",
            targeted_code="module bad; endmodule",
            error_memory="old lesson",
        )

        self.assertIn("Prompt-Name: repair_module", prompt)
        self.assertIn("syntax error", prompt)
        self.assertIn("// File: top_module.v", prompt)
        self.assertIn("只输出被修改的文件", prompt)

    def test_testbench_templates_render_contracts(self):
        generate_prompt = render_prompt(
            "testbench_generate.md",
            all_rtl="module demo_top; endmodule",
            user_requirement="verify demo",
            verilog_rules="Verilog-2001 rules",
            dut_module="demo_top",
        )
        repair_prompt = render_prompt(
            "testbench_repair.md",
            all_rtl="module demo_top; endmodule",
            user_requirement="verify demo",
            verilog_rules="Verilog-2001 rules",
            error_msg="SIM_RESULT: FAILED",
            current_tb="bad tb",
            dut_module="demo_top",
        )

        self.assertIn("Prompt-Name: testbench_generate", generate_prompt)
        self.assertIn("Prompt-Name: testbench_repair", repair_prompt)
        self.assertIn("tb_demo_top", generate_prompt)
        self.assertIn("SIM_RESULT: PASSED", repair_prompt)
        self.assertIn("$stop", repair_prompt)

    def test_architect_readme_template_renders_required_sections(self):
        prompt = render_prompt(
            "architect_readme.md",
            requirement="Create a counter.",
            xilinx_notes="create_clock notes",
        )

        self.assertIn("Prompt-Name: architect_readme", prompt)
        self.assertIn("Create a counter.", prompt)
        self.assertIn("## 8. Testbench 验收标准", prompt)
        self.assertIn("tb_top_module.v", prompt)
        self.assertIn("create_clock notes", prompt)

    def test_render_prompt_reports_missing_value(self):
        with self.assertRaisesRegex(KeyError, "missing value"):
            render_prompt("coder_module.md", sys_spec="only one")


if __name__ == "__main__":
    unittest.main()
