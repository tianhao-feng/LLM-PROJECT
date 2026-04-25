import json
import os
import re

from .code_utils import VERILOG_2001_RULES, build_targeted_context, clean_code, read_all_src_code, write_verified_verilog
from .llm_client import query_llm
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
    prompt_readme = f"""
你是一个资深 FPGA/RTL 项目架构师。你的任务不是写概念说明，而是生成一份可直接指导自动代码生成、仿真和综合的工程规格 README.md。

【用户需求】
{requirement}

【硬性工程约束】
1. 所有 RTL 必须使用 Verilog-2001，禁止 SystemVerilog。
2. 所有 RTL 文件扩展名为 .v。
3. 必须生成可被 Icarus Verilog、ModelSim 和 Vivado 2017.4 接受的代码。
4. 设计必须可综合，不允许只写行为级不可综合模型。
5. 时钟统一命名为 clk，复位统一命名为 rst_n，低有效异步复位。
6. 顶层模块名必须明确指定。如果用户没有指定，使用与设计语义匹配的顶层名，例如 riscv_cpu_top。
7. 所有子模块必须给出 filename、module_name、端口、位宽、方向、功能说明。
8. 不允许出现“待实现”“略”“根据需要扩展”“TODO”这类占位内容。
9. 必须明确最小可验证功能范围，避免生成超出当前任务的不可控复杂系统。

【README.md 必须按以下结构输出】

# 项目名称

## 1. 设计目标
- 用 3-6 条列出本工程必须实现的功能。
- 明确不实现的功能边界。

## 2. 语言与工具约束
- RTL 语言：Verilog-2001。
- 禁止使用 SystemVerilog 语法。
- 目标工具：Icarus Verilog、ModelSim、Vivado 2017.4。
- 时钟、复位、端口命名规则。

## 3. 顶层模块规范
必须包含一个 Markdown 表格：
| 项目 | 内容 |
|---|---|
| 顶层文件 | xxx.v |
| 顶层模块 | xxx |
| 时钟端口 | clk |
| 复位端口 | rst_n |
| 复位类型 | 低有效异步复位 |

然后给出顶层端口表：
| 端口名 | 方向 | 位宽 | 说明 |

## 4. 模块划分
必须给出模块清单表：
| filename | module_name | 是否顶层 | 功能 | 主要输入 | 主要输出 |

## 5. 模块详细接口
对每个模块分别给出：
### module_name
| 端口名 | 方向 | 位宽 | 说明 |
并说明该模块的组合逻辑、时序逻辑、复位行为。

## 6. 模块连接关系
必须说明：
- 哪个模块例化哪个模块。
- 关键内部信号名称。
- 数据流方向。
- 控制流方向。

## 7. 功能行为规格
用可验证条目描述设计行为。
如果是 CPU/RISC-V，需要明确：
- 支持的最小指令子集。
- PC 更新规则。
- 寄存器 x0 恒为 0。
- 访存规则。
- 分支/跳转规则。
- 写回规则。
- 是否支持流水线；如果支持，说明 hazard/forward/stall/flush 策略。

## 8. Testbench 验收标准
必须定义 testbench 需要验证的场景。
必须要求：
- 测试平台文件固定命名为 tb_top_module.v。
- 测试平台 module 名称可以自定，建议使用 tb_<dut_name>；系统会从 testbench 文件中自动解析仿真顶层。
- 成功时打印 SIM_RESULT: PASSED。
- 失败时打印 SIM_RESULT: FAILED。
- 仿真结束调用 $stop。
- 不允许只跑时钟不检查结果。

## 9. XDC/板卡约束需求
说明哪些顶层端口需要物理约束。
如果端口不是板卡 IO，而是外部存储器接口，也要说明约束策略。

## 10. 代码生成规则
- 每个 module 必须独立成文件。
- module_name 必须和架构表一致。
- 禁止空文件。
- 禁止解释文本混入 Verilog。
- 禁止 SystemVerilog。
- 循环变量必须声明在 module 作用域。
- 所有 always 块必须有明确复位或默认赋值，避免 latch。

【输出要求】
只输出完整 README.md 内容，不要输出解释。
内容必须具体、完整，不能少于 800 字。
"""
    prompt_readme += f"""

[Xilinx/Vivado/XDC reference notes]
Use the following local notes as hard engineering guidance when writing the README.
They are reference constraints, not user requirements. Do not copy them verbatim.
{xilinx_notes}
"""
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
        prompt = f"""你是一个修复 Bug 的主程。系统联合编译报错！
        【总体设计规范】\n{sys_spec}\n
        {VERILOG_2001_RULES}

        【报错信息】\n{error_context}
        【相关模块代码】\n{targeted_code}
        【历史教训】\n{err_mem}

        请严格修复。输出代码块第一行用注释标明覆写文件名，如 `// File: top_module.v`。
        只输出被修改的文件。"""
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
            prompt = f"""【总体设计规范】\n{sys_spec}\n【局部架构清单】\n{global_arch}\n
            {VERILOG_2001_RULES}

            【任务】：编写 `{fname}`。
            模块名：{mname}
            端口列表：{port_spec}
            功能描述：{mod.get('description', '')}
            {retry_hint}

            强制要求：
            1. 只输出一个完整 Verilog 代码块。
            2. 必须包含 `module {mname}` 和 `endmodule`。
            3. 禁止输出解释、Markdown 正文或对话文本。
            4. 必须严格满足 Verilog-2001 硬性约束。"""
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
        prompt = f"""被测系统：\n{all_rtl}\n【需求】:\n{ctx.user_requirement}\n{VERILOG_2001_RULES}
TB报错：\n{error_msg}\n【错误TB】:\n{current_tb}
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
        11. 只输出一个完整 Verilog 代码块。"""
    else:
        prompt = f"""全系统代码：\n{all_rtl}\n【设计需求】:\n{ctx.user_requirement}
        {VERILOG_2001_RULES}
        编写自校验 Testbench。
        硬性要求：
        1. Testbench 文件由系统保存为 tb_top_module.v。
        2. Testbench module 名称可以自定，建议使用 tb_{dut_module}；系统会从文件中自动解析仿真顶层。
        3. 被测 DUT 模块名是 {dut_module}，必须例化它。
        4. 根据需求主动检查 DUT 输出，不允许只跑时钟。
        5. 成功路径必须打印 $display("SIM_RESULT: PASSED");
        6. 失败路径必须打印 $display("SIM_RESULT: FAILED");
        7. 每一个检查点失败时必须打印 SIM_RESULT: FAILED，不能只打印普通 ERROR。
        8. 必须包含 if/比较语句主动检查 DUT 输出或关键状态，禁止只跑时钟或固定延时后直接 PASS。
        9. 时序电路采样规则：输入激励在 negedge clk 或远离 posedge 的时刻改变；检查寄存器输出必须在 posedge clk 之后 #1 再比较，或在下一个 negedge clk 比较。禁止用裸 #10 后直接把 loop index 当期望值。
        10. 对计数器这类寄存器 DUT，维护 expected_count 变量；每次有效 posedge 后先根据复位/使能规则更新 expected_count，再与 DUT 输出比较。
        11. 仿真结束必须调用 $stop，禁止 $finish。
        12. 只输出一个完整 Verilog 代码块。"""
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
