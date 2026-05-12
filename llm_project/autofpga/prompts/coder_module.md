Prompt-Name: coder_module
Prompt-Version: 1

【总体设计规范】
{sys_spec}

【局部架构清单】
{global_arch}

{verilog_rules}

【任务】：编写 `{filename}`。
模块名：{module_name}
端口列表：
{port_spec}
功能描述：{description}
{retry_hint}

强制要求：
1. 只输出一个完整 Verilog 代码块。
2. 必须包含 `module {module_name}` 和 `endmodule`。
3. 禁止输出解释、Markdown 正文或对话文本。
4. 必须严格满足 Verilog-2001 硬性约束。
