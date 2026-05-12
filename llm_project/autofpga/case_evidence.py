import hashlib
import json
import os
import shutil
import time

from .manifest import validate_manifest_file


def capture_case_evidence(case_dir, manifest_path, expected_manifest_path=None, copy_manifest=False):
    case_dir = os.path.abspath(case_dir)
    manifest_path = os.path.abspath(manifest_path)
    expected_manifest_path = expected_manifest_path or os.path.join(case_dir, "expected_manifest.json")
    expected_manifest_path = os.path.abspath(expected_manifest_path) if expected_manifest_path else ""

    manifest = load_json(manifest_path)
    validation_problems = []
    if expected_manifest_path and os.path.exists(expected_manifest_path):
        validation_problems = validate_manifest_file(manifest_path, expected_manifest_path, check_files=False)

    evidence = build_evidence(case_dir, manifest_path, manifest, expected_manifest_path, validation_problems)
    os.makedirs(case_dir, exist_ok=True)
    evidence_path = os.path.join(case_dir, "run_evidence.json")
    with open(evidence_path, "w", encoding="utf-8") as f:
        json.dump(evidence, f, ensure_ascii=False, indent=2)

    copied_manifest = ""
    if copy_manifest:
        copied_manifest = os.path.join(case_dir, "run_manifest.json")
        shutil.copyfile(manifest_path, copied_manifest)

    return {
        "evidence_path": evidence_path,
        "copied_manifest": copied_manifest,
        "validation_problems": validation_problems,
        "evidence": evidence,
    }


def build_evidence(case_dir, manifest_path, manifest, expected_manifest_path, validation_problems):
    config = manifest.get("config", {}) if isinstance(manifest, dict) else {}
    design = manifest.get("design", {}) if isinstance(manifest, dict) else {}
    reports = manifest.get("reports", {}) if isinstance(manifest, dict) else {}
    artifacts = manifest.get("artifacts", {}) if isinstance(manifest, dict) else {}
    history = manifest.get("history", []) if isinstance(manifest, dict) else []
    artifact_files = artifacts.get("files", {}) if isinstance(artifacts, dict) else {}

    return {
        "schema_version": 1,
        "case_name": os.path.basename(os.path.normpath(case_dir)),
        "validated_at": manifest.get("updated_at") or time.strftime("%Y-%m-%d %H:%M:%S"),
        "source_manifest": relpath_or_name(manifest_path, case_dir),
        "source_manifest_sha256": file_sha256(manifest_path),
        "expected_manifest": relpath_or_name(expected_manifest_path, case_dir) if expected_manifest_path else "",
        "manifest_status": manifest.get("status"),
        "manifest_stage": manifest.get("stage"),
        "design": {
            "top_module": design.get("top_module"),
            "testbench_module": design.get("testbench_module"),
        },
        "toolchain": {
            "python": manifest.get("python"),
            "platform": manifest.get("platform"),
            "iverilog_path": config.get("iverilog_path"),
            "modelsim_path": config.get("modelsim_path"),
            "vivado_path": config.get("vivado_path"),
            "fpga_part": config.get("fpga_part"),
        },
        "flow_passed": {
            "lint": history_has_stage(history, "lint"),
            "simulation": history_has_stage(history, "simulation_passed"),
            "vivado_build": history_has_stage(history, "vivado_build"),
            "complete": manifest.get("status") == "succeeded" and manifest.get("stage") == "complete",
            "bitstream": bool(artifact_files.get("bitstream")),
        },
        "reports": reports,
        "manifest_validation": {
            "expected_checked": bool(expected_manifest_path and os.path.exists(expected_manifest_path)),
            "passed": not validation_problems,
            "problems": validation_problems,
        },
    }


def validate_case_evidence(evidence, expected_top=None, expected_tb=None):
    problems = []
    warnings = []
    if not isinstance(evidence, dict):
        return ["run_evidence.json is not a JSON object"], warnings
    if evidence.get("schema_version") != 1:
        warnings.append("run_evidence.json schema_version is not 1")
    if evidence.get("manifest_status") != "succeeded":
        problems.append("run_evidence manifest_status is not succeeded")
    if evidence.get("manifest_stage") != "complete":
        problems.append("run_evidence manifest_stage is not complete")
    design = evidence.get("design", {}) if isinstance(evidence.get("design"), dict) else {}
    if expected_top and design.get("top_module") != expected_top:
        problems.append("run_evidence top_module expected {}, got {}".format(expected_top, design.get("top_module")))
    if expected_tb and design.get("testbench_module") != expected_tb:
        problems.append(
            "run_evidence testbench_module expected {}, got {}".format(expected_tb, design.get("testbench_module"))
        )
    flow = evidence.get("flow_passed", {}) if isinstance(evidence.get("flow_passed"), dict) else {}
    for key in ["lint", "simulation", "vivado_build", "complete", "bitstream"]:
        if flow.get(key) is not True:
            warnings.append("run_evidence flow_passed.{} is not true".format(key))
    validation = evidence.get("manifest_validation", {})
    if isinstance(validation, dict) and validation.get("problems"):
        problems.append("run_evidence manifest validation has problems")
    return problems, warnings


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def history_has_stage(history, stage):
    return any(isinstance(entry, dict) and entry.get("stage") == stage for entry in history or [])


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relpath_or_name(path, base_dir):
    if not path:
        return ""
    try:
        return os.path.relpath(path, base_dir).replace("\\", "/")
    except Exception:
        return os.path.basename(path)
