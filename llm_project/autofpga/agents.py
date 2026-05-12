import json
import os
import re

from .code_utils import VERILOG_2001_RULES, build_targeted_context, clean_code, read_all_src_code, write_verified_verilog
from .llm_client import query_llm
from .prompt_templates import render_prompt
from .xdc import ensure_board_pin_database, generate_structured_xdc


def ensure_knowledge_base(ctx):
    ensure_board_pin_database(ctx)
    board_file = os.path.join(ctx.kb_dir, "board_constraints.txt")
    if not os.path.exists(board_file):
        with open(board_file, "w", encoding="utf-8") as f:
            f.write("""[板卡基础信息]
型号: Zynq 7020 (xc7z020clg400-2)
[物理引脚映射字典]
时钟 clk -> K17
复位 rst_n -> M19
输出 led_out[0] -> M14
输出 led_out[1] -> M15
输出 led_out[2] -> K16
输出 led_out[3] -> J16

Vivado XDC 编写规则:
1. 只允许 create_clock 和 set_property。
2. 每个端口必须分配 PACKAGE_PIN 和 IOSTANDARD LVCMOS33。
3. 数组端口必须使用 [get_ports {led_out[3]}] 形式。
""")
    if not os.path.exists(ctx.error_kb_file):
        with open(ctx.error_kb_file, "w", encoding="utf-8") as f:
            f.write("[AI FPGA 历史错题本]\n")


def load_xilinx_skill_notes(ctx, filenames=None, max_chars=5000):
    filenames = filenames or [
        "vivado_flow_notes.md",
        "xdc_constraints_notes.md",
        "tcl_commands_notes.md",
    ]
    notes_dir = os.path.join(ctx.kb_dir, "xilinx_skill")
    chunks = []
    for fname in filenames:
        path = os.path.join(notes_dir, fname)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read().strip()
        if content:
            chunks.append(f"[{fname}]\n{content}")
    text = "\n\n".join(chunks).strip()
    if max_chars and len(text) > max_chars:
        return text[:max_chars].rstrip() + "\n[truncated]"
    return text


def agent_router(query):
    print("\n>>> [Agent-总调度师] 正在分析用户意图...")
    prompt = f"""分析以下 FPGA 任务意图：{query}
    只输出以下三个标签之一：
    [TABLE]：查询具体芯片手册、表格、引脚或参数。
    [CONCEPT]：询问原理或概念。
    [CODE]：要求设计系统、编写代码、综合或生成比特流。
    """
    label = query_llm(prompt).strip()
    if "[TABLE]" in label.upper():
        return "TABLE"
    if "[CONCEPT]" in label.upper():
        return "CONCEPT"
    return "CODE"


