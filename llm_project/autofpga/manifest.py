import json
import os


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_manifest_file(manifest_path, expected_path=None, check_files=True):
    manifest = load_json(manifest_path)
    expected = load_json(expected_path) if expected_path else {}
    return validate_manifest(manifest, expected, check_files=check_files)


def validate_manifest(manifest, expected=None, check_files=True):
    expected = expected or {}
    problems = []

    for key in ["status", "stage"]:
        if key in expected and manifest.get(key) != expected[key]:
            problems.append(f"{key} expected {expected[key]!r}, got {manifest.get(key)!r}")

    expected_design = expected.get("design", {})
    actual_design = manifest.get("design", {})
    for key, value in expected_design.items():
        if actual_design.get(key) != value:
            problems.append(f"design.{key} expected {value!r}, got {actual_design.get(key)!r}")

    artifact_files = manifest.get("artifacts", {}).get("files", {})
    for artifact_name in expected.get("required_artifacts", []):
        path = artifact_files.get(artifact_name)
        if not path:
            problems.append(f"missing artifact entry: {artifact_name}")
        elif check_files and not os.path.exists(path):
            problems.append(f"artifact file does not exist: {artifact_name} -> {path}")

    expected_reports = expected.get("reports", {})
    actual_reports = manifest.get("reports", {})
    problems.extend(compare_subset(actual_reports, expected_reports, prefix="reports"))

    return problems


def compare_subset(actual, expected, prefix):
    problems = []
    if not isinstance(expected, dict):
        if actual != expected:
            problems.append(f"{prefix} expected {expected!r}, got {actual!r}")
        return problems

    if not isinstance(actual, dict):
        problems.append(f"{prefix} expected object, got {type(actual).__name__}")
        return problems

    for key, expected_value in expected.items():
        child_prefix = f"{prefix}.{key}"
        if key not in actual:
            problems.append(f"missing {child_prefix}")
            continue
        actual_value = actual[key]
        if isinstance(expected_value, dict):
            problems.extend(compare_subset(actual_value, expected_value, child_prefix))
        elif actual_value != expected_value:
            problems.append(f"{child_prefix} expected {expected_value!r}, got {actual_value!r}")
    return problems
