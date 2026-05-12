Prompt-Name: testbench_repair
Prompt-Version: 1

被测系统：
{all_rtl}

【需求】:
{user_requirement}

{verilog_rules}

TB报错：
{error_msg}

【错误TB】:
{current_tb}

请修复错误。
硬性要求：
1. Testbench 文件由系统保存为 tb_top_module.v。
2. Testbench module 名称可以自定，建议使用 tb_{dut_module}；系统会从文件中自动解析仿真顶层。
3. 被测 DUT 模块名是 {dut_module}，必须例化它。
4. 验证成功路径必须打印 $display("SIM_RESULT: PASSED");
5. 验证失败路径必须打印 $display("SIM_RESULT: FAILED");
6. 每一个检查点失败时必须打印 SIM_RESULT: FAILED，不能只打印普通 ERROR。
7. 必须包含 if/比较语句主动检查 DUT 输出或关键状态，禁止只跑时钟或固定延时后直接 PASS。
8. 时序电路采样规则：输入激励在 negedge clk 或远离 posedge 的时刻改变；检查寄存器输出必须在 posedge clk 之后 #1 再比较，或在下一个 negedge clk 比较。禁止用裸 #10 后直接把 loop index 当期望值。
9. 对计数器这类寄存器 DUT，维护 expected_count 变量；每次有效 posedge 后先根据复位/使能规则更新 expected_count，再与 DUT 输出比较。
10. 仿真结束必须调用 $stop，禁止 $finish。
11. 只输出一个完整 Verilog 代码块。