def agent_architect(ctx, requirement):
    print("\n>>> [Agent-架构师] 正在进行系统级需求分析并撰写 README.md...")
    xilinx_notes = load_xilinx_skill_notes(
        ctx,
        filenames=["vivado_flow_notes.md", "xdc_constraints_notes.md"],
        max_chars=4500,
    )
    prompt_readme = render_prompt(
        "architect_readme.md",
        requirement=requirement,
        xilinx_notes=xilinx_notes,
    )
    readme_content = ""
    readme_problems = []
    for readme_try in range(3):
        raw_readme = query_llm(prompt_readme)
        if is_llm_error_response(raw_readme):
            save_rejected_readme(ctx, raw_readme, [raw_readme], readme_try + 1)
            raise RuntimeError("README generation failed because the LLM request failed: " + raw_readme[:500])
        readme_content = normalize_readme_contracts(clean_code(raw_readme, "markdown"))
        readme_ok, readme_problems = assess_readme_content(readme_content)
        if readme_ok:
            break
        save_rejected_readme(ctx, readme_content or raw_readme, readme_problems, readme_try + 1)
        if not has_minimum_readme_content(readme_content):
            print(f"⚠️ README 内容过短，重试 {readme_try + 1}/3: {'; '.join(readme_problems[:4])}")
            continue
        print(f"⚠️ README 规格不完整，继续流水线: {'; '.join(readme_problems[:4])}")
        break
    if not has_minimum_readme_content(readme_content):
        _, readme_problems = assess_readme_content(readme_content)
        save_rejected_readme(ctx, readme_content, readme_problems, "final")
        raise RuntimeError("README generation failed: content is empty or too short to guide code generation")
    _, readme_problems = assess_readme_content(readme_content)
    if readme_problems:
        save_rejected_readme(ctx, readme_content, readme_problems, "warning")
    with open(ctx.readme_file, "w", encoding="utf-8") as f:
        f.write(readme_content)
    print("总体设计规范已保存至 README.md")

    prompt_json = f"""
你是 RTL 工程规划解析器。请从下面 README.md 中提取模块清单，输出严格 JSON，不要输出任何解释。

【README.md】
{readme_content}

【JSON Schema】
{{
  "top_module": "string",
  "top_file": "string",
  "modules": [
    {{
      "filename": "string, must end with .v",
      "module_name": "string",
      "is_top": true,
      "ports": [
        {{
          "name": "string",
          "direction": "input|output|inout",
          "width": "string, e.g. 1 or 32 or [31:0]",
          "description": "string"
        }}
      ],
      "description": "string",
      "instances": ["module_name list instantiated by this module"]
    }}
  ],
  "testbench_goals": ["string"],
  "verilog_standard": "Verilog-2001"
}}

【硬性规则】
1. filename 必须唯一。
2. module_name 必须唯一。
3. top_module 必须等于 modules 中 is_top=true 的 module_name。
4. 只能有一个 is_top=true。
5. 不允许返回 Markdown。
6. 不允许返回注释。
7. 不允许省略 ports。
8. verilog_standard 必须为 Verilog-2001。
"""
    for _ in range(3):
        res = query_llm(prompt_json)
        match = re.search(r"\{[\s\S]*\}", res)
        if match:
            try:
                arch_json = json.loads(match.group(0))
                if validate_arch_json(arch_json):
                    return arch_json
            except Exception:
                pass
    return {
        "top_module": "top_module",
        "top_file": "top_module.v",
        "verilog_standard": "Verilog-2001",
        "testbench_goals": ["验证顶层复位、基本输入输出行为，并在成功时打印 SIM_RESULT: PASSED"],
        "modules": [
            {
                "filename": "top_module.v",
                "module_name": "top_module",
                "is_top": True,
                "ports": [
                    {"name": "clk", "direction": "input", "width": "1", "description": "系统时钟"},
                    {"name": "rst_n", "direction": "input", "width": "1", "description": "低有效异步复位"},
                ],
                "description": requirement,
                "instances": [],
            }
        ],
    }


def validate_readme_content(content):
    ok, _ = assess_readme_content(content)
    return ok


def has_minimum_readme_content(content):
    text = (content or "").strip()
    return len(text) >= 120 and ("#" in text or "module" in text.lower() or "模块" in text)


