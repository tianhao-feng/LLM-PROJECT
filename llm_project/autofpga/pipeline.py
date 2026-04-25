import os
import re

from .agents import agent_architect, agent_coder, agent_router, task_generate_testbench, task_generate_xdc
from .code_utils import validate_testbench_contract
from .config import build_context, write_run_manifest
from .diagnostics import extract_and_classify_errors
from .rag import execute_rag_skill
from .tools import discover_top_module, parse_vivado_reports, run_iverilog_checks, run_vivado_build, task_run_modelsim


def execute_coding_pipeline(ctx, requirement):
    for path in [ctx.save_dir, ctx.src_dir, ctx.sim_dir, ctx.output_dir]:
        os.makedirs(path, exist_ok=True)
    write_run_manifest(ctx, "running", "prepare_workspace")

    print("\n🚀 [系统总控] 已进入代码生成与物理综合流水线！")
    write_run_manifest(ctx, "running", "architect")
    arch = agent_architect(ctx, requirement)
    if arch:
        write_run_manifest(ctx, "running", "generate_rtl", extra={"modules": arch.get("modules", [])})
        agent_coder(ctx, arch)
    missing_or_invalid = find_missing_or_invalid_modules(ctx, arch)
    if missing_or_invalid:
        raise RuntimeError("模块生成失败，停止流水线: " + ", ".join(missing_or_invalid))
    write_run_manifest(ctx, "running", "rtl_generated")

    current_tb = None
    tb_needs_regen, xdc_needs_regen = True, True

    for attempt in range(ctx.max_retries):
        print(f"\n--- 自愈闭环迭代 {attempt + 1}/{ctx.max_retries} ---")
        write_run_manifest(ctx, "running", "self_heal_iteration", extra={"attempt": attempt + 1})

        if tb_needs_regen:
            write_run_manifest(ctx, "running", "generate_testbench", extra={"attempt": attempt + 1})
            current_tb = generate_testbench_or_raise(ctx, current_tb)
            tb_needs_regen = False

        write_run_manifest(ctx, "running", "lint", extra={"attempt": attempt + 1})
        linter_ok, linter_msg = run_iverilog_checks(ctx)
        if not linter_ok:
            if is_infrastructure_error(linter_msg):
                raise RuntimeError(linter_msg)
            cats, adv, lvl = extract_and_classify_errors(ctx, linter_msg, "Linter联调")
            write_run_manifest(ctx, "running", "lint_repair", error=linter_msg, extra={"categories": cats})
            print(f"🛑 [审查报错] 召回主程统筹修复: {lvl}")
            if "Testbench" in linter_msg:
                current_tb = generate_testbench_or_raise(ctx, current_tb, f"{linter_msg}\n{adv}")
            else:
                agent_coder(ctx, None, error_context=f"{linter_msg}\n{adv}")
            tb_needs_regen, xdc_needs_regen = True, True
            continue

        write_run_manifest(ctx, "running", "simulate", extra={"attempt": attempt + 1})
        s_ok, s_msg = task_run_modelsim(ctx)
        if not s_ok:
            if is_infrastructure_error(s_msg):
                raise RuntimeError(s_msg)
            cats, adv, lvl = extract_and_classify_errors(ctx, s_msg, "仿真验证")
            write_run_manifest(ctx, "running", "simulation_repair", error=s_msg, extra={"categories": cats})
            if is_likely_testbench_oracle_error(s_msg):
                current_tb = generate_testbench_or_raise(
                    ctx,
                    current_tb,
                    f"{s_msg}\n{adv}\n请优先修复 testbench 的采样时序和期望值，不要修改 RTL。",
                )
                tb_needs_regen = False
            else:
                agent_coder(ctx, None, error_context=f"{s_msg}\n{adv}")
                tb_needs_regen = True
            xdc_needs_regen = True
            continue
        print("✅ 全系统逻辑验证通过！")
        write_run_manifest(ctx, "running", "simulation_passed")

        if xdc_needs_regen:
            write_run_manifest(ctx, "running", "generate_xdc")
            task_generate_xdc(ctx)
            xdc_needs_regen = False

        write_run_manifest(ctx, "running", "vivado_build", extra={"attempt": attempt + 1})
        b_ok, b_msg = run_vivado_build(ctx)
        if b_ok:
            print("🎉 🎉 系统设计圆满成功！比特流已就绪。")
            parse_vivado_reports(ctx)
            write_run_manifest(ctx, "succeeded", "complete")
            break

        cats, adv, lvl = extract_and_classify_errors(ctx, b_msg, "Vivado编译")
        if is_infrastructure_error(b_msg):
            raise RuntimeError(b_msg)
        write_run_manifest(ctx, "running", "vivado_repair", error=b_msg, extra={"categories": cats})
        err_ai = f"{b_msg}\n\n{adv}"
        if "未匹配到端口" in cats or "IO约束错误" in cats or "非法XDC" in cats:
            print(">>> 触发 XDC 独立自愈...")
            cur_xdc = open(ctx.xdc_file, "r", encoding="utf-8").read() if os.path.exists(ctx.xdc_file) else ""
            task_generate_xdc(ctx, error_msg=err_ai, current_xdc=cur_xdc)
        else:
            print(">>> 触发 RTL 后端自愈...")
            agent_coder(ctx, None, error_context=err_ai)
            tb_needs_regen, xdc_needs_regen = True, True
    else:
        raise RuntimeError(f"达到最大自愈次数仍未完成: {ctx.max_retries}")


