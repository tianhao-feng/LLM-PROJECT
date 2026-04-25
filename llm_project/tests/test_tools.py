import os
import unittest
import uuid
from unittest.mock import Mock, patch

import subprocess

from autofpga.tools import evaluate_modelsim_output, run_command, run_vivado_build, task_run_modelsim


class ToolValidationTests(unittest.TestCase):
    def test_modelsim_accepts_single_pass(self):
        ok, message = evaluate_modelsim_output("SIM_RESULT: PASSED\n", 0)

        self.assertTrue(ok)
        self.assertIn("PASSED", message)

    def test_modelsim_rejects_missing_pass(self):
        ok, message = evaluate_modelsim_output("simulation stopped\n", 0)

        self.assertFalse(ok)
        self.assertIn("未输出明确通过标志", message)

    def test_modelsim_rejects_failed_marker_even_with_pass(self):
        ok, _ = evaluate_modelsim_output("SIM_RESULT: PASSED\nSIM_RESULT: FAILED\n", 0)

        self.assertFalse(ok)

    def test_modelsim_rejects_multiple_passes(self):
        ok, message = evaluate_modelsim_output("SIM_RESULT: PASSED\nSIM_RESULT: PASSED\n", 0)

        self.assertFalse(ok)
        self.assertIn("多个", message)

    def test_modelsim_rejects_nonzero_returncode(self):
        ok, message = evaluate_modelsim_output("SIM_RESULT: PASSED\n", 1)

        self.assertFalse(ok)
        self.assertIn("返回码异常", message)

    def test_run_command_success(self):
        completed = subprocess.CompletedProcess(["tool"], 0, stdout="ok", stderr="")
        with patch("autofpga.tools.missing_executable", return_value=""), patch("subprocess.run", return_value=completed):
            result = run_command(["tool", "--version"], label="Tool")

        self.assertTrue(result.ok)
        self.assertEqual(result.stdout, "ok")

    def test_run_command_reports_missing_tool(self):
        result = run_command(["definitely_missing_tool_for_autofpga"], label="MissingTool")

        self.assertTrue(result.missing_tool)
        self.assertIn("工具未找到", result.failure_summary())

    def test_run_command_reports_timeout(self):
        timeout = subprocess.TimeoutExpired(["tool"], timeout=1, output="partial", stderr="late")
        with patch("autofpga.tools.missing_executable", return_value=""), patch("subprocess.run", side_effect=timeout):
            result = run_command(["tool"], label="SlowTool", timeout=1)

        self.assertTrue(result.timeout)
        self.assertIn("超时", result.failure_summary())

    def test_modelsim_run_do_uses_parsed_testbench_module(self):
        root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "codex_test_tmp", f"modelsim_{uuid.uuid4().hex}")
        src_dir = os.path.join(root, "src")
        sim_dir = os.path.join(root, "sim")
        os.makedirs(src_dir)
        os.makedirs(sim_dir)
        tb_file = os.path.join(root, "tb_top_module.v")
        with open(os.path.join(src_dir, "counter_top.v"), "w", encoding="utf-8") as f:
            f.write("module counter_top(input clk); endmodule\n")
        with open(tb_file, "w", encoding="utf-8") as f:
            f.write("module tb_counter_top; counter_top dut(); initial begin if (1==1) $display(\"SIM_RESULT: PASSED\"); else $display(\"SIM_RESULT: FAILED\"); $stop; end endmodule\n")

        class Ctx:
            pass

        ctx = Ctx()
        ctx.src_dir = src_dir
        ctx.sim_dir = sim_dir
        ctx.tb_file = tb_file
        ctx.modelsim_path = "vsim"
        ctx.modelsim_timeout = 60

        with patch("autofpga.tools.run_command") as mocked_run:
            mocked_run.return_value.missing_tool = False
            mocked_run.return_value.timeout = False
            mocked_run.return_value.exception = None
            mocked_run.return_value.stdout = "SIM_RESULT: PASSED\n"
            mocked_run.return_value.returncode = 0

            ok, _ = task_run_modelsim(ctx)

        self.assertTrue(ok)
        with open(os.path.join(sim_dir, "run.do"), "r", encoding="utf-8") as f:
            run_do = f.read()
        self.assertIn("work.tb_counter_top", run_do)

    def test_vivado_build_keeps_scripts_and_logs_under_runs(self):
        root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "codex_test_tmp", f"vivado_{uuid.uuid4().hex}")
        src_dir = os.path.join(root, "src")
        run_dir = os.path.join(root, "runs")
        output_dir = os.path.join(run_dir, "vivado_out")
        os.makedirs(src_dir)
        os.makedirs(run_dir)
        xdc_file = os.path.join(root, "constraints.xdc")
        with open(os.path.join(src_dir, "demo_top.v"), "w", encoding="utf-8") as f:
            f.write("module demo_top(input clk, output led); assign led = clk; endmodule\n")
        with open(xdc_file, "w", encoding="utf-8") as f:
            f.write("set_property PACKAGE_PIN E3 [get_ports clk]\n")

        class Ctx:
            pass

        ctx = Ctx()
        ctx.save_dir = root
        ctx.run_dir = run_dir
        ctx.src_dir = src_dir
        ctx.output_dir = output_dir
        ctx.xdc_file = xdc_file
        ctx.vivado_path = "vivado"
        ctx.vivado_timeout = 7200
        ctx.fpga_part = "xc7z020clg400-2"

        def fake_streaming_command(command, label=None, cwd=None, timeout=None, on_line=None):
            if on_line:
                on_line("write_bitstream completed successfully\n")
            result = Mock()
            result.missing_tool = False
            result.timeout = False
            result.exception = None
            result.returncode = 0
            result.output = ""
            return result

        with patch("autofpga.tools.run_streaming_command", side_effect=fake_streaming_command) as mocked_run:
            ok, _ = run_vivado_build(ctx)

        self.assertTrue(ok)
        run_tcl = os.path.join(run_dir, "scripts", "run.tcl")
        log_dir = os.path.join(run_dir, "vivado_logs")
        self.assertTrue(os.path.exists(run_tcl))
        self.assertFalse(os.path.exists(os.path.join(root, "run.tcl")))

        kwargs = mocked_run.call_args.kwargs
        command = mocked_run.call_args.args[0]
        self.assertEqual(kwargs["cwd"], log_dir)
        self.assertIn("-source", command)
        self.assertIn(run_tcl, command)
        self.assertIn("-log", command)
        self.assertIn(os.path.join(log_dir, "vivado.log"), command)
        self.assertIn("-journal", command)
        self.assertIn(os.path.join(log_dir, "vivado.jou"), command)


if __name__ == "__main__":
    unittest.main()
