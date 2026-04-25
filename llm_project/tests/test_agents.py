import os
import unittest
import uuid
from unittest.mock import patch

from autofpga.agents import (
    assess_readme_content,
    build_deterministic_counter_testbench,
    has_minimum_readme_content,
    is_llm_error_response,
    load_xilinx_skill_notes,
    normalize_readme_contracts,
    save_rejected_readme,
    task_generate_xdc,
)
from autofpga.code_utils import validate_testbench_contract


class AgentsTests(unittest.TestCase):
    def test_llm_error_response_detection(self):
        self.assertTrue(is_llm_error_response("API error: HTTP 401"))
        self.assertTrue(is_llm_error_response("network connection timeout"))
        self.assertFalse(is_llm_error_response("# README\n\nSIM_RESULT: PASSED\nSIM_RESULT: FAILED"))

    def test_save_rejected_readme(self):
        tmp = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "codex_test_tmp",
            f"agents_rejected_readme_{uuid.uuid4().hex}",
        )
        os.makedirs(tmp, exist_ok=True)

        class Ctx:
            save_dir = tmp

        save_rejected_readme(Ctx(), "bad content", ["too short"], 2)

        with open(os.path.join(tmp, "README.rejected.md"), "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "bad content")
        with open(os.path.join(tmp, "README.rejected_reason.txt"), "r", encoding="utf-8") as f:
            reason = f.read()
        self.assertIn("attempt: 2", reason)
        self.assertIn("too short", reason)

    def test_load_xilinx_skill_notes_reads_selected_files_and_truncates(self):
        tmp = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "codex_test_tmp",
            f"agents_xilinx_notes_{uuid.uuid4().hex}",
        )
        notes_dir = os.path.join(tmp, "xilinx_skill")
        os.makedirs(notes_dir, exist_ok=True)
        with open(os.path.join(notes_dir, "xdc_constraints_notes.md"), "w", encoding="utf-8") as f:
            f.write("XDC rule " + ("x" * 200))

        class Ctx:
            kb_dir = tmp

        notes = load_xilinx_skill_notes(Ctx(), ["xdc_constraints_notes.md"], max_chars=40)

        self.assertIn("[xdc_constraints_notes.md]", notes)
        self.assertIn("[truncated]", notes)

    def test_task_generate_xdc_writes_xilinx_notes_on_rejection(self):
        tmp = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "codex_test_tmp",
            f"agents_xdc_reject_{uuid.uuid4().hex}",
        )
        notes_dir = os.path.join(tmp, "kb", "xilinx_skill")
        os.makedirs(notes_dir, exist_ok=True)
        with open(os.path.join(notes_dir, "xdc_constraints_notes.md"), "w", encoding="utf-8") as f:
            f.write("PACKAGE_PIN and IOSTANDARD must both be set.")

        class Ctx:
            save_dir = tmp
            kb_dir = os.path.join(tmp, "kb")

        with patch("autofpga.agents.generate_structured_xdc", side_effect=RuntimeError("missing pin")):
            with self.assertRaises(RuntimeError):
                task_generate_xdc(Ctx())

        with open(os.path.join(tmp, "xdc_rejected_reason.txt"), "r", encoding="utf-8") as f:
            reason = f.read()
        self.assertIn("missing pin", reason)
        self.assertIn("PACKAGE_PIN and IOSTANDARD", reason)

    def test_normalize_readme_contracts_keeps_dynamic_testbench_module(self):
        content = """
## 8. Testbench 验收标准
测试平台文件固定命名为 `tb_counter_top.v`。
测试平台模块固定命名为 `tb_counter_top`。
"""
        normalized = normalize_readme_contracts(content)

        self.assertIn("`tb_top_module.v`", normalized)
        self.assertIn("`tb_counter_top`", normalized)

    def test_minimum_readme_gate_is_less_strict_than_quality_assessment(self):
        content = """
# Counter
实现一个 Verilog-2001 计数器模块，包含 clk、rst_n、en 和 count 端口。
测试平台应打印 SIM_RESULT: PASSED 或 SIM_RESULT: FAILED。
""" + ("x" * 160)

        ok, problems = assess_readme_content(content)

        self.assertFalse(ok)
        self.assertTrue(problems)
        self.assertTrue(has_minimum_readme_content(content))

    def test_assess_readme_does_not_treat_strategy_as_placeholder(self):
        content = """
# Demo
## 1. 设计目标
实现计数器。
## 2. 语言与工具约束
RTL 语言：Verilog-2001。
## 3. 顶层模块规范
顶层模块 top_module，端口 clk rst_n count，文件 top_module.v。
## 4. 模块划分
module list filename top_module.v。
## 5. 模块详细接口
端口表包含 clk rst_n。
## 6. 模块连接关系
说明数据流策略和控制流策略。
## 7. 功能行为规格
验证计数行为。
## 8. Testbench 验收标准
测试平台文件固定命名为 tb_top_module.v，测试平台模块名由系统自动解析。
成功打印 SIM_RESULT: PASSED，失败打印 SIM_RESULT: FAILED。
## 9. 代码生成规则
禁止 SystemVerilog。
""" + ("x" * 700)

        ok, problems = assess_readme_content(content)

        self.assertTrue(ok, problems)

    def test_build_deterministic_counter_testbench(self):
        rtl = """
module counter_4bit_top(input clk, input rst_n, input en, output [3:0] count, output overflow);
endmodule
module counter_4bit_core(input clk, input rst_n, input en, output reg [3:0] count);
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) count <= 4'h0;
    else if (en) count <= count + 1'b1;
end
endmodule
"""

        tb = build_deterministic_counter_testbench(rtl, "counter_4bit_top")
        ok, problems = validate_testbench_contract(tb, expected_dut_module="counter_4bit_top")

        self.assertIn("module tb_counter_4bit_top", tb)
        self.assertIn("expected_count = expected_count + 1'b1", tb)
        self.assertTrue(ok, problems)

    def test_build_deterministic_load_updown_counter_testbench(self):
        rtl = """
module counter_load_updown_top(
    input clk,
    input rst_n,
    input en,
    input load,
    input up_down,
    input [3:0] load_value,
    output [3:0] count,
    output overflow,
    output underflow
);
always @(posedge clk or negedge rst_n) begin
end
endmodule
"""

        tb = build_deterministic_counter_testbench(rtl, "counter_load_updown_top")
        ok, problems = validate_testbench_contract(tb, expected_dut_module="counter_load_updown_top")

        self.assertIn("module tb_counter_load_updown_top", tb)
        self.assertIn(".load(load)", tb)
        self.assertIn(".up_down(up_down)", tb)
        self.assertIn(".load_value(load_value)", tb)
        self.assertIn("underflow flag expected 1 on wrap down", tb)
        self.assertTrue(ok, problems)


if __name__ == "__main__":
    unittest.main()
