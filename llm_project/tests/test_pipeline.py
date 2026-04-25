import unittest

from autofpga.pipeline import is_infrastructure_error, is_likely_testbench_oracle_error


class PipelineTests(unittest.TestCase):
    def test_infrastructure_error_detection(self):
        self.assertTrue(is_infrastructure_error(r"ModelSim 工具未找到: C:\modeltech64_2020.4\win64\vsim.exe"))
        self.assertTrue(is_infrastructure_error("Permission denied while running Vivado"))
        self.assertFalse(is_infrastructure_error("syntax error near unexpected token"))

    def test_testbench_oracle_error_detection(self):
        log = "SIM_RESULT: FAILED at time 30000: Expected count = 0, got 1"

        self.assertTrue(is_likely_testbench_oracle_error(log))
        self.assertFalse(is_likely_testbench_oracle_error("syntax error near unexpected token"))


if __name__ == "__main__":
    unittest.main()