def normalize_readme_contracts(content):
    text = content or ""
    replacements = [
        (
            r"(测试平台文件固定命名为\s*)`?[^`\n。]*?\.v`?",
            r"\1`tb_top_module.v`",
        ),
        (
            r"(testbench\s+file\s+.*?(?:named|name(?:d)?\s+as)\s*)`?[^`\n。]*?\.v`?",
            r"\1`tb_top_module.v`",
        ),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    if "tb_top_module.v" not in text:
        text += (
            "\n\nTestbench 固定契约：测试平台文件固定命名为 `tb_top_module.v`，"
            "测试平台 module 名称由系统从 testbench 文件中自动解析。"
        )
    return text


def is_llm_error_response(text):
    lowered = (text or "").lower()
    markers = [
        "api ",
        "api error",
        "http 4",
        "http 5",
        "request timed out",
        "timeout",
        "connection",
        "network",
    ]
    return any(marker in lowered for marker in markers)


def save_rejected_readme(ctx, content, problems, attempt):
    os.makedirs(ctx.save_dir, exist_ok=True)
    rejected_md = os.path.join(ctx.save_dir, "README.rejected.md")
    rejected_log = os.path.join(ctx.save_dir, "README.rejected_reason.txt")
    with open(rejected_md, "w", encoding="utf-8") as f:
        f.write(content or "")
    with open(rejected_log, "w", encoding="utf-8") as f:
        f.write(f"attempt: {attempt}\n")
        for problem in problems or []:
            f.write(f"- {problem}\n")


def assess_readme_content(content):
    if not content:
        return False, ["README 为空"]

    text = content.strip()
    lowered = text.lower()
    problems = []
    if len(text) < 600:
        problems.append(f"内容过短: {len(text)} 字符，至少需要 600 字符")

    banned_placeholder_patterns = {
        "待实现": r"待实现",
        "根据需要扩展": r"根据需要扩展",
        "TODO": r"\bTODO\b|\btodo\b",
        "此处略": r"此处略|略去|省略实现|内容略|其余略|后续补充|详见后续",
    }
    found_placeholders = [
        name for name, pattern in banned_placeholder_patterns.items() if re.search(pattern, text)
    ]
    if found_placeholders:
        problems.append("存在占位内容: " + ", ".join(found_placeholders))

    required_tokens = {
        "Verilog-2001": ["verilog-2001", "verilog 2001"],
        "顶层模块": ["顶层模块", "top module", "top_module", "top-level"],
        "端口说明": ["端口", "port"],
        "模块文件": [".v", "filename", "文件"],
        "Testbench通过标志": ["sim_result: passed"],
        "Testbench失败标志": ["sim_result: failed"],
        "复位/时钟": ["clk", "rst_n"],
    }
    for name, choices in required_tokens.items():
        if not any(choice in lowered for choice in choices):
            problems.append(f"缺少核心工程信息: {name}")

    section_groups = [
        ["设计目标", "功能目标", "design goals", "设计需求"],
        ["语言与工具约束", "工具约束", "语言约束", "verilog-2001"],
        ["顶层模块规范", "顶层接口", "顶层模块", "top module"],
        ["模块划分", "模块清单", "模块列表", "module list"],
        ["模块详细接口", "模块接口", "端口表", "接口定义"],
        ["模块连接关系", "连接关系", "例化关系", "数据流"],
        ["功能行为规格", "行为规格", "功能行为", "验收行为"],
        ["Testbench 验收标准", "testbench", "测试平台", "仿真验收"],
        ["代码生成规则", "生成规则", "编码规则", "rtl 规则"],
    ]
    matched_groups = 0
    for group in section_groups:
        if any(keyword.lower() in lowered for keyword in group):
            matched_groups += 1
    if matched_groups < 7:
        problems.append(f"工程规格章节覆盖不足: {matched_groups}/9，至少需要 7/9")

    return len(problems) == 0, problems


def validate_arch_json(arch_json):
    if not isinstance(arch_json, dict):
        return False
    modules = arch_json.get("modules")
    if not isinstance(modules, list) or not modules:
        return False
    if arch_json.get("verilog_standard") != "Verilog-2001":
        return False

    filenames = []
    module_names = []
    top_modules = []
    for mod in modules:
        if not isinstance(mod, dict):
            return False
        fname = mod.get("filename")
        mname = mod.get("module_name")
        ports = mod.get("ports")
        if not fname or not fname.endswith(".v") or not mname:
            return False
        if not isinstance(ports, list) or not ports:
            return False
        for port in ports:
            if not isinstance(port, dict):
                return False
            if port.get("direction") not in ["input", "output", "inout"]:
                return False
            if not port.get("name") or not port.get("width"):
                return False
        filenames.append(fname)
        module_names.append(mname)
        if mod.get("is_top") is True:
            top_modules.append(mname)

    return (
        len(filenames) == len(set(filenames))
        and len(module_names) == len(set(module_names))
        and len(top_modules) == 1
        and arch_json.get("top_module") == top_modules[0]
    )


def agent_coder(ctx, arch_json, error_context=None):
    ensure_knowledge_base(ctx)
    err_mem = open(ctx.error_kb_file, "r", encoding="utf-8").read()[-1000:] if os.path.exists(ctx.error_kb_file) else ""
    sys_spec = open(ctx.readme_file, "r", encoding="utf-8").read() if os.path.exists(ctx.readme_file) else "无总体规范"

    if error_context:
        print("\n>>> [Agent-主程修复] 接到审查报错，正在分析血缘依赖并加载增量上下文...")
        targeted_code, scope_str = build_targeted_context(error_context, ctx.src_dir)
        print(f"    -> [上下文剪枝] 锁定相关依赖链: {scope_str}")
        prompt = render_prompt(
            "repair_module.md",
            sys_spec=sys_spec,
            verilog_rules=VERILOG_2001_RULES,
            error_context=error_context,
            targeted_code=targeted_code,
            error_memory=err_mem,
        )
        repair_code = query_llm(prompt)
        blocks = re.split(r"//\s*File:\s*([a-zA-Z0-9_]+\.v)", repair_code, flags=re.IGNORECASE)
        if len(blocks) > 1:
            for i in range(1, len(blocks), 2):
                fname, code_content = blocks[i].strip(), clean_code(blocks[i + 1], "verilog")
                ok, problems = write_verified_verilog(os.path.join(ctx.src_dir, fname), code_content)
                if ok:
                    print(f"✅ [修复] 已精准覆写 {fname}")
                else:
                    print(f"⚠️ [修复拒写] {fname}: {'; '.join(problems)}")
        else:
            print("⚠️ 主程未按格式输出，尝试智能提取...")
            code_content = clean_code(repair_code, "verilog")
            if code_content:
                files = [f for f in os.listdir(ctx.src_dir) if f.endswith(".v")]
                files.sort(key=lambda x: os.path.getsize(os.path.join(ctx.src_dir, x)), reverse=True)
                if files:
                    ok, problems = write_verified_verilog(os.path.join(ctx.src_dir, files[0]), code_content)
                    if ok:
                        print(f"✅ [修复] 已智能覆写 {files[0]}")
                    else:
                        print(f"⚠️ [修复拒写] {files[0]}: {'; '.join(problems)}")
        return True

    print("\n>>> [Agent-编码团队] 收到设计规范，开始开发...")
    global_arch = json.dumps(arch_json, ensure_ascii=False, indent=2)
    for mod in arch_json["modules"]:
        fname, mname = mod["filename"], mod["module_name"]
        port_spec = format_port_spec(mod.get("ports", ""))
        last_problems = []
        for gen_try in range(3):
            print(f"    -> 正在编写 {fname} ... (尝试 {gen_try + 1}/3)")
            retry_hint = ""
            if last_problems:
                retry_hint = "\n【上次输出被拒绝原因】:\n" + "\n".join([f"- {p}" for p in last_problems])
            prompt = render_prompt(
                "coder_module.md",
                sys_spec=sys_spec,
                global_arch=global_arch,
                verilog_rules=VERILOG_2001_RULES,
                filename=fname,
                module_name=mname,
                port_spec=port_spec,
                description=mod.get("description", ""),
                retry_hint=retry_hint,
            )
            code = clean_code(query_llm(prompt), "verilog")
            ok, last_problems = write_verified_verilog(os.path.join(ctx.src_dir, fname), code, expected_module=mname)
            if ok:
                break
            print(f"    ⚠️ {fname} 生成结果拒写: {'; '.join(last_problems)}")
        else:
            print(f"    ❌ {fname} 连续生成失败，等待后续审查暴露问题。")


def format_port_spec(ports):
    if isinstance(ports, list):
        lines = []
        for port in ports:
            if isinstance(port, dict):
                lines.append(
                    f"- {port.get('direction', '')} {port.get('width', '')} {port.get('name', '')}: {port.get('description', '')}"
                )
        return "\n".join(lines)
    return str(ports)


def task_generate_testbench(ctx, error_msg=None, current_tb=None):
    print(">>> [Agent-验证专家] 正在生成意图驱动的自校验测试平台...")
    all_rtl = read_all_src_code(ctx)
    dut_module = infer_dut_module(ctx)
    deterministic_tb = build_deterministic_counter_testbench(all_rtl, dut_module)
    if deterministic_tb:
        ok, problems = write_verified_verilog(
            ctx.tb_file,
            deterministic_tb,
            require_sim_result=True,
            expected_dut_module=dut_module,
        )
        if ok:
            print("✅ [TB] 已生成确定性 4-bit counter testbench")
            return deterministic_tb
        print(f"⚠️ [TB模板拒写] {'; '.join(problems)}")
        save_rejected_testbench(ctx, deterministic_tb, problems)

    if error_msg:
        prompt = render_prompt(
            "testbench_repair.md",
            all_rtl=all_rtl,
            user_requirement=ctx.user_requirement,
            verilog_rules=VERILOG_2001_RULES,
            error_msg=error_msg,
            current_tb=current_tb,
            dut_module=dut_module,
        )
    else:
        prompt = render_prompt(
            "testbench_generate.md",
            all_rtl=all_rtl,
            user_requirement=ctx.user_requirement,
            verilog_rules=VERILOG_2001_RULES,
            dut_module=dut_module,
        )
    code = clean_code(query_llm(prompt), "tb")
    if code:
        ok, problems = write_verified_verilog(
            ctx.tb_file,
            code,
            require_sim_result=True,
            expected_dut_module=dut_module,
        )
        if not ok:
            print(f"⚠️ [TB拒写] {'; '.join(problems)}")
            save_rejected_testbench(ctx, code, problems)
            return current_tb
    return code


def build_deterministic_counter_testbench(all_rtl, dut_module):
    if not is_4bit_counter_design(all_rtl, dut_module):
        return ""
    if is_4bit_load_updown_counter_design(all_rtl, dut_module):
        return build_deterministic_load_updown_counter_testbench(all_rtl, dut_module)
    has_overflow = re.search(r"\boverflow\b", all_rtl or "") is not None
    overflow_decl = "    wire overflow;\n" if has_overflow else ""
    overflow_port = "        .overflow(overflow)\n" if has_overflow else ""

    port_block = f"""        .clk(clk),
        .rst_n(rst_n),
        .en(en),
        .count(count){',' if has_overflow else ''}
{overflow_port}"""

    return f"""`timescale 1ns / 1ps

module tb_{dut_module};

    reg clk;
    reg rst_n;
    reg en;
    wire [3:0] count;
{overflow_decl}
    reg test_failed;
    reg [3:0] expected_count;
    reg [3:0] hold_count;
    integer i;

    {dut_module} dut (
{port_block}    );

    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    initial begin
        test_failed = 1'b0;
        expected_count = 4'h0;
        hold_count = 4'h0;
        rst_n = 1'b0;
        en = 1'b0;

        #12;
        if (count !== 4'h0) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: reset count expected 0, got %b", count);
            test_failed = 1'b1;
        end

        @(negedge clk);
        rst_n = 1'b1;
        en = 1'b0;
        @(posedge clk);
        #1;
        if (count !== 4'h0) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: count changed while disabled after reset, got %b", count);
            test_failed = 1'b1;
        end

        @(negedge clk);
        en = 1'b1;
        expected_count = 4'h0;
        for (i = 0; i < 20; i = i + 1) begin
            @(posedge clk);
            #1;
            expected_count = expected_count + 1'b1;
            if (count !== expected_count) begin
                $display("SIM_RESULT: FAILED");
                $display("ERROR: count mismatch at step %0d, expected %b, got %b", i, expected_count, count);
                test_failed = 1'b1;
            end

        end

        @(negedge clk);
        en = 1'b0;
        hold_count = count;
        for (i = 0; i < 3; i = i + 1) begin
            @(posedge clk);
            #1;
            if (count !== hold_count) begin
                $display("SIM_RESULT: FAILED");
                $display("ERROR: count changed while disabled, expected %b, got %b", hold_count, count);
                test_failed = 1'b1;
            end

        end

        @(negedge clk);
        en = 1'b1;
        @(posedge clk);
        #1;
        hold_count = hold_count + 1'b1;
        if (count !== hold_count) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: count did not increment after re-enable, expected %b, got %b", hold_count, count);
            test_failed = 1'b1;
        end

        #2;
        rst_n = 1'b0;
        #1;
        if (count !== 4'h0) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: async reset count expected 0, got %b", count);
            test_failed = 1'b1;
        end

        if (test_failed) begin
            $display("SIM_RESULT: FAILED");
        end else begin
            $display("SIM_RESULT: PASSED");
        end
        $stop;
    end

endmodule
"""


def build_deterministic_load_updown_counter_testbench(all_rtl, dut_module):
    has_overflow = re.search(r"\boverflow\b", all_rtl or "") is not None
    has_underflow = re.search(r"\bunderflow\b", all_rtl or "") is not None
    overflow_decl = "    wire overflow;\n" if has_overflow else ""
    underflow_decl = "    wire underflow;\n" if has_underflow else ""
    overflow_port = "        .overflow(overflow),\n" if has_overflow else ""
    underflow_port = "        .underflow(underflow)\n" if has_underflow else ""
    trailing_count_comma = "," if has_overflow or has_underflow else ""
    trailing_overflow_comma = "," if has_overflow and has_underflow else ""

    return f"""`timescale 1ns / 1ps

module tb_{dut_module};

    reg clk;
    reg rst_n;
    reg en;
    reg load;
    reg up_down;
    reg [3:0] load_value;
    wire [3:0] count;
{overflow_decl}{underflow_decl}
    reg test_failed;
    integer i;

    {dut_module} dut (
        .clk(clk),
        .rst_n(rst_n),
        .en(en),
        .load(load),
        .up_down(up_down),
        .load_value(load_value),
        .count(count){trailing_count_comma}
{overflow_port.replace('),', ')' + trailing_overflow_comma) if has_overflow else ''}{underflow_port}    );

    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    initial begin
        test_failed = 1'b0;
        rst_n = 1'b0;
        en = 1'b0;
        load = 1'b0;
        up_down = 1'b1;
        load_value = 4'h0;

        #12;
        if (count !== 4'h0) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: reset count expected 0, got %b", count);
            test_failed = 1'b1;
        end

        @(negedge clk);
        rst_n = 1'b1;
        en = 1'b0;
        load = 1'b0;
        @(posedge clk);
        #1;
        if (count !== 4'h0) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: disabled counter changed after reset, got %b", count);
            test_failed = 1'b1;
        end

        @(negedge clk);
        load_value = 4'ha;
        load = 1'b1;
        en = 1'b0;
        @(posedge clk);
        #1;
        if (count !== 4'ha) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: load expected a, got %b", count);
            test_failed = 1'b1;
        end

        @(negedge clk);
        load = 1'b0;
        en = 1'b1;
        up_down = 1'b1;
        for (i = 0; i < 3; i = i + 1) begin
            @(posedge clk);
            #1;
        end
        if (count !== 4'hd) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: up count from a for 3 cycles expected d, got %b", count);
            test_failed = 1'b1;
        end

        @(negedge clk);
        load = 1'b1;
        load_value = 4'hf;
        @(posedge clk);
        #1;
        if (count !== 4'hf) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: load expected f, got %b", count);
            test_failed = 1'b1;
        end

        @(negedge clk);
        load = 1'b0;
        en = 1'b1;
        up_down = 1'b1;
        @(posedge clk);
        #1;
        if (count !== 4'h0) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: overflow wrap expected 0, got %b", count);
            test_failed = 1'b1;
        end
{'''        if (overflow !== 1'b1) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: overflow flag expected 1 on wrap up");
            test_failed = 1'b1;
        end
''' if has_overflow else ''}
{'''        if (underflow !== 1'b0) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: underflow flag expected 0 on wrap up");
            test_failed = 1'b1;
        end
''' if has_underflow else ''}
        @(posedge clk);
        #1;
        if (count !== 4'h1) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: count after overflow expected 1, got %b", count);
            test_failed = 1'b1;
        end
{'''        if (overflow !== 1'b0) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: overflow flag should clear after one cycle");
            test_failed = 1'b1;
        end
''' if has_overflow else ''}
        @(negedge clk);
        load = 1'b1;
        load_value = 4'h0;
        @(posedge clk);
        #1;
        if (count !== 4'h0) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: load expected 0, got %b", count);
            test_failed = 1'b1;
        end

        @(negedge clk);
        load = 1'b0;
        en = 1'b1;
        up_down = 1'b0;
        @(posedge clk);
        #1;
        if (count !== 4'hf) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: underflow wrap expected f, got %b", count);
            test_failed = 1'b1;
        end
{'''        if (underflow !== 1'b1) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: underflow flag expected 1 on wrap down");
            test_failed = 1'b1;
        end
''' if has_underflow else ''}
{'''        if (overflow !== 1'b0) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: overflow flag expected 0 on wrap down");
            test_failed = 1'b1;
        end
''' if has_overflow else ''}
        @(posedge clk);
        #1;
        if (count !== 4'he) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: count after underflow expected e, got %b", count);
            test_failed = 1'b1;
        end
{'''        if (underflow !== 1'b0) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: underflow flag should clear after one cycle");
            test_failed = 1'b1;
        end
''' if has_underflow else ''}
        @(negedge clk);
        en = 1'b0;
        @(posedge clk);
        #1;
        if (count !== 4'he) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: disabled counter expected hold e, got %b", count);
            test_failed = 1'b1;
        end

        #2;
        rst_n = 1'b0;
        #1;
        if (count !== 4'h0) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: async reset count expected 0, got %b", count);
            test_failed = 1'b1;
        end

        if (test_failed) begin
            $display("SIM_RESULT: FAILED");
        end else begin
            $display("SIM_RESULT: PASSED");
        end
        $stop;
    end

endmodule
"""


def is_4bit_load_updown_counter_design(all_rtl, dut_module):
    text = all_rtl or ""
    if not dut_module or not re.search(rf"\bmodule\s+{re.escape(dut_module)}\b", text):
        return False
    required = [
        r"\bload\b",
        r"\bup_down\b",
        r"\bload_value\b",
        r"\[3\s*:\s*0\]\s*load_value|\bload_value\s*\[3\s*:\s*0\]",
    ]
    return all(re.search(pattern, text) for pattern in required)


def is_4bit_counter_design(all_rtl, dut_module):
    text = all_rtl or ""
    if not dut_module or not re.search(rf"\bmodule\s+{re.escape(dut_module)}\b", text):
        return False
    required = [
        r"\bclk\b",
        r"\brst_n\b",
        r"\ben\b",
        r"\bcount\b",
        r"\[3\s*:\s*0\]\s*count|\bcount\s*\[3\s*:\s*0\]",
        r"posedge\s+clk",
        r"negedge\s+rst_n",
    ]
    return all(re.search(pattern, text) for pattern in required)


def task_generate_xdc(ctx, error_msg=None, current_xdc=None):
    print(">>> [约束专家] 正在基于结构化 board pin database 生成物理约束...")
    xdc_notes = load_xilinx_skill_notes(
        ctx,
        filenames=["xdc_constraints_notes.md", "tcl_commands_notes.md"],
        max_chars=3000,
    )
    if xdc_notes:
        print(">>> [约束专家] 已加载本地 Xilinx/XDC 约束规则；仍只使用 board_pins.json 生成引脚。")
    try:
        xdc_code = generate_structured_xdc(ctx)
        print(f"✅ [XDC] 已生成结构化约束: {ctx.xdc_file}")
        return xdc_code
    except Exception as exc:
        rejected_log = os.path.join(ctx.save_dir, "xdc_rejected_reason.txt")
        with open(rejected_log, "w", encoding="utf-8") as f:
            f.write(str(exc))
            if xdc_notes:
                f.write("\n\n[Xilinx/XDC 本地规则摘要]\n" + xdc_notes)
            if error_msg:
                f.write("\n\n[上游 Vivado 报错]\n" + error_msg)
            if current_xdc:
                f.write("\n\n[被拒绝的历史 XDC]\n" + current_xdc)
        raise


def infer_dut_module(ctx):
    modules = []
    if os.path.exists(ctx.src_dir):
        for fname in os.listdir(ctx.src_dir):
            if not fname.endswith(".v"):
                continue
            content = open(os.path.join(ctx.src_dir, fname), "r", encoding="utf-8", errors="ignore").read()
            modules.extend(re.findall(r"\bmodule\s+([a-zA-Z_][a-zA-Z0-9_$]*)\b", content))
    non_tb = [m for m in modules if not m.startswith("tb_")]
    preferred = [m for m in non_tb if "top" in m.lower()]
    if preferred:
        return preferred[0]
    if non_tb:
        return non_tb[0]
    return "top_module"


def save_rejected_testbench(ctx, code, problems):
    rejected_v = os.path.join(ctx.save_dir, "tb_rejected_last.v")
    rejected_log = os.path.join(ctx.save_dir, "tb_rejected_reason.txt")
    with open(rejected_v, "w", encoding="utf-8") as f:
        f.write(code or "")
    with open(rejected_log, "w", encoding="utf-8") as f:
        f.write("\n".join(problems))