def find_missing_or_invalid_modules(ctx, arch):
    problems = []
    if not arch or "modules" not in arch:
        return ["架构 JSON 缺少 modules"]
    for mod in arch["modules"]:
        fname = mod.get("filename")
        mname = mod.get("module_name")
        if not fname or not mname:
            problems.append(str(mod))
            continue
        path = os.path.join(ctx.src_dir, fname)
        if not os.path.exists(path):
            problems.append(f"{fname}: 文件缺失")
            continue
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.strip():
            problems.append(f"{fname}: 文件为空")
        elif not re.search(rf"\bmodule\s+{re.escape(mname)}\b", content):
            problems.append(f"{fname}: 缺少 module {mname}")
        elif "endmodule" not in content:
            problems.append(f"{fname}: 缺少 endmodule")
    return problems


def is_infrastructure_error(message):
    lowered = (message or "").lower()
    markers = [
        "工具未找到",
        "missing tool",
        "not found",
        "no such file",
        "不是内部或外部命令",
        "无法将",
        "permission denied",
        "拒绝访问",
    ]
    return any(marker in lowered for marker in markers)


def is_likely_testbench_oracle_error(message):
    lowered = (message or "").lower()
    markers = [
        "expected",
        "got",
        "mismatch",
        "wrap-around",
        "should be",
        "should increment",
        "should hold",
        "overflow should",
    ]
    has_tb_result = "sim_result: failed" in lowered
    has_oracle_word = any(marker in lowered for marker in markers)
    has_compile_error = any(marker in lowered for marker in ["syntax error", "unknown module", "vlog-", "vsim-3033"])
    return has_tb_result and has_oracle_word and not has_compile_error


def generate_testbench_or_raise(ctx, current_tb, error_msg=None):
    for tb_try in range(3):
        tb_code = task_generate_testbench(ctx, error_msg, current_tb)
        if os.path.exists(ctx.tb_file):
            with open(ctx.tb_file, "r", encoding="utf-8") as f:
                content = f.read()
            tb_ok, tb_problems = validate_testbench_contract(content, expected_dut_module=discover_top_module(ctx))
            if tb_ok:
                return tb_code
            print(f"⚠️ Testbench 合同检查失败: {'; '.join(tb_problems)}")
        print(f"⚠️ Testbench 生成失败或被拒写，重试 {tb_try + 1}/3")
        current_tb = tb_code or current_tb
    raise RuntimeError("Testbench 生成失败：未满足可解析TB顶层 / PASS / FAIL / $stop / DUT例化 / 自校验合同，已停止流水线。")


def main(ctx=None):
    ctx = ctx or build_context()
    print(f"=== FPGA 专家系统 (Agentic Workflow) | 模式: {ctx.work_mode} ===")
    write_run_manifest(ctx, "running", "start")

    try:
        if ctx.work_mode == "AUTO":
            write_run_manifest(ctx, "running", "route_intent")
            intent = agent_router(ctx.user_requirement)
            print(f"🎯 [总调度师] 诊断用户意图为: {intent}")
            write_run_manifest(ctx, "running", "intent_routed", extra={"intent": intent})
            if intent in ["TABLE", "CONCEPT"]:
                execute_rag_skill(ctx, ctx.user_requirement, intent)
                write_run_manifest(ctx, "succeeded", "rag_complete", extra={"intent": intent})
            elif intent == "CODE":
                execute_coding_pipeline(ctx, ctx.user_requirement)
        elif ctx.work_mode == "BUILD_ONLY":
            write_run_manifest(ctx, "running", "vivado_build_only")
            b_ok, b_msg = run_vivado_build(ctx)
            if b_ok:
                parse_vivado_reports(ctx)
                write_run_manifest(ctx, "succeeded", "build_only_complete")
            else:
                print(b_msg)
                raise RuntimeError(b_msg or "Vivado build failed")
        else:
            raise ValueError(f"未知运行模式: {ctx.work_mode}")
    except Exception as exc:
        write_run_manifest(ctx, "failed", "failed", error=exc)
        raise
