import os
import unittest
import uuid
from unittest.mock import patch
from unittest.mock import Mock

from autofpga.config import build_context
from autofpga.doctor import collect_doctor_report, format_doctor_report


def reset_tmp(name):
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "codex_test_tmp", f"{name}_{uuid.uuid4().hex}")
    os.makedirs(path)
    return path


class DoctorTests(unittest.TestCase):
    def test_doctor_reports_environment_items(self):
        tmp = reset_tmp("doctor")
        ctx = build_context(
            script_dir=tmp,
            project_name="demo",
            auto_timestamp=False,
            iverilog_path="iverilog",
            modelsim_path="vsim",
            vivado_path="vivado",
            llm_api_key="secret",
        )

        with patch("autofpga.doctor.missing_executable", return_value=""):
            report = collect_doctor_report(ctx)

        self.assertIn(report["overall"], {"ok", "warn"})
        components = {item["component"] for item in report["items"]}
        self.assertIn("external_tool", components)
        self.assertIn("llm", components)
        self.assertIn("board", components)
        text = format_doctor_report(report)
        self.assertIn("AutoFPGA Doctor", text)

    def test_doctor_warns_for_missing_external_tools(self):
        tmp = reset_tmp("doctor_missing_tool")
        ctx = build_context(script_dir=tmp, project_name="demo", auto_timestamp=False)

        with patch("autofpga.doctor.missing_executable", return_value="not found"):
            report = collect_doctor_report(ctx)

        self.assertEqual(report["overall"], "warn")
        self.assertTrue(any(item["component"] == "external_tool" and item["status"] == "warn" for item in report["items"]))

    def test_doctor_smoke_runs_version_commands(self):
        tmp = reset_tmp("doctor_smoke")
        ctx = build_context(
            script_dir=tmp,
            project_name="demo",
            auto_timestamp=False,
            iverilog_path="iverilog",
            modelsim_path="vsim",
            vivado_path="vivado",
        )
        result = Mock()
        result.ok = True
        result.output = "tool version\n"

        with patch("autofpga.doctor.missing_executable", return_value=""), patch(
            "autofpga.doctor.run_command", return_value=result
        ) as run:
            report = collect_doctor_report(ctx, smoke=True)

        self.assertEqual(run.call_count, 3)
        self.assertTrue(all(item["status"] == "ok" for item in report["items"] if item["component"] == "external_tool"))


if __name__ == "__main__":
    unittest.main()
