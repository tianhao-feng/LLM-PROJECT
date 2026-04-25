import glob
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

from .code_utils import infer_testbench_module_name, validate_testbench_contract
from .diagnostics import classify_iverilog_log, format_iverilog_result


@dataclass
class CommandResult:
    label: str
    command: list
    returncode: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    timeout: bool = False
    missing_tool: bool = False
    exception: str = ""

    @property
    def output(self):
        return (self.stdout + "\n" + self.stderr).strip()

    @property
    def ok(self):
        return self.returncode == 0 and not self.timeout and not self.missing_tool and not self.exception

    def failure_summary(self):
        if self.missing_tool:
            return f"{self.label} 工具未找到: {self.command[0]}"
        if self.timeout:
            return f"{self.label} 执行超时。"
        if self.exception:
            return f"{self.label} 执行异常: {self.exception}"
        if self.returncode not in (0, None):
            return f"{self.label} 返回码异常: {self.returncode}"
        return f"{self.label} 执行失败"


def run_command(command, label="command", cwd=None, timeout=None, merge_stderr=False):
    command = normalize_command(command)
    missing = missing_executable(command[0])
    if missing:
        return CommandResult(label=label, command=command, missing_tool=True, exception=missing)
    try:
        res = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            timeout=timeout,
            shell=needs_shell(command[0]),
        )
        return CommandResult(
            label=label,
            command=command,
            returncode=res.returncode,
            stdout=res.stdout or "",
            stderr="" if merge_stderr else (res.stderr or ""),
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            label=label,
            command=command,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
            timeout=True,
        )
    except FileNotFoundError as exc:
        return CommandResult(label=label, command=command, missing_tool=True, exception=str(exc))
    except Exception as exc:
        return CommandResult(label=label, command=command, exception=str(exc))


def run_streaming_command(command, label="command", cwd=None, timeout=None, on_line=None):
    command = normalize_command(command)
    missing = missing_executable(command[0])
    if missing:
        return CommandResult(label=label, command=command, missing_tool=True, exception=missing)
    stdout_chunks = []
    start = time.time()
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            shell=needs_shell(command[0]),
        )
        while True:
            if timeout is not None and time.time() - start > timeout:
                process.kill()
                return CommandResult(
                    label=label,
                    command=command,
                    returncode=process.poll(),
                    stdout="".join(stdout_chunks),
                    timeout=True,
                )
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                stdout_chunks.append(line)
                if on_line:
                    on_line(line)
        return CommandResult(
            label=label,
            command=command,
            returncode=process.returncode,
            stdout="".join(stdout_chunks),
        )
    except FileNotFoundError as exc:
        return CommandResult(label=label, command=command, missing_tool=True, exception=str(exc))
    except Exception as exc:
        return CommandResult(label=label, command=command, exception=str(exc), stdout="".join(stdout_chunks))


def missing_executable(executable):
    if not executable:
        return "空执行路径"
    expanded = os.path.expandvars(os.path.expanduser(executable))
    has_path_sep = os.path.sep in expanded or (os.path.altsep and os.path.altsep in expanded)
    if has_path_sep or os.path.splitext(expanded)[1]:
        if os.path.exists(expanded):
            return ""
        if shutil.which(expanded):
            return ""
        return "文件不存在且不在 PATH 中"
    if shutil.which(expanded):
        return ""
    return "不在 PATH 中"


def normalize_command(command):
    command = [str(part) for part in command]
    if command:
        command[0] = os.path.expandvars(os.path.expanduser(command[0]))
    return command


def needs_shell(executable):
    return os.name == "nt" and os.path.splitext(executable)[1].lower() in {".bat", ".cmd"}


def run_iverilog_checks(ctx):
    print(">>> [Linter审查专家] 正在审查接口与语法...")
    v_files = glob.glob(os.path.join(ctx.src_dir, "*.v"))
    if not v_files:
        return False, "未找到 RTL 文件"

    res_rtl = run_command(
        [ctx.iverilog_path, "-Wall", "-t", "null"] + v_files,
        label="Icarus Verilog RTL",
        timeout=ctx.iverilog_timeout,
    )
    if res_rtl.missing_tool or res_rtl.timeout or res_rtl.exception:
        return False, res_rtl.failure_summary() + "\n" + res_rtl.output
    err_rtl = res_rtl.output
    rtl_result = classify_iverilog_log(err_rtl, res_rtl.returncode)
    if rtl_result["errors"] or rtl_result["blocking_warnings"]:
        if "0xc0000279" not in err_rtl:
            return False, format_iverilog_result("RTL", rtl_result)
    elif rtl_result["nonblocking_warnings"]:
        print("⚠️ [Linter] RTL 存在非阻断警告，已记录但不触发自愈。")

    if os.path.exists(ctx.tb_file):
        tb_content = open(ctx.tb_file, "r", encoding="utf-8", errors="ignore").read()
        tb_ok, tb_problems = validate_testbench_contract(tb_content, expected_dut_module=discover_top_module(ctx))
        if not tb_ok:
            return False, "Testbench 合同检查未通过:\n" + "\n".join(f"- {p}" for p in tb_problems)
        res_tb = run_command(
            [ctx.iverilog_path, "-Wall", "-t", "null"] + v_files + [ctx.tb_file],
            label="Icarus Verilog Testbench",
            timeout=ctx.iverilog_timeout,
        )
        if res_tb.missing_tool or res_tb.timeout or res_tb.exception:
            return False, res_tb.failure_summary() + "\n" + res_tb.output
        err_tb = res_tb.output
        tb_result = classify_iverilog_log(err_tb, res_tb.returncode)
        if tb_result["errors"] or tb_result["blocking_warnings"]:
            if "0xc0000279" not in err_tb:
                return False, format_iverilog_result("Testbench", tb_result)
        elif tb_result["nonblocking_warnings"]:
            print("⚠️ [Linter] Testbench 存在非阻断警告，已记录但不触发自愈。")
    return True, "PASS"


