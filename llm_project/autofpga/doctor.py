import importlib.util
import os
import platform
import sys

from .tools import missing_executable, run_command
from .xdc import load_board_pin_database


PYTHON_MIN_VERSION = (3, 9)


def collect_doctor_report(ctx, smoke=False):
    items = []
    items.append(check_python_runtime())
    items.extend(check_python_dependencies())
    items.extend(check_external_tools(ctx, smoke=smoke))
    items.extend(check_llm_settings(ctx))
    items.extend(check_runtime_paths(ctx))
    items.append(check_board_pin_database(ctx))

    statuses = [item["status"] for item in items]
    if "fail" in statuses:
        overall = "fail"
    elif "warn" in statuses:
        overall = "warn"
    else:
        overall = "ok"

    return {
        "overall": overall,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "items": items,
    }


def check_python_runtime():
    version = sys.version_info[:3]
    ok = version >= PYTHON_MIN_VERSION
    return {
        "component": "python",
        "name": "runtime",
        "status": "ok" if ok else "fail",
        "message": "Python {}.{}.{}".format(*version),
    }


def check_python_dependencies():
    required = ["requests", "chromadb", "pdfplumber"]
    items = []
    for module_name in required:
        found = importlib.util.find_spec(module_name) is not None
        items.append(
            {
                "component": "python_dependency",
                "name": module_name,
                "status": "ok" if found else "warn",
                "message": "installed" if found else "not installed",
            }
        )
    return items


def check_external_tools(ctx, smoke=False):
    tool_specs = [
        ("iverilog", ctx.iverilog_path, ["-V"], True),
        ("modelsim", ctx.modelsim_path, ["-version"], True),
        ("vivado", ctx.vivado_path, ["-version"], True),
    ]
    items = []
    for name, command, version_args, required_for_full_flow in tool_specs:
        problem = missing_executable(command)
        if problem:
            status = "warn" if required_for_full_flow else "ok"
            message = "{}: {}".format(command, problem)
        else:
            status = "ok"
            message = command
            if smoke:
                status, message = smoke_external_tool(name, command, version_args)
        items.append(
            {
                "component": "external_tool",
                "name": name,
                "status": status,
                "message": message,
            }
        )
    return items


def smoke_external_tool(name, command, version_args):
    result = run_command([command] + version_args, label=name, timeout=20, merge_stderr=True)
    if result.ok:
        first_line = next((line.strip() for line in result.output.splitlines() if line.strip()), "")
        return "ok", first_line or command
    return "warn", result.failure_summary() + "\n" + result.output[-500:]


def check_llm_settings(ctx):
    items = []
    provider = (ctx.llm_provider or "").lower()
    if provider in {"deepseek", "openai", "openai_compatible", "cloud"}:
        has_key = bool(ctx.llm_api_key or (ctx.llm_api_key_env and os.getenv(ctx.llm_api_key_env)))
        items.append(
            {
                "component": "llm",
                "name": provider or "cloud",
                "status": "ok" if has_key else "warn",
                "message": "API key configured" if has_key else "API key not configured",
            }
        )
    elif provider == "ollama":
        items.append(
            {
                "component": "llm",
                "name": "ollama",
                "status": "ok" if ctx.llm_base_url else "warn",
                "message": ctx.llm_base_url or "base URL not configured",
            }
        )
    else:
        items.append(
            {
                "component": "llm",
                "name": provider or "unknown",
                "status": "fail",
                "message": "unsupported provider",
            }
        )

    embedding_provider = (ctx.embedding_provider or "").lower()
    if embedding_provider in {"none", "disabled", ""}:
        items.append(
            {
                "component": "embedding",
                "name": embedding_provider or "none",
                "status": "warn",
                "message": "semantic embeddings disabled; lexical fallback may be used",
            }
        )
    elif embedding_provider == "ollama":
        items.append(
            {
                "component": "embedding",
                "name": "ollama",
                "status": "ok" if ctx.embedding_base_url else "warn",
                "message": ctx.embedding_base_url or "base URL not configured",
            }
        )
    elif embedding_provider in {"openai", "openai_compatible", "cloud"}:
        has_key = bool(
            ctx.embedding_api_key
            or (ctx.embedding_api_key_env and os.getenv(ctx.embedding_api_key_env))
        )
        items.append(
            {
                "component": "embedding",
                "name": embedding_provider,
                "status": "ok" if has_key else "warn",
                "message": "API key configured" if has_key else "API key not configured",
            }
        )
    else:
        items.append(
            {
                "component": "embedding",
                "name": embedding_provider,
                "status": "fail",
                "message": "unsupported provider",
            }
        )
    return items


def check_runtime_paths(ctx):
    path_specs = [
        ("script_dir", ctx.script_dir),
        ("knowledge_base", ctx.kb_dir),
        ("datasheets", ctx.datasheet_dir),
        ("runs_base", ctx.runs_base_dir),
        ("projects_base", ctx.projects_base_dir),
    ]
    items = []
    for name, path in path_specs:
        exists = os.path.isdir(path)
        items.append(
            {
                "component": "path",
                "name": name,
                "status": "ok" if exists else "warn",
                "message": path if exists else "missing: " + path,
            }
        )
    return items


def check_board_pin_database(ctx):
    try:
        db = load_board_pin_database(ctx)
    except Exception as exc:
        return {
            "component": "board",
            "name": "board_pins.json",
            "status": "fail",
            "message": str(exc),
        }

    ports = db.get("ports", {})
    pins = []
    duplicates = []
    for port_name, entry in ports.items():
        pin = entry.get("pin") if isinstance(entry, dict) else None
        if not pin:
            return {
                "component": "board",
                "name": "board_pins.json",
                "status": "fail",
                "message": "missing pin for {}".format(port_name),
            }
        if pin in pins:
            duplicates.append(pin)
        pins.append(pin)

    if duplicates:
        return {
            "component": "board",
            "name": "board_pins.json",
            "status": "ok",
            "message": "{} ports mapped; shared pin aliases: {}".format(
                len(ports),
                ", ".join(sorted(set(duplicates))),
            ),
        }
    return {
        "component": "board",
        "name": "board_pins.json",
        "status": "ok",
        "message": "{} ports mapped".format(len(ports)),
    }


def format_doctor_report(report):
    lines = [
        "AutoFPGA Doctor",
        "Overall: {}".format(report["overall"].upper()),
        "Python: {}".format(report["python"]),
        "Platform: {}".format(report["platform"]),
        "",
        "Checks:",
    ]
    for item in report["items"]:
        lines.append(
            "- [{status}] {component}/{name}: {message}".format(
                status=item["status"].upper(),
                component=item["component"],
                name=item["name"],
                message=item["message"],
            )
        )
    return "\n".join(lines)
