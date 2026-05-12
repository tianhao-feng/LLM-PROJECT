import os
import re
import string

from .prompt_templates import PROMPT_DIR, parse_prompt_metadata


REQUIRED_TEMPLATE_VARS = {
    "architect_readme.md": {"requirement", "xilinx_notes"},
    "coder_module.md": {
        "sys_spec",
        "global_arch",
        "verilog_rules",
        "filename",
        "module_name",
        "port_spec",
        "description",
        "retry_hint",
    },
    "repair_module.md": {"sys_spec", "verilog_rules", "error_context", "targeted_code", "error_memory"},
    "testbench_generate.md": {"all_rtl", "user_requirement", "verilog_rules", "dut_module"},
    "testbench_repair.md": {
        "all_rtl",
        "user_requirement",
        "verilog_rules",
        "error_msg",
        "current_tb",
        "dut_module",
    },
}


REQUIRED_KEYWORDS = {
    "architect_readme.md": ["Verilog-2001", "tb_top_module.v", "SIM_RESULT: PASSED", "SIM_RESULT: FAILED"],
    "coder_module.md": ["Verilog-2001", "module {module_name}", "endmodule"],
    "repair_module.md": ["{verilog_rules}", "// File:", "只输出被修改的文件"],
    "testbench_generate.md": ["tb_top_module.v", "SIM_RESULT: PASSED", "SIM_RESULT: FAILED", "$stop"],
    "testbench_repair.md": ["tb_top_module.v", "SIM_RESULT: PASSED", "SIM_RESULT: FAILED", "$stop"],
}


def audit_prompt_templates(prompt_dir=PROMPT_DIR):
    results = []
    for filename in sorted(name for name in os.listdir(prompt_dir) if name.endswith(".md")):
        path = os.path.join(prompt_dir, filename)
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        results.append(audit_prompt_template(filename, text))
    return build_prompt_audit_report(prompt_dir, results)


def audit_prompt_template(filename, text):
    problems = []
    warnings = []
    metadata = parse_prompt_metadata(text)
    variables = extract_template_variables(text)

    if not metadata.get("prompt_name"):
        problems.append("missing Prompt-Name")
    if not metadata.get("prompt_version"):
        problems.append("missing Prompt-Version")
    elif not re.fullmatch(r"\d+", metadata["prompt_version"]):
        problems.append("Prompt-Version must be an integer")

    expected_vars = REQUIRED_TEMPLATE_VARS.get(filename)
    if expected_vars is None:
        warnings.append("template is not listed in REQUIRED_TEMPLATE_VARS")
    else:
        missing_vars = sorted(expected_vars - variables)
        extra_vars = sorted(variables - expected_vars)
        if missing_vars:
            problems.append("missing variables: " + ", ".join(missing_vars))
        if extra_vars:
            warnings.append("unexpected variables: " + ", ".join(extra_vars))

    for keyword in REQUIRED_KEYWORDS.get(filename, []):
        if keyword not in text:
            problems.append("missing required keyword: " + keyword)

    return {
        "filename": filename,
        "prompt_name": metadata.get("prompt_name", ""),
        "prompt_version": metadata.get("prompt_version", ""),
        "variables": sorted(variables),
        "warnings": warnings,
        "problems": problems,
        "status": "passed" if not problems else "failed",
    }


def build_prompt_audit_report(prompt_dir, results):
    return {
        "schema_version": 1,
        "prompt_dir": os.path.basename(os.path.normpath(prompt_dir)) or prompt_dir,
        "total": len(results),
        "passed": len([result for result in results if result["status"] == "passed"]),
        "failed": len([result for result in results if result["status"] == "failed"]),
        "results": results,
    }


def extract_template_variables(text):
    variables = set()
    for _, field_name, _, _ in string.Formatter().parse(text or ""):
        if field_name:
            variables.add(field_name.split(".", 1)[0].split("[", 1)[0])
    return variables


def format_prompt_audit_report(report):
    lines = [
        "AutoFPGA Prompt Audit",
        "Templates: {total}, Passed: {passed}, Failed: {failed}".format(**report),
        "",
    ]
    if not report["results"]:
        lines.append("No prompt templates found.")
        return "\n".join(lines)
    for result in report["results"]:
        status = "PASS" if result["status"] == "passed" else "FAIL"
        label = result["prompt_name"] or result["filename"]
        version = result["prompt_version"] or "?"
        lines.append("- [{}] {} v{} ({})".format(status, label, version, result["filename"]))
        for warning in result.get("warnings", []):
            lines.append("  - warning: " + warning)
        for problem in result.get("problems", []):
            lines.append("  - " + problem)
    return "\n".join(lines)
