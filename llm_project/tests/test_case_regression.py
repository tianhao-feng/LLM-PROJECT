import json
import os
import unittest
import uuid
from unittest.mock import patch

from autofpga.case_regression import normalize_regression_tools, run_case_regression
from autofpga.config import build_context


def reset_tmp(name):
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "codex_test_tmp", f"{name}_{uuid.uuid4().hex}")
    os.makedirs(path)
    return path


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class CaseRegressionTests(unittest.TestCase):
    def test_normalize_regression_tools(self):
        self.assertEqual(normalize_regression_tools("lint,sim,build"), ["iverilog", "modelsim", "vivado"])
        self.assertEqual(normalize_regression_tools(["iverilog", "iverilog"]), ["iverilog"])

    def test_run_case_regression_copies_case_and_runs_tools(self):
        root = reset_tmp("case_regression")
        examples = os.path.join(root, "examples")
        case = os.path.join(examples, "demo")
        write(os.path.join(case, "README.md"), "# Demo\n\n" + "A complete regression fixture. " * 40)
        write(os.path.join(case, "requirement.json"), json.dumps({"user_requirement": "Create demo."}))
        write(
            os.path.join(case, "expected_manifest.json"),
            json.dumps({"design": {"top_module": "demo_top", "testbench_module": "tb_demo_top"}}),
        )
        write(os.path.join(case, "src", "demo_top.v"), "module demo_top(input clk); endmodule\n")
        write(
            os.path.join(case, "tb_top_module.v"),
            "module tb_demo_top; reg clk; demo_top dut(.clk(clk)); initial begin if (1==1) $display(\"SIM_RESULT: PASSED\"); else $display(\"SIM_RESULT: FAILED\"); $stop; end endmodule\n",
        )
        write(
            os.path.join(case, "constraints.xdc"),
            "set_property PACKAGE_PIN K17 [get_ports clk]\nset_property IOSTANDARD LVCMOS33 [get_ports clk]\n",
        )
        ctx = build_context(script_dir=root, project_name="demo", auto_timestamp=False)

        with patch("autofpga.case_regression.run_iverilog_checks", return_value=(True, "PASS")) as iverilog:
            report = run_case_regression(ctx, examples, tools="iverilog")

        self.assertEqual(report["failed"], 0)
        self.assertEqual(report["passed"], 1)
        self.assertTrue(os.path.exists(report["report_file"]))
        self.assertTrue(os.path.exists(os.path.join(report["work_root"], "demo", "src", "demo_top.v")))
        iverilog.assert_called_once()

    def test_run_case_regression_marks_tool_failure(self):
        root = reset_tmp("case_regression_fail")
        examples = os.path.join(root, "examples")
        case = os.path.join(examples, "demo")
        write(os.path.join(case, "README.md"), "# Demo\n\n" + "A complete regression fixture. " * 40)
        write(os.path.join(case, "requirement.json"), json.dumps({"user_requirement": "Create demo."}))
        write(
            os.path.join(case, "expected_manifest.json"),
            json.dumps({"design": {"top_module": "demo_top", "testbench_module": "tb_demo_top"}}),
        )
        write(os.path.join(case, "src", "demo_top.v"), "module demo_top(input clk); endmodule\n")
        write(
            os.path.join(case, "tb_top_module.v"),
            "module tb_demo_top; reg clk; demo_top dut(.clk(clk)); initial begin if (1==1) $display(\"SIM_RESULT: PASSED\"); else $display(\"SIM_RESULT: FAILED\"); $stop; end endmodule\n",
        )
        write(
            os.path.join(case, "constraints.xdc"),
            "set_property PACKAGE_PIN K17 [get_ports clk]\nset_property IOSTANDARD LVCMOS33 [get_ports clk]\n",
        )
        ctx = build_context(script_dir=root, project_name="demo", auto_timestamp=False)

        with patch("autofpga.case_regression.run_iverilog_checks", return_value=(False, "bad")):
            report = run_case_regression(ctx, examples, tools="iverilog")

        self.assertEqual(report["failed"], 1)
        self.assertFalse(report["results"][0]["tools"][0]["ok"])


if __name__ == "__main__":
    unittest.main()
