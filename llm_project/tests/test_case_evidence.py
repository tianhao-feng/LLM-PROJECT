import json
import os
import unittest
import uuid

from autofpga.case_evidence import capture_case_evidence, validate_case_evidence


def reset_tmp(name):
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "codex_test_tmp", f"{name}_{uuid.uuid4().hex}")
    os.makedirs(path)
    return path


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class CaseEvidenceTests(unittest.TestCase):
    def test_capture_case_evidence_from_manifest(self):
        root = reset_tmp("case_evidence")
        case_dir = os.path.join(root, "examples", "demo")
        manifest_path = os.path.join(root, "projects", "demo", "run_manifest.json")
        expected_path = os.path.join(case_dir, "expected_manifest.json")
        manifest = {
            "status": "succeeded",
            "stage": "complete",
            "updated_at": "2026-05-10 12:00:00",
            "python": "3.13.0",
            "platform": "test-platform",
            "config": {
                "iverilog_path": "iverilog",
                "modelsim_path": "vsim",
                "vivado_path": "vivado",
                "fpga_part": "xc7z020clg400-2",
            },
            "design": {"top_module": "demo_top", "testbench_module": "tb_demo_top"},
            "artifacts": {"files": {"bitstream": os.path.join(root, "demo.bit")}},
            "reports": {"timing": {"constraints_met": True}},
            "history": [
                {"stage": "lint"},
                {"stage": "simulation_passed"},
                {"stage": "vivado_build"},
            ],
        }
        expected = {
            "status": "succeeded",
            "stage": "complete",
            "design": {"top_module": "demo_top"},
            "required_artifacts": ["bitstream"],
            "reports": {"timing": {"constraints_met": True}},
        }
        write_json(manifest_path, manifest)
        write_json(expected_path, expected)

        result = capture_case_evidence(case_dir, manifest_path, copy_manifest=True)

        self.assertTrue(os.path.exists(result["evidence_path"]))
        self.assertTrue(os.path.exists(os.path.join(case_dir, "run_manifest.json")))
        self.assertEqual(result["validation_problems"], [])
        evidence = result["evidence"]
        self.assertEqual(evidence["manifest_status"], "succeeded")
        self.assertTrue(evidence["flow_passed"]["simulation"])
        self.assertTrue(evidence["manifest_validation"]["passed"])

    def test_validate_case_evidence_reports_design_mismatch(self):
        evidence = {
            "schema_version": 1,
            "manifest_status": "succeeded",
            "manifest_stage": "complete",
            "design": {"top_module": "wrong", "testbench_module": "tb_wrong"},
            "flow_passed": {"lint": True, "simulation": True, "vivado_build": True, "complete": True, "bitstream": True},
            "manifest_validation": {"problems": []},
        }

        problems, warnings = validate_case_evidence(evidence, expected_top="demo_top", expected_tb="tb_demo_top")

        self.assertTrue(any("top_module expected" in problem for problem in problems))
        self.assertTrue(any("testbench_module expected" in problem for problem in problems))
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
