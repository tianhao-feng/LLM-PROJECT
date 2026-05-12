import json
import os
import re
import time

from .code_utils import infer_testbench_module_name, validate_testbench_contract
from .case_evidence import validate_case_evidence
from .tools import discover_top_module


REQUIRED_EXAMPLE_FILES = [
    "README.md",
    "requirement.json",
    "expected_manifest.json",
    "tb_top_module.v",
    "constraints.xdc",
]


def audit_examples(examples_dir, write_index=False, index_file=None):
    examples = find_example_dirs(examples_dir)
    results = [audit_example_dir(path, examples_dir=examples_dir) for path in examples]
    total_problems = sum(len(result["problems"]) for result in results)
    report = {
        "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "registry_kind": "golden_cases",
        "examples_dir": os.path.basename(os.path.normpath(examples_dir)) or examples_dir,
        "total": len(results),
        "passed": len([result for result in results if not result["problems"]]),
        "failed": len([result for result in results if result["problems"]]),
        "problems": total_problems,
        "results": results,
    }
    if write_index:
        write_case_index(report, index_file or os.path.join(examples_dir, "index.json"))
    return report


def find_example_dirs(examples_dir):
    if not os.path.isdir(examples_dir):
        return []
    dirs = []
    for name in sorted(os.listdir(examples_dir)):
        path = os.path.join(examples_dir, name)
        if os.path.isdir(path) and os.path.exists(os.path.join(path, "requirement.json")):
            dirs.append(path)
    return dirs


def audit_example_dir(example_dir, examples_dir=None):
    problems = []
    warnings = []
    stable_files = {}
    for rel_path in REQUIRED_EXAMPLE_FILES:
        path = os.path.join(example_dir, rel_path)
        stable_files[rel_path] = os.path.exists(path)
        if not stable_files[rel_path]:
            problems.append("missing required file: " + rel_path)

    src_dir = os.path.join(example_dir, "src")
    src_files = []
    if not os.path.isdir(src_dir):
        problems.append("missing src directory")
    else:
        src_files = sorted(name for name in os.listdir(src_dir) if name.endswith(".v"))
    if os.path.isdir(src_dir) and not src_files:
        problems.append("src directory has no Verilog files")

    expected = load_json_if_exists(os.path.join(example_dir, "expected_manifest.json"))
    expected_design = expected.get("design", {}) if isinstance(expected, dict) else {}
    expected_top = expected_design.get("top_module")
    expected_tb = expected_design.get("testbench_module")
    expected_artifacts = expected.get("required_artifacts", []) if isinstance(expected, dict) else []
    expected_reports = expected.get("reports", {}) if isinstance(expected, dict) else {}

    top_module = None
    if os.path.isdir(src_dir):
        class Ctx:
            pass

        ctx = Ctx()
        ctx.src_dir = src_dir
        top_module = discover_top_module(ctx)
        if not top_module:
            problems.append("cannot discover top module from src")
        elif expected_top and top_module != expected_top:
            problems.append("top module expected {}, got {}".format(expected_top, top_module))

    tb_file = os.path.join(example_dir, "tb_top_module.v")
    if os.path.exists(tb_file):
        with open(tb_file, "r", encoding="utf-8", errors="ignore") as f:
            tb_content = f.read()
        tb_ok, tb_problems = validate_testbench_contract(tb_content, expected_dut_module=top_module)
        problems.extend("testbench: " + problem for problem in tb_problems if not tb_ok)
        tb_module = infer_testbench_module_name(tb_content, expected_dut_module=top_module)
        if expected_tb and tb_module != expected_tb:
            problems.append("testbench module expected {}, got {}".format(expected_tb, tb_module))

    readme_file = os.path.join(example_dir, "README.md")
    if os.path.exists(readme_file):
        with open(readme_file, "r", encoding="utf-8", errors="ignore") as f:
            readme = f.read().strip()
        if len(readme) < 600:
            problems.append("README is too short for a regression fixture")

    requirement_file = os.path.join(example_dir, "requirement.json")
    requirement = load_json_if_exists(requirement_file)
    requirement_text = ""
    if requirement_file and not isinstance(requirement, dict):
        problems.append("requirement.json is not valid JSON object")
    elif isinstance(requirement, dict):
        requirement_text = requirement.get("user_requirement") or ""
        if not requirement_text:
            problems.append("requirement.json missing user_requirement")

    xdc_file = os.path.join(example_dir, "constraints.xdc")
    if os.path.exists(xdc_file):
        with open(xdc_file, "r", encoding="utf-8", errors="ignore") as f:
            xdc = f.read()
        if "PACKAGE_PIN" not in xdc or "IOSTANDARD" not in xdc:
            problems.append("constraints.xdc missing PACKAGE_PIN or IOSTANDARD")
        if re.search(r"\bTODO\b|待实现|根据需要", xdc, flags=re.IGNORECASE):
            problems.append("constraints.xdc contains placeholder text")

    evidence_file = os.path.join(example_dir, "run_evidence.json")
    manifest_file = os.path.join(example_dir, "run_manifest.json")
    evidence = load_json_if_exists(evidence_file)
    manifest = load_json_if_exists(manifest_file)
    has_evidence = isinstance(evidence, dict)
    has_manifest = isinstance(manifest, dict)
    if not has_evidence:
        warnings.append("missing run_evidence.json")
    else:
        evidence_problems, evidence_warnings = validate_case_evidence(evidence, expected_top, expected_tb)
        problems.extend(evidence_problems)
        warnings.extend(evidence_warnings)
    if not has_manifest:
        warnings.append("missing run_manifest.json")

    return {
        "name": os.path.basename(example_dir),
        "path": case_relative_path(example_dir, examples_dir),
        "status": "passed" if not problems else "failed",
        "top_module": top_module,
        "expected_top_module": expected_top,
        "testbench_module": expected_tb,
        "requirement_summary": summarize_text(requirement_text),
        "src_files": src_files,
        "src_file_count": len(src_files),
        "stable_files": stable_files,
        "expected_artifacts": expected_artifacts,
        "expected_reports": expected_reports,
        "has_run_evidence": has_evidence,
        "has_run_manifest": has_manifest,
        "validated_at": evidence.get("validated_at") if has_evidence else None,
        "toolchain": evidence.get("toolchain", {}) if has_evidence else {},
        "flow_passed": evidence.get("flow_passed", {}) if has_evidence else {},
        "warnings": warnings,
        "problems": problems,
    }


def load_json_if_exists(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def format_example_audit_report(report):
    lines = [
        "AutoFPGA Golden Case Audit",
        "Cases: {total}, Passed: {passed}, Failed: {failed}".format(**report),
        "",
    ]
    if not report["results"]:
        lines.append("No golden cases found.")
        return "\n".join(lines)
    for result in report["results"]:
        status = "PASS" if not result["problems"] else "FAIL"
        lines.append("- [{}] {} ({})".format(status, result["name"], result.get("top_module") or "no top"))
        for warning in result.get("warnings", []):
            lines.append("  - warning: " + warning)
        for problem in result["problems"]:
            lines.append("  - " + problem)
    return "\n".join(lines)


def write_case_index(report, index_file):
    os.makedirs(os.path.dirname(index_file), exist_ok=True)
    with open(index_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return index_file


def case_relative_path(example_dir, examples_dir=None):
    if examples_dir:
        try:
            return os.path.relpath(example_dir, examples_dir).replace("\\", "/")
        except Exception:
            pass
    return os.path.basename(example_dir)


def summarize_text(text, max_chars=140):
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."