def task_run_modelsim(ctx):
    v_sim_pattern = os.path.join(ctx.src_dir, "*.v").replace("\\", "/")
    tb_sim = ctx.tb_file.replace("\\", "/")
    with open(ctx.tb_file, "r", encoding="utf-8", errors="ignore") as f:
        tb_content = f.read()
    tb_module = infer_testbench_module_name(tb_content, expected_dut_module=discover_top_module(ctx))
    if not tb_module:
        return False, "无法从 Testbench 中解析仿真顶层 module 名称"
    with open(os.path.join(ctx.sim_dir, "run.do"), "w", encoding="utf-8") as f:
        f.write(f"vlib work\nvlog \"{v_sim_pattern}\"\nvlog \"{tb_sim}\"\nvsim -c -do \"onerror {{quit -f}}; run 2ms; quit -f\" work.{tb_module}\n")
    res = run_command(
        [ctx.modelsim_path, "-c", "-do", "run.do"],
        label="ModelSim",
        cwd=ctx.sim_dir,
        timeout=ctx.modelsim_timeout,
        merge_stderr=True,
    )
    if res.missing_tool or res.timeout or res.exception:
        return False, res.failure_summary() + "\n" + res.output[-1500:]
    return evaluate_modelsim_output(res.stdout, res.returncode)


def evaluate_modelsim_output(stdout, returncode):
    stdout = stdout or ""
    stdout_lower = stdout.lower()
    pass_count = stdout_lower.count("sim_result: passed")
    fail_count = stdout_lower.count("sim_result: failed")
    error_markers = ["error:", "fatal:", "mismatch", "timeout", "x detected", "assertion", "failure"]
    has_real_error = fail_count > 0 or any(kw in stdout_lower for kw in error_markers)
    tail = stdout[-1500:]
    if pass_count == 1 and not has_real_error and returncode == 0:
        return True, tail
    if pass_count > 1:
        return False, "ModelSim 输出多个 SIM_RESULT: PASSED，Testbench 结果不唯一。\n" + tail
    if pass_count == 0 and not has_real_error:
        return False, "ModelSim 未输出明确通过标志 SIM_RESULT: PASSED。\n" + tail
    if returncode != 0 and pass_count == 1 and not has_real_error:
        return False, f"ModelSim 返回码异常: {returncode}。\n" + tail
    return False, tail


