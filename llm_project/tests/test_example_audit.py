import json
import os
import unittest
import uuid

from autofpga.example_audit import audit_examples, format_example_audit_report


def reset_tmp(name):
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "codex_test_tmp", f"{name}_{uuid.uuid4().hex}")
    os.makedirs(path)
    return path


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class ExampleAuditTests(unittest.TestCase):
    def test_audit_accepts_complete_example_fixture(self):
        root = reset_tmp("example_audit")
        example = os.path.join(root, "examples", "demo")
        write(os.path.join(example, "README.md"), "# Demo\n\n" + "A complete regression fixture. " * 40)
        write(
            os.path.join(example, "requirement.json"),
            json.dumps({"user_requirement": "Create demo."}, ensure_ascii=False),
        )
        write(
            os.path.join(example, "expected_manifest.json"),
            json.dumps(
                {
                    "design": {
                        "top_module": "demo_top",
                        "testbench_module": "tb_demo_top",
                    }
                },
                ensure_ascii=False,
            ),
        )
        write(
            os.path.join(example, "src", "demo_top.v"),
            "module demo_top(input clk, output led); assign led = clk; endmodule\n",
        )
        write(
            os.path.join(example, "tb_top_module.v"),
            """
module tb_demo_top;
reg clk;
wire led;
demo_top dut(.clk(clk), .led(led));
initial begin
    clk = 1'b0;
    if (led === 1'b0 || led === 1'b1) begin
        $display("SIM_RESULT: PASSED");
    end else begin
        $display("SIM_RESULT: FAILED");
    end
    $stop;
end
endmodule
""".strip()
            + "\n",
        )
        write(
            os.path.join(example, "constraints.xdc"),
            "set_property PACKAGE_PIN K17 [get_ports clk]\nset_property IOSTANDARD LVCMOS33 [get_ports clk]\n",
        )

        report = audit_examples(os.path.join(root, "examples"))

        self.assertEqual(report["failed"], 0)
        self.assertEqual(report["passed"], 1)
        self.assertEqual(report["registry_kind"], "golden_cases")
        self.assertEqual(report["results"][0]["src_file_count"], 1)
        self.assertEqual(report["results"][0]["requirement_summary"], "Create demo.")
        self.assertFalse(report["results"][0]["has_run_evidence"])
        self.assertIn("PASS", format_example_audit_report(report))

    def test_audit_writes_case_index_json(self):
        root = reset_tmp("example_audit_index")
        example = os.path.join(root, "examples", "demo")
        index_file = os.path.join(root, "examples", "index.json")
        write(os.path.join(example, "README.md"), "# Demo\n\n" + "A complete regression fixture. " * 40)
        write(os.path.join(example, "requirement.json"), json.dumps({"user_requirement": "Create demo."}))
        write(
            os.path.join(example, "expected_manifest.json"),
            json.dumps({"design": {"top_module": "demo_top", "testbench_module": "tb_demo_top"}}),
        )
        write(os.path.join(example, "src", "demo_top.v"), "module demo_top(input clk); endmodule\n")
        write(
            os.path.join(example, "tb_top_module.v"),
            "module tb_demo_top; reg clk; demo_top dut(.clk(clk)); initial begin if (1==1) $display(\"SIM_RESULT: PASSED\"); else $display(\"SIM_RESULT: FAILED\"); $stop; end endmodule\n",
        )
        write(
            os.path.join(example, "constraints.xdc"),
            "set_property PACKAGE_PIN K17 [get_ports clk]\nset_property IOSTANDARD LVCMOS33 [get_ports clk]\n",
        )
        write(
            os.path.join(example, "run_evidence.json"),
            json.dumps(
                {
                    "validated_at": "2026-05-10",
                    "toolchain": {"vivado": "2017.4"},
                    "flow_passed": {"bitstream": True},
                }
            ),
        )

        audit_examples(os.path.join(root, "examples"), write_index=True, index_file=index_file)

        with open(index_file, "r", encoding="utf-8") as f:
            index = json.load(f)
        self.assertEqual(index["registry_kind"], "golden_cases")
        self.assertEqual(index["results"][0]["validated_at"], "2026-05-10")
        self.assertTrue(index["results"][0]["has_run_evidence"])

    def test_audit_reports_missing_files(self):
        root = reset_tmp("example_audit_missing")
        example = os.path.join(root, "examples", "broken")
        os.makedirs(example)
        write(os.path.join(example, "requirement.json"), "{}")

        report = audit_examples(os.path.join(root, "examples"))

        self.assertEqual(report["failed"], 1)
        problems = report["results"][0]["problems"]
        self.assertTrue(any("missing required file" in problem for problem in problems))

    def test_audit_rejects_mismatched_evidence(self):
        root = reset_tmp("example_audit_bad_evidence")
        example = os.path.join(root, "examples", "demo")
        write(os.path.join(example, "README.md"), "# Demo\n\n" + "A complete regression fixture. " * 40)
        write(os.path.join(example, "requirement.json"), json.dumps({"user_requirement": "Create demo."}))
        write(
            os.path.join(example, "expected_manifest.json"),
            json.dumps({"design": {"top_module": "demo_top", "testbench_module": "tb_demo_top"}}),
        )
        write(os.path.join(example, "src", "demo_top.v"), "module demo_top(input clk); endmodule\n")
        write(
            os.path.join(example, "tb_top_module.v"),
            "module tb_demo_top; reg clk; demo_top dut(.clk(clk)); initial begin if (1==1) $display(\"SIM_RESULT: PASSED\"); else $display(\"SIM_RESULT: FAILED\"); $stop; end endmodule\n",
        )
        write(
            os.path.join(example, "constraints.xdc"),
            "set_property PACKAGE_PIN K17 [get_ports clk]\nset_property IOSTANDARD LVCMOS33 [get_ports clk]\n",
        )
        write(
            os.path.join(example, "run_evidence.json"),
            json.dumps(
                {
                    "schema_version": 1,
                    "manifest_status": "succeeded",
                    "manifest_stage": "complete",
                    "design": {"top_module": "wrong_top", "testbench_module": "tb_demo_top"},
                    "flow_passed": {
                        "lint": True,
                        "simulation": True,
                        "vivado_build": True,
                        "complete": True,
                        "bitstream": True,
                    },
                    "manifest_validation": {"problems": []},
                }
            ),
        )

        report = audit_examples(os.path.join(root, "examples"))

        self.assertEqual(report["failed"], 1)
        self.assertTrue(any("run_evidence top_module expected" in p for p in report["results"][0]["problems"]))


if __name__ == "__main__":
    unittest.main()
