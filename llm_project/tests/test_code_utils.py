import unittest

from autofpga.code_utils import infer_testbench_module_name, validate_testbench_contract, validate_verilog_code


class CodeUtilsTests(unittest.TestCase):
    def test_validate_verilog_accepts_basic_verilog_2001_module(self):
        code = """
module counter_top (
    input clk,
    input rst_n,
    output reg [3:0] count
);
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        count <= 4'b0000;
    end else begin
        count <= count + 1'b1;
    end
end
endmodule
"""

        ok, problems = validate_verilog_code(code, "counter_top.v", expected_module="counter_top")

        self.assertTrue(ok)
        self.assertEqual(problems, [])

    def test_validate_verilog_rejects_systemverilog_logic(self):
        code = """
module bad_top(input clk, output logic done);
endmodule
"""

        ok, problems = validate_verilog_code(code, "bad_top.v", expected_module="bad_top")

        self.assertFalse(ok)
        self.assertTrue(any("logic" in problem for problem in problems))

    def test_validate_testbench_contract_accepts_self_checking_tb(self):
        code = """
module tb_counter_top;
reg clk;
reg rst_n;
wire [3:0] count;
counter_top dut(.clk(clk), .rst_n(rst_n), .count(count));
initial begin
    clk = 0;
end
always #5 clk = ~clk;
initial begin
    rst_n = 0;
    #20;
    rst_n = 1;
    #10;
    if (count == 4'h0) begin
        $display("SIM_RESULT: PASSED");
    end else begin
        $display("SIM_RESULT: FAILED");
    end
    $stop;
end
endmodule
"""

        ok, problems = validate_testbench_contract(code, expected_dut_module="counter_top")

        self.assertTrue(ok, problems)
        self.assertEqual(infer_testbench_module_name(code, expected_dut_module="counter_top"), "tb_counter_top")

    def test_validate_testbench_ignores_increment_like_text_in_comments(self):
        code = """
module tb_counter_top;
counter_top dut();
integer i;
initial begin
    // 测试6--异步复位
    for (i = 0; i < 4; i = i + 1) begin
        if (i == 0) begin
            $display("SIM_RESULT: PASSED");
        end else begin
            $display("SIM_RESULT: FAILED");
        end
    end
    $stop;
end
endmodule
"""

        ok, problems = validate_testbench_contract(code, expected_dut_module="counter_top")

        self.assertTrue(ok, problems)

    def test_validate_testbench_contract_rejects_missing_failed_marker(self):
        code = """
module tb_top_module;
initial begin
    if (1 == 1) $display("SIM_RESULT: PASSED");
    $stop;
end
endmodule
"""

        ok, problems = validate_testbench_contract(code)

        self.assertFalse(ok)
        self.assertTrue(any("FAILED" in problem for problem in problems))

    def test_validate_testbench_contract_rejects_missing_dut_instance(self):
        code = """
module tb_top_module;
initial begin
    if (1 == 1) begin
        $display("SIM_RESULT: PASSED");
    end else begin
        $display("SIM_RESULT: FAILED");
    end
    $stop;
end
endmodule
"""

        ok, problems = validate_testbench_contract(code, expected_dut_module="counter_top")

        self.assertFalse(ok)
        self.assertTrue(any("counter_top" in problem for problem in problems))

    def test_validate_testbench_contract_rejects_no_comparison(self):
        code = """
module tb_top_module;
counter_top dut();
initial begin
    #100;
    $display("SIM_RESULT: PASSED");
    $display("SIM_RESULT: FAILED");
    $stop;
end
endmodule
"""

        ok, problems = validate_testbench_contract(code, expected_dut_module="counter_top")

        self.assertFalse(ok)
        self.assertTrue(any("条件检查" in problem or "比较检查" in problem for problem in problems))


if __name__ == "__main__":
    unittest.main()