def run_vivado_build(ctx):
    print(">>> [构建] 启动 Vivado 全系统综合...")
    out_dir_fix, xdc_fix = ctx.output_dir.replace("\\", "/"), ctx.xdc_file.replace("\\", "/")
    script_dir = os.path.join(ctx.run_dir, "scripts")
    log_dir = os.path.join(ctx.run_dir, "vivado_logs")
    os.makedirs(script_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)
    run_tcl = os.path.join(script_dir, "run.tcl")
    vivado_log = os.path.join(log_dir, "vivado.log")
    vivado_jou = os.path.join(log_dir, "vivado.jou")
    top_module = discover_top_module(ctx)
    if not top_module:
        return False, "无法自动识别顶层模块。请检查 src 下是否存在未被其他模块例化的 module。"
    print(f">>> [构建] 自动识别 Vivado 顶层模块: {top_module}")
    add_files_str = "\n    ".join(
        [f'add_files {{ "{os.path.join(ctx.src_dir, f).replace(chr(92), "/")}" }}' for f in os.listdir(ctx.src_dir) if f.endswith(".v")]
    )
    tcl_script = f"""
    create_project -force ai_project "{out_dir_fix}" -part {ctx.fpga_part}
    {add_files_str}
    if {{ [file exists "{xdc_fix}"] }} {{ add_files -fileset constrs_1 -norecurse "{xdc_fix}" }}
    update_compile_order -fileset sources_1
    set_property top {top_module} [current_fileset]
    set_property source_mgmt_mode DisplayOnly [current_project]
    synth_design -top {top_module} -part {ctx.fpga_part}
    opt_design
    place_design
    route_design
    report_utilization -file "{out_dir_fix}/report_utilization.rpt"
    report_timing_summary -delay_type min_max -max_paths 10 -file "{out_dir_fix}/report_timing.rpt"
    report_power -file "{out_dir_fix}/report_power.rpt"
    write_bitstream -force "{out_dir_fix}/{top_module}.bit"
    exit 0
    """
    with open(run_tcl, "w", encoding="utf-8") as f:
        f.write(tcl_script)
    err_buf, success = "", False

    def handle_vivado_line(line):
        nonlocal err_buf, success
        if ("ERROR" in line or "CRITICAL WARNING" in line) and not line.strip().startswith("#"):
            err_buf += line + "\n"
        elif "write_bitstream completed successfully" in line or "impl_1_route_report_power_0" in line:
            success = True

    res = run_streaming_command(
        [ctx.vivado_path, "-mode", "batch", "-source", run_tcl, "-log", vivado_log, "-journal", vivado_jou],
        label="Vivado",
        cwd=log_dir,
        timeout=ctx.vivado_timeout,
        on_line=handle_vivado_line,
    )
    if res.missing_tool or res.timeout or res.exception:
        return False, res.failure_summary() + "\n" + (err_buf or res.output[-3000:])
    if res.returncode == 0 and success:
        return True, err_buf
    return False, err_buf or res.failure_summary() + "\n" + res.output[-3000:]


def discover_top_module(ctx):
    modules = set()
    instantiated = set()
    module_decl = re.compile(r"^\s*module\s+([a-zA-Z_][a-zA-Z0-9_$]*)\b", re.MULTILINE)
    inst_decl = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_$]*)\s+(?:#\s*\([^;]*?\)\s*)?([a-zA-Z_][a-zA-Z0-9_$]*)\s*\(", re.MULTILINE | re.DOTALL)
    keywords = {"module", "always", "if", "for", "case", "assign", "function", "task", "begin"}

    for path in glob.glob(os.path.join(ctx.src_dir, "*.v")):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        modules.update(module_decl.findall(content))
        for mod_name, inst_name in inst_decl.findall(content):
            if mod_name not in keywords and inst_name not in keywords:
                instantiated.add(mod_name)

    candidates = sorted([m for m in modules if m not in instantiated and not m.startswith("tb_")])
    if not candidates:
        return None
    preferred = [m for m in candidates if "top" in m.lower()]
    if preferred:
        return preferred[0]
    return candidates[0]


def parse_vivado_reports(ctx):
    stats = {"lut_u": "0", "lut_t": "0", "lut_p": "0", "ff_u": "0", "ff_t": "0", "ff_p": "0", "wns": "N/A", "fmax": "N/A", "power": "N/A"}
    try:
        util = os.path.join(ctx.output_dir, "report_utilization.rpt")
        if os.path.exists(util):
            for line in open(util, "r", encoding="utf-8", errors="ignore"):
                cols = [c.strip() for c in line.split("|")]
                if len(cols) < 6:
                    continue
                if "Slice LUTs" in cols[1] and "Logic" not in cols[1]:
                    stats.update({"lut_u": cols[2], "lut_t": cols[4], "lut_p": cols[5]})
                if "Slice Registers" in cols[1]:
                    stats.update({"ff_u": cols[2], "ff_t": cols[4], "ff_p": cols[5]})
        timing = os.path.join(ctx.output_dir, "report_timing.rpt")
        if os.path.exists(timing):
            text = open(timing, "r", encoding="utf-8", errors="ignore").read()
            match = re.search(r"WNS\(ns\).*?TNS\(ns\).*?\n.*?\n\s*(-?\d+\.?\d*)", text, re.DOTALL)
            if match:
                wns = float(match.group(1))
                stats["wns"], stats["fmax"] = f"{wns} ns", f"{1000.0 / (20.0 - wns):.2f} MHz" if wns > 0 else "时序违例"
        power = os.path.join(ctx.output_dir, "report_power.rpt")
        if os.path.exists(power):
            text = open(power, "r", encoding="utf-8", errors="ignore").read()
            match = re.search(r"Total On-Chip Power \(W\)\s*\|\s*([0-9\.]+)", text)
            if match:
                stats["power"] = match.group(1) + " W"
    except Exception:
        pass
    print(
        f"\n{'=' * 45}\n系统 PPA 报告\n{'=' * 45}\n"
        f"LUTs: {stats['lut_u']}/{stats['lut_t']} ({stats['lut_p']}%)\n"
        f"FFs : {stats['ff_u']}/{stats['ff_t']} ({stats['ff_p']}%)\n"
        f"FMax: {stats['fmax']}\nPower: {stats['power']}\n{'=' * 45}\n"
    )
