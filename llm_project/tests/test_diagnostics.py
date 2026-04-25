import os
import unittest
import uuid

from autofpga.diagnostics import classify_iverilog_log, extract_and_classify_errors


class DiagnosticsTests(unittest.TestCase):
    def test_classify_iverilog_log_marks_systemverilog_as_error(self):
        result = classify_iverilog_log("foo.v:10: error: Variable declaration in unnamed block requires SystemVerilog.", 1)

        self.assertTrue(result["errors"])
        self.assertIn("Verilog-2001", result["errors"][0])

    def test_classify_iverilog_log_allows_timescale_warning(self):
        result = classify_iverilog_log("warning: timescale for tb inherited from another file.", 0)

        self.assertEqual(result["errors"], [])
        self.assertEqual(result["blocking_warnings"], [])
        self.assertTrue(result["nonblocking_warnings"])

    def test_vivado_xdc_diagnostics_classify_pin_and_ucio_errors(self):
        class Ctx:
            pass

        tmp = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "codex_test_tmp",
            f"diagnostics_{uuid.uuid4().hex}",
        )
        os.makedirs(tmp)
        ctx = Ctx()
        ctx.error_kb_file = os.path.join(tmp, "error_memory.txt")

        log = """
CRITICAL WARNING: [Common 17-69] Command failed: 'R15' is not a valid site or package pin name.
ERROR: [DRC UCIO-1] Unconstrained Logical Port: Problem ports: underflow.
ERROR: [Vivado 12-1345] Error(s) found during DRC. Bitgen not run.
ERROR: [Common 17-39] 'write_bitstream' failed due to earlier errors.
"""
        cats, advice, level = extract_and_classify_errors(ctx, log, "Vivado")

        self.assertIn("invalid package pin", cats)
        self.assertIn("unconstrained IO", cats)
        self.assertIn("bitstream generation failed", cats)
        self.assertIn("board_pins.json", advice)
        self.assertIn("invalid package pin", level)


if __name__ == "__main__":
    unittest.main()
