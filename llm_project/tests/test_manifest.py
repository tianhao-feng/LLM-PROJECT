import os
import unittest
import uuid

from autofpga.manifest import validate_manifest


class ManifestValidationTests(unittest.TestCase):
    def test_manifest_validation_accepts_expected_subset(self):
        tmpdir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "codex_test_tmp", f"manifest_{uuid.uuid4().hex}")
        os.makedirs(tmpdir)
        bitstream = os.path.join(tmpdir, "top.bit")
        with open(bitstream, "w", encoding="utf-8") as f:
            f.write("fake bitstream")

        manifest = {
            "status": "succeeded",
            "stage": "complete",
            "design": {
                "top_module": "counter_4bit_top",
                "testbench_module": "tb_counter_4bit_top",
            },
            "artifacts": {"files": {"bitstream": bitstream}},
            "reports": {"timing": {"constraints_met": True}},
        }
        expected = {
            "status": "succeeded",
            "stage": "complete",
            "design": {"top_module": "counter_4bit_top"},
            "required_artifacts": ["bitstream"],
            "reports": {"timing": {"constraints_met": True}},
        }

        self.assertEqual(validate_manifest(manifest, expected), [])

    def test_manifest_validation_reports_missing_artifact_and_wrong_design(self):
        manifest = {
            "status": "failed",
            "stage": "simulation",
            "design": {"top_module": "wrong_top"},
            "artifacts": {"files": {}},
            "reports": {"timing": {"constraints_met": False}},
        }
        expected = {
            "status": "succeeded",
            "design": {"top_module": "counter_4bit_top"},
            "required_artifacts": ["bitstream"],
            "reports": {"timing": {"constraints_met": True}},
        }

        problems = validate_manifest(manifest, expected)

        self.assertTrue(any("status expected" in problem for problem in problems))
        self.assertTrue(any("design.top_module expected" in problem for problem in problems))
        self.assertTrue(any("missing artifact entry: bitstream" in problem for problem in problems))
        self.assertTrue(any("reports.timing.constraints_met expected" in problem for problem in problems))


if __name__ == "__main__":
    unittest.main()
