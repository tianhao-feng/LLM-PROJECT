import json
import io
import os
import unittest
import uuid
from contextlib import redirect_stdout
from unittest.mock import patch

from autofpga.config import build_context
from autofpga.pipeline import execute_coding_pipeline


class PipelineE2ETests(unittest.TestCase):
    def test_pipeline_completes_with_mocked_agents_and_tools(self):
        root = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "codex_test_tmp",
            f"pipeline_e2e_{uuid.uuid4().hex}",
        )
        ctx = build_context(script_dir=root, project_name="demo", auto_timestamp=False, max_retries=2)

        arch = {
            "top_module": "demo_top",
            "top_file": "demo_top.v",
            "verilog_standard": "Verilog-2001",
            "modules": [
                {
                    "filename": "demo_top.v",
                    "module_name": "demo_top",
                    "is_top": True,
                    "ports": [
                        {"name": "clk", "direction": "input", "width": "1", "description": "clock"},
                        {"name": "rst_n", "direction": "input", "width": "1", "description": "reset"},
                        {"name": "led", "direction": "output", "width": "1", "description": "led"},
                    ],
                    "description": "toggle LED",
                    "instances": [],
                }
            ],
            "testbench_goals": ["check reset and toggle"],
        }

        def fake_architect(fake_ctx, requirement):
            with open(fake_ctx.readme_file, "w", encoding="utf-8") as f:
                f.write("# Demo\n\nMocked pipeline README.\n")
            return arch

        def fake_coder(fake_ctx, arch_json, error_context=None):
            os.makedirs(fake_ctx.src_dir, exist_ok=True)
            with open(os.path.join(fake_ctx.src_dir, "demo_top.v"), "w", encoding="utf-8") as f:
                f.write(
                    """
module demo_top (
    input clk,
    input rst_n,
    output reg led
);
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        led <= 1'b0;
    end else begin
        led <= ~led;
    end
end
endmodule
""".strip()
                    + "\n"
                )

        def fake_testbench(fake_ctx, error_msg=None, current_tb=None):
            tb = """
module tb_demo_top;
reg clk;
reg rst_n;
wire led;
demo_top dut(.clk(clk), .rst_n(rst_n), .led(led));
initial begin clk = 1'b0; forever #5 clk = ~clk; end
initial begin
    rst_n = 1'b0;
    #12;
    rst_n = 1'b1;
    @(posedge clk);
    #1;
    if (led == 1'b1) begin
        $display("SIM_RESULT: PASSED");
    end else begin
        $display("SIM_RESULT: FAILED");
    end
    $stop;
end
endmodule
""".strip()
            with open(fake_ctx.tb_file, "w", encoding="utf-8") as f:
                f.write(tb + "\n")
            return tb

        def fake_xdc(fake_ctx, error_msg=None, current_xdc=None):
            xdc = "set_property PACKAGE_PIN K17 [get_ports clk]\n"
            with open(fake_ctx.xdc_file, "w", encoding="utf-8") as f:
                f.write(xdc)
            return xdc

        with patch("autofpga.pipeline.agent_architect", side_effect=fake_architect), patch(
            "autofpga.pipeline.agent_coder", side_effect=fake_coder
        ), patch("autofpga.pipeline.task_generate_testbench", side_effect=fake_testbench), patch(
            "autofpga.pipeline.task_generate_xdc", side_effect=fake_xdc
        ), patch(
            "autofpga.pipeline.run_iverilog_checks", return_value=(True, "PASS")
        ), patch(
            "autofpga.pipeline.task_run_modelsim", return_value=(True, "SIM_RESULT: PASSED")
        ), patch(
            "autofpga.pipeline.run_vivado_build", return_value=(True, "")
        ), patch(
            "autofpga.pipeline.parse_vivado_reports"
        ):
            with redirect_stdout(io.StringIO()):
                execute_coding_pipeline(ctx, "Create a demo toggle.")

        with open(ctx.manifest_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        self.assertEqual(manifest["status"], "succeeded")
        self.assertEqual(manifest["stage"], "complete")
        self.assertEqual(manifest["design"]["top_module"], "demo_top")
        self.assertEqual(manifest["design"]["testbench_module"], "tb_demo_top")
        self.assertTrue(os.path.exists(os.path.join(ctx.src_dir, "demo_top.v")))
        self.assertTrue(os.path.exists(ctx.tb_file))
        self.assertTrue(os.path.exists(ctx.xdc_file))
        stages = [entry["stage"] for entry in manifest["history"]]
        self.assertIn("lint", stages)
        self.assertIn("simulate", stages)
        self.assertIn("vivado_build", stages)


if __name__ == "__main__":
    unittest.main()
