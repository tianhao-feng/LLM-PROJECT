import os
import re


VERILOG_2001_RULES = """
【Verilog-2001 硬性约束】
1. 只生成 Verilog-2001 兼容代码，文件扩展名保持 .v。
2. 禁止 SystemVerilog 语法：logic、always_ff、always_comb、always_latch、typedef、enum、struct、interface、package、import、unique、priority、final。
3. 禁止块内变量声明，例如 always/initial/begin 内部的 integer i;。
4. 禁止 for (integer i = ...)、for (int i = ...)、foreach。循环变量必须在 module 作用域声明，例如 integer i; 然后 for (i = 0; ... )。
5. 禁止使用 SystemVerilog 数组初始化语法、'{...}、++、--。
6. 组合逻辑使用 always @(*)；时序逻辑使用 always @(posedge clk or negedge rst_n)。
"""


def clean_code(text, lang="verilog"):
    fence = "`" * 3
    pattern = rf"{fence}[^\n]*\n(.*?)\n{fence}"
    match = re.search(pattern, text or "", re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()

    text = re.sub(r"###\s*解释.*", "", text or "", flags=re.DOTALL | re.IGNORECASE)
    code = text.strip()
    if lang in ["verilog", "tb"]:
        code = re.sub(r"#\s*\(?\s*(\d+)\s*(?:ns|ps|us|ms)\s*\)?", r"#\1", code, flags=re.IGNORECASE)
        if lang == "tb" and "`timescale" not in code and "module" in code:
            code = "`timescale 1ns / 1ps\n" + code
        if lang == "tb":
            code = re.sub(r"\$finish\b", "$stop", code)
    return code


def validate_verilog_code(code, filename, expected_module=None, require_sim_result=False):
    problems = []
    if not code or not code.strip():
        return False, ["模型输出为空"]

    stripped = code.strip()
    lowered = stripped.lower()
    bad_markers = ["api 报错", "网络请求异常", "```", "here is", "下面是", "以下是", "解释如下"]
    for marker in bad_markers:
        if marker in lowered:
            problems.append(f"输出包含非 Verilog 内容或错误标记: {marker}")

    if not re.search(r"\bmodule\s+[a-zA-Z_][a-zA-Z0-9_$]*\b", stripped):
        problems.append("缺少 module 定义")
    if not re.search(r"\bendmodule\b", stripped):
        problems.append("缺少 endmodule")
    if expected_module and not re.search(rf"\bmodule\s+{re.escape(expected_module)}\b", stripped):
        problems.append(f"模块名不匹配，期望 module {expected_module}")
    if require_sim_result:
        problems.extend(validate_testbench_contract(stripped)[1])
    if filename and not filename.endswith(".v"):
        problems.append(f"非法 Verilog 文件名: {filename}")
    problems.extend(find_verilog_2001_violations(stripped))
    return len(problems) == 0, problems


def validate_testbench_contract(code, expected_dut_module=None):
    problems = []
    stripped = (code or "").strip()
    if not stripped:
        return False, ["Testbench 为空"]

    code_no_comments = strip_verilog_comments(stripped)
    lowered = code_no_comments.lower()
    tb_module = infer_testbench_module_name(code_no_comments, expected_dut_module=expected_dut_module)
    if not tb_module:
        problems.append("Testbench 缺少可作为仿真顶层的 module 定义")
    if "sim_result: passed" not in lowered:
        problems.append("Testbench 必须在成功路径打印 SIM_RESULT: PASSED")
    if "sim_result: failed" not in lowered:
        problems.append("Testbench 必须在失败路径打印 SIM_RESULT: FAILED")
    if not re.search(r"\$stop\b", code_no_comments):
        problems.append("Testbench 仿真结束必须调用 $stop")
    if re.search(r"\$finish\b", code_no_comments):
        problems.append("Testbench 禁止使用 $finish，请使用 $stop")
    if not re.search(r"\bif\s*\(", code_no_comments):
        problems.append("Testbench 必须包含条件检查，不能只跑时钟或固定延时后直接 PASS")
    if not re.search(r"(==|!=|===|!==|<=|>=|<|>)", code_no_comments):
        problems.append("Testbench 必须包含比较检查，用于验证 DUT 输出或状态")
    if expected_dut_module and not re.search(
        rf"(?<!module\s)\b{re.escape(expected_dut_module)}\b\s*(?:#\s*\([\s\S]*?\)\s*)?[a-zA-Z_][a-zA-Z0-9_$]*\s*\(",
        code_no_comments,
        flags=re.MULTILINE,
    ):
        problems.append(f"Testbench 必须例化 DUT 模块 {expected_dut_module}")
    return len(problems) == 0, problems


def infer_testbench_module_name(code, expected_dut_module=None):
    code_no_comments = strip_verilog_comments(code)
    modules = re.findall(r"\bmodule\s+([a-zA-Z_][a-zA-Z0-9_$]*)\b", code_no_comments)
    if not modules:
        return None

    candidates = [name for name in modules if name != expected_dut_module]
    if not candidates:
        return None

    preferred = [name for name in candidates if name.lower().startswith("tb")]
    if preferred:
        return preferred[0]

    test_named = [name for name in candidates if "test" in name.lower() or "bench" in name.lower()]
    if test_named:
        return test_named[0]

    return candidates[0]


def strip_verilog_comments(code):
    code = re.sub(r"/\*[\s\S]*?\*/", "", code or "")
    return re.sub(r"//.*", "", code)


def find_verilog_2001_violations(code):
    violations = []
    code_no_comments = strip_verilog_comments(code)
    checks = [
        (r"\blogic\b", "禁止 SystemVerilog logic，请使用 wire/reg"),
        (r"\balways_ff\b|\balways_comb\b|\balways_latch\b", "禁止 SystemVerilog always_ff/always_comb/always_latch"),
        (r"\btypedef\b|\benum\b|\bstruct\b|\binterface\b|\bpackage\b|\bimport\b", "禁止 SystemVerilog 类型/包/interface 语法"),
        (r"\bunique\b|\bpriority\b|\bfinal\b", "禁止 SystemVerilog unique/priority/final"),
        (r"for\s*\(\s*(integer|int)\s+[a-zA-Z_][a-zA-Z0-9_]*\s*=", "禁止 for 循环头部声明变量，循环变量必须在 module 作用域声明"),
        (r"\bforeach\s*\(", "禁止 SystemVerilog foreach"),
        (r"'\s*\{", "禁止 SystemVerilog 聚合初始化 '{...}"),
        (r"\+\+|--", "禁止 ++/--，请使用 i = i + 1 / i = i - 1"),
    ]
    for pattern, message in checks:
        if re.search(pattern, code_no_comments):
            violations.append(message)

    for match in re.finditer(r"\bbegin\b(?P<body>.*?)\bend\b", code_no_comments, flags=re.DOTALL):
        body = match.group("body")
        if re.search(r"\b(integer|int|reg|wire)\s+(\[[^\]]+\]\s*)?[a-zA-Z_][a-zA-Z0-9_]*\s*;", body):
            violations.append("禁止在 begin/end 块内部声明 integer/int/reg/wire，必须移到 module 作用域")
            break
    return violations


def normalize_verilog_code(code):
    code = (code or "").strip()
    if code and "`timescale" not in code and re.search(r"\bmodule\b", code):
        code = "`timescale 1ns / 1ps\n\n" + code
    return code


def write_verified_verilog(path, code, expected_module=None, require_sim_result=False, expected_dut_module=None):
    fname = os.path.basename(path)
    code = normalize_verilog_code(code)
    ok, problems = validate_verilog_code(code, fname, expected_module, require_sim_result)
    if ok and require_sim_result:
        ok, problems = validate_testbench_contract(code, expected_dut_module=expected_dut_module)
    if not ok:
        return False, problems
    with open(path, "w", encoding="utf-8") as f:
        f.write(code)
    return True, []


def read_all_src_code(ctx):
    all_code = ""
    if not os.path.exists(ctx.src_dir):
        return all_code
    for fname in os.listdir(ctx.src_dir):
        if fname.endswith(".v"):
            with open(os.path.join(ctx.src_dir, fname), "r", encoding="utf-8") as file:
                all_code += f"// --- File: {fname} ---\n{file.read()}\n\n"
    return all_code


def build_targeted_context(error_msg, src_dir):
    faulty_files = set(re.findall(r"([a-zA-Z0-9_]+\.v)", error_msg or ""))
    all_v_files = [f for f in os.listdir(src_dir) if f.endswith(".v")]
    valid_faulty_files = {f for f in faulty_files if f in all_v_files}

    if not valid_faulty_files:
        class Tmp:
            pass
        tmp = Tmp()
        tmp.src_dir = src_dir
        return read_all_src_code(tmp), "全量代码 (未追踪到特定依赖)"

    file_to_modules = {}
    for fname in all_v_files:
        with open(os.path.join(src_dir, fname), "r", encoding="utf-8") as f:
            content = f.read()
        file_to_modules[fname] = re.findall(r"\bmodule\s+([a-zA-Z0-9_]+)\b", content)

    related_files = set(valid_faulty_files)
    for fname in all_v_files:
        with open(os.path.join(src_dir, fname), "r", encoding="utf-8") as f:
            content = f.read()
        for err_f in valid_faulty_files:
            for mod in file_to_modules.get(err_f, []):
                if fname != err_f and re.search(rf"\b{mod}\b", content):
                    related_files.add(fname)
        if fname in valid_faulty_files:
            for other_f in all_v_files:
                if other_f == fname:
                    continue
                for mod in file_to_modules.get(other_f, []):
                    if re.search(rf"\b{mod}\b", content):
                        related_files.add(other_f)

    context = ""
    for fname in related_files:
        with open(os.path.join(src_dir, fname), "r", encoding="utf-8") as f:
            context += f"// --- File: {fname} ---\n{f.read()}\n\n"
    return context, ", ".join(related_files)
