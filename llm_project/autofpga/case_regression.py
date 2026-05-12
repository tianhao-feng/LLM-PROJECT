import json
import os
import shutil
import time

from .example_audit import audit_example_dir, find_example_dirs
from .tools import run_iverilog_checks, run_vivado_build, task_run_modelsim


DEFAULT_REGRESSION_TOOLS = ["iverilog"]


def run_case_regression(ctx, cases_dir, tools=None, report_file=None):
    tools = normalize_regression_tools(tools)
    cases = find_example_dirs(cases_dir)
    run_id = time.strftime("%Y%m%d_%H%M%S")
    work_root = os.path.join(ctx.runs_base_dir, "regression", run_id)
    os.makedirs(work_root, exist_ok=True)

    results = [run_single_case(ctx, case_dir, work_root, tools, cases_dir) for case_dir in cases]
    report = {
        "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "registry_kind": "golden_case_regression",
        "cases_dir": os.path.basename(os.path.normpath(cases_dir)) or cases_dir,
        "work_root": work_root,
        "tools": tools,
        "total": len(results),
        "passed": len([result for result in results if result["status"] == "passed"]),
        "failed": len([result for result in results if result["status"] == "failed"]),
        "results": results,
    }

    report_file = report_file or os.path.join(work_root, "regression_report.json")
    os.makedirs(os.path.dirname(report_file), exist_ok=True)
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    report["report_file"] = report_file
    return report


def run_single_case(parent_ctx, case_dir, work_root, tools, cases_dir):
    case_name = os.path.basename(os.path.normpath(case_dir))
    audit = audit_example_dir(case_dir, examples_dir=cases_dir)
    work_case_dir = os.path.join(work_root, case_name)
    if os.path.exists(work_case_dir):
        shutil.rmtree(work_case_dir)
    shutil.copytree(case_dir, work_case_dir)

    result = {
        "name": case_name,
        "source_path": audit.get("path", case_name),
        "work_dir": work_case_dir,
        "top_module": audit.get("top_module"),
        "audit_problems": audit.get("problems", []),
        "audit_warnings": audit.get("warnings", []),
        "tools": [],
        "status": "passed",
    }
    if result["audit_problems"]:
        result["status"] = "failed"
        return result

    case_ctx = build_case_context(parent_ctx, work_case_dir)
    for tool in tools:
        tool_result = run_case_tool(case_ctx, tool)
        result["tools"].append(tool_result)
        if not tool_result["ok"]:
            result["status"] = "failed"
            break
    return result


def build_case_context(parent_ctx, work_case_dir):
    class CaseContext:
        pass

    case_ctx = CaseContext()
    case_ctx.save_dir = work_case_dir
    case_ctx.run_dir = os.path.join(work_case_dir, "runs")
    case_ctx.src_dir = os.path.join(work_case_dir, "src")
    case_ctx.tb_file = os.path.join(work_case_dir, "tb_top_module.v")
    case_ctx.xdc_file = os.path.join(work_case_dir, "constraints.xdc")
    case_ctx.sim_dir = os.path.join(case_ctx.run_dir, "sim_work")
    case_ctx.output_dir = os.path.join(case_ctx.run_dir, "vivado_out")
    case_ctx.iverilog_path = parent_ctx.iverilog_path
    case_ctx.modelsim_path = parent_ctx.modelsim_path
    case_ctx.vivado_path = parent_ctx.vivado_path
    case_ctx.iverilog_timeout = parent_ctx.iverilog_timeout
    case_ctx.modelsim_timeout = parent_ctx.modelsim_timeout
    case_ctx.vivado_timeout = parent_ctx.vivado_timeout
    case_ctx.fpga_part = parent_ctx.fpga_part
    os.makedirs(case_ctx.run_dir, exist_ok=True)
    os.makedirs(case_ctx.sim_dir, exist_ok=True)
    os.makedirs(case_ctx.output_dir, exist_ok=True)
    return case_ctx


def run_case_tool(case_ctx, tool):
    started = time.time()
    if tool == "iverilog":
        ok, message = run_iverilog_checks(case_ctx)
    elif tool == "modelsim":
        ok, message = task_run_modelsim(case_ctx)
    elif tool == "vivado":
        ok, message = run_vivado_build(case_ctx)
    else:
        ok, message = False, "unsupported regression tool: " + tool
    return {
        "tool": tool,
        "ok": bool(ok),
        "elapsed_sec": round(time.time() - started, 3),
        "message": trim_message(message),
    }


def normalize_regression_tools(tools):
    raw = tools or DEFAULT_REGRESSION_TOOLS
    if isinstance(raw, str):
        raw = raw.split(",")
    normalized = []
    aliases = {
        "lint": "iverilog",
        "sim": "modelsim",
        "simulation": "modelsim",
        "build": "vivado",
    }
    for item in raw:
        for part in str(item).split(","):
            name = aliases.get(part.strip().lower(), part.strip().lower())
            if name and name not in normalized:
                normalized.append(name)
    return normalized or list(DEFAULT_REGRESSION_TOOLS)


def trim_message(message, limit=3000):
    text = str(message or "")
    if len(text) <= limit:
        return text
    return text[-limit:]


def format_regression_report(report):
    lines = [
        "AutoFPGA Golden Case Regression",
        "Cases: {total}, Passed: {passed}, Failed: {failed}".format(**report),
        "Tools: " + ", ".join(report.get("tools", [])),
        "Report: " + report.get("report_file", ""),
        "",
    ]
    if not report["results"]:
        lines.append("No golden cases found.")
        return "\n".join(lines)
    for result in report["results"]:
        status = "PASS" if result["status"] == "passed" else "FAIL"
        lines.append("- [{}] {} ({})".format(status, result["name"], result.get("top_module") or "no top"))
        for tool_result in result.get("tools", []):
            tool_status = "PASS" if tool_result["ok"] else "FAIL"
            lines.append("  - [{}] {}: {}s".format(tool_status, tool_result["tool"], tool_result["elapsed_sec"]))
        for problem in result.get("audit_problems", []):
            lines.append("  - audit: " + problem)
    return "\n".join(lines)
