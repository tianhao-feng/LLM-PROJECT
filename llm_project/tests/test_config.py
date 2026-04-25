import os
import json
import unittest
import uuid


from autofpga.config import DEFAULT_CONFIG, DEFAULT_REQUIREMENT, build_context, runtime_config_dict, write_run_manifest


def reset_tmp(name):
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "codex_test_tmp", f"{name}_{uuid.uuid4().hex}")
    os.makedirs(path)
    return path


class ConfigTests(unittest.TestCase):
    def test_default_requirement_is_counter_and_manifest_records_it(self):
        tmp = reset_tmp("config_default_requirement")
        ctx = build_context(script_dir=tmp, project_name="demo", auto_timestamp=False)

        self.assertIn("计数器", DEFAULT_REQUIREMENT)
        self.assertEqual(DEFAULT_CONFIG["user_requirement"], DEFAULT_REQUIREMENT)
        self.assertIn("计数器", ctx.user_requirement)
        self.assertIn("user_requirement", runtime_config_dict(ctx))

    def test_build_context_uses_runs_for_runtime_outputs(self):
        with self.subTest("runtime paths"):
            tmp = reset_tmp("config_paths")
            ctx = build_context(script_dir=tmp, project_name="demo", auto_timestamp=False)

            self.assertEqual(ctx.save_dir, os.path.join(tmp, "projects", "demo"))
            self.assertEqual(ctx.output_dir, os.path.join(ctx.save_dir, "runs", "vivado_out"))
            self.assertEqual(ctx.sim_dir, os.path.join(ctx.save_dir, "runs", "sim_work"))
            self.assertEqual(ctx.vector_db_dir, os.path.join(tmp, "runs", "vector_db"))
            self.assertEqual(ctx.error_kb_file, os.path.join(tmp, "runs", "error_memory.txt"))
            self.assertEqual(ctx.iverilog_timeout, 60)
            self.assertEqual(ctx.modelsim_timeout, 60)
            self.assertEqual(ctx.vivado_timeout, 7200)

    def test_build_context_accepts_tool_timeouts(self):
        tmp = reset_tmp("config_tool_timeouts")
        ctx = build_context(
            script_dir=tmp,
            project_name="demo",
            auto_timestamp=False,
            iverilog_timeout=11,
            modelsim_timeout=22,
            vivado_timeout=33,
        )

        self.assertEqual(ctx.iverilog_timeout, 11)
        self.assertEqual(ctx.modelsim_timeout, 22)
        self.assertEqual(ctx.vivado_timeout, 33)

    def test_build_only_requires_explicit_project_dir(self):
        tmp = reset_tmp("config_build_only_required")
        with self.assertRaisesRegex(ValueError, "project_dir"):
            build_context(script_dir=tmp, work_mode="BUILD_ONLY")

    def test_build_only_accepts_named_project_with_src(self):
        tmp = reset_tmp("config_build_only_existing")
        src_dir = os.path.join(tmp, "projects", "existing", "src")
        os.makedirs(src_dir)

        ctx = build_context(script_dir=tmp, work_mode="BUILD_ONLY", project_dir="existing")

        self.assertEqual(ctx.save_dir, os.path.join(tmp, "projects", "existing"))
        self.assertEqual(ctx.src_dir, src_dir)

    def test_manifest_collects_design_reports_and_bitstream(self):
        tmp = reset_tmp("manifest_enhanced")
        ctx = build_context(script_dir=tmp, project_name="demo", auto_timestamp=False)
        os.makedirs(ctx.src_dir, exist_ok=True)
        os.makedirs(ctx.output_dir, exist_ok=True)
        os.makedirs(os.path.join(ctx.output_dir, "ai_project.runs", "impl_1"), exist_ok=True)
        with open(os.path.join(ctx.src_dir, "demo_top.v"), "w", encoding="utf-8") as f:
            f.write("module demo_top(input clk); endmodule\n")
        with open(ctx.tb_file, "w", encoding="utf-8") as f:
            f.write("module tb_demo_top; demo_top dut(); initial begin if (1==1) $display(\"SIM_RESULT: PASSED\"); else $display(\"SIM_RESULT: FAILED\"); $stop; end endmodule\n")
        with open(os.path.join(ctx.output_dir, "ai_project.runs", "impl_1", "demo_top.bit"), "w", encoding="utf-8") as f:
            f.write("bit")
        with open(os.path.join(ctx.output_dir, "report_timing.rpt"), "w", encoding="utf-8") as f:
            f.write("All user specified timing constraints are met.\nSetup :            0  Failing Endpoints,  Worst Slack       18.564ns\nHold  :            0  Failing Endpoints,  Worst Slack        0.250ns\nPW    :            0  Failing Endpoints,  Worst Slack        9.500ns\n")
        with open(os.path.join(ctx.output_dir, "report_utilization.rpt"), "w", encoding="utf-8") as f:
            f.write("| Slice LUTs              |    4 |     0 |     53200 | <0.01 |\n| Slice Registers         |    5 |     0 |    106400 | <0.01 |\n| Bonded IOB              |    8 |     8 |       125 |  6.40 |\n| BUFGCTRL                |    1 |     0 |        32 |  3.13 |\n")
        with open(os.path.join(ctx.output_dir, "report_power.rpt"), "w", encoding="utf-8") as f:
            f.write("Total On-Chip Power (W) | 0.123\n")

        write_run_manifest(ctx, "running", "lint_repair", extra={"categories": ["demo"]})

        with open(ctx.manifest_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertEqual(manifest["design"]["top_module"], "demo_top")
        self.assertEqual(manifest["design"]["testbench_module"], "tb_demo_top")
        self.assertIn("bitstream", manifest["artifacts"]["files"])
        self.assertTrue(manifest["reports"]["timing"]["constraints_met"])
        self.assertEqual(manifest["reports"]["timing"]["setup_worst_slack_ns"], 18.564)
        self.assertEqual(manifest["reports"]["utilization"]["slice_luts_used"], 4)
        self.assertEqual(manifest["reports"]["power"]["total_on_chip_power_w"], 0.123)
        self.assertEqual(manifest["history"][-1]["extra"]["categories"], ["demo"])


if __name__ == "__main__":
    unittest.main()
