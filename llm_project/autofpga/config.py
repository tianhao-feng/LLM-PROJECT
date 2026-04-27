import json
import os
import platform
import glob
import re
import sys
import time
from dataclasses import asdict, dataclass
from typing import Optional


@dataclass
class RuntimeContext:
    work_mode: str
    project_name: str
    auto_timestamp: bool
    script_dir: str
    vivado_path: str
    modelsim_path: str
    iverilog_path: str
    iverilog_timeout: int
    modelsim_timeout: int
    vivado_timeout: int
    fpga_part: str
    max_retries: int
    user_requirement: str
    llm_provider: str
    llm_model: str
    llm_base_url: str
    llm_api_key_env: str
    llm_api_key: str
    llm_temperature: float
    llm_timeout: int
    llm_max_retries: int
    embedding_provider: str
    embedding_model: str
    embedding_base_url: str
    embedding_api_key_env: str
    embedding_api_key: str
    embedding_timeout: int
    rag_top_k: int
    rag_candidate_k: int
    rag_reindex: bool
    rag_clear_index: bool
    rag_show_sources: bool
    rag_dry_run: bool
    rag_sources: list
    kb_dir: str
    datasheet_dir: str
    vector_db_dir: str
    error_kb_file: str
    runs_base_dir: str
    projects_base_dir: str
    save_dir: str
    run_dir: str
    src_dir: str
    tb_file: str
    xdc_file: str
    readme_file: str
    output_dir: str
    sim_dir: str
    manifest_file: str
    config_file: Optional[str] = None


DEFAULT_REQUIREMENT = """
创建一个 Verilog-2001 FPGA 工程，实现一个 4 位同步计数器。
要求包含 clk、rst_n、en 和 count[3:0] 端口；rst_n 为低有效异步复位；en 为高时在 clk 上升沿递增计数，en 为低时保持；计数从 0 到 15 后回绕到 0。
"""


DEFAULT_CONFIG = {
    "work_mode": "AUTO",
    "project_name": "ai_fpga_project",
    "auto_timestamp": True,
    "script_dir": None,
    "project_dir": None,
    "vivado_path": r"D:\Vivado\2017.4\bin\vivado.bat",
    "modelsim_path": r"D:\win64\vsim.exe",
    "iverilog_path": "iverilog",
    "iverilog_timeout": 60,
    "modelsim_timeout": 60,
    "vivado_timeout": 7200,
    "fpga_part": "xc7z020clg400-2",
    "max_retries": 5,
    "user_requirement": DEFAULT_REQUIREMENT,
    "llm_provider": "deepseek",
    "llm_model": "deepseek-chat",
    "llm_base_url": "https://api.deepseek.com",
    "llm_api_key_env": "DEEPSEEK_API_KEY",
    "llm_api_key": "",
    "llm_temperature": 0.1,
    "llm_timeout": 300,
    "llm_max_retries": 2,
    "embedding_provider": "ollama",
    "embedding_model": "nomic-embed-text",
    "embedding_base_url": "http://localhost:11434",
    "embedding_api_key_env": "",
    "embedding_api_key": "",
    "embedding_timeout": 30,
    "rag_top_k": 5,
    "rag_candidate_k": 20,
    "rag_reindex": False,
    "rag_clear_index": False,
    "rag_show_sources": True,
    "rag_dry_run": False,
    "rag_sources": ["datasheets", "knowledge_base"],
}


def build_context(
    work_mode=None,
    project_name=None,
    auto_timestamp=None,
    script_dir=None,
    project_dir=None,
    vivado_path=None,
    modelsim_path=None,
    iverilog_path=None,
    iverilog_timeout=None,
    modelsim_timeout=None,
    vivado_timeout=None,
    fpga_part=None,
    max_retries=None,
    user_requirement=None,
    llm_provider=None,
    llm_model=None,
    llm_base_url=None,
    llm_api_key_env=None,
    llm_api_key=None,
    llm_temperature=None,
    llm_timeout=None,
    llm_max_retries=None,
    embedding_provider=None,
    embedding_model=None,
    embedding_base_url=None,
    embedding_api_key_env=None,
    embedding_api_key=None,
    embedding_timeout=None,
    rag_top_k=None,
    rag_candidate_k=None,
    rag_reindex=None,
    rag_clear_index=None,
    rag_show_sources=None,
    rag_dry_run=None,
    rag_sources=None,
    config_file=None,
):
    work_mode = DEFAULT_CONFIG["work_mode"] if work_mode is None else work_mode
    project_name = DEFAULT_CONFIG["project_name"] if project_name is None else project_name
    auto_timestamp = DEFAULT_CONFIG["auto_timestamp"] if auto_timestamp is None else auto_timestamp
    vivado_path = DEFAULT_CONFIG["vivado_path"] if vivado_path is None else vivado_path
    modelsim_path = DEFAULT_CONFIG["modelsim_path"] if modelsim_path is None else modelsim_path
    iverilog_path = DEFAULT_CONFIG["iverilog_path"] if iverilog_path is None else iverilog_path
    iverilog_timeout = DEFAULT_CONFIG["iverilog_timeout"] if iverilog_timeout is None else iverilog_timeout
    modelsim_timeout = DEFAULT_CONFIG["modelsim_timeout"] if modelsim_timeout is None else modelsim_timeout
    vivado_timeout = DEFAULT_CONFIG["vivado_timeout"] if vivado_timeout is None else vivado_timeout
    fpga_part = DEFAULT_CONFIG["fpga_part"] if fpga_part is None else fpga_part
    max_retries = DEFAULT_CONFIG["max_retries"] if max_retries is None else max_retries
    user_requirement = DEFAULT_CONFIG["user_requirement"] if user_requirement is None else user_requirement
    llm_provider = DEFAULT_CONFIG["llm_provider"] if llm_provider is None else llm_provider
    llm_model = DEFAULT_CONFIG["llm_model"] if llm_model is None else llm_model
    llm_base_url = DEFAULT_CONFIG["llm_base_url"] if llm_base_url is None else llm_base_url
    llm_api_key_env = DEFAULT_CONFIG["llm_api_key_env"] if llm_api_key_env is None else llm_api_key_env
    llm_api_key = DEFAULT_CONFIG["llm_api_key"] if llm_api_key is None else llm_api_key
    llm_temperature = DEFAULT_CONFIG["llm_temperature"] if llm_temperature is None else llm_temperature
    llm_timeout = DEFAULT_CONFIG["llm_timeout"] if llm_timeout is None else llm_timeout
    llm_max_retries = DEFAULT_CONFIG["llm_max_retries"] if llm_max_retries is None else llm_max_retries
    embedding_provider = DEFAULT_CONFIG["embedding_provider"] if embedding_provider is None else embedding_provider
    embedding_model = DEFAULT_CONFIG["embedding_model"] if embedding_model is None else embedding_model
    embedding_base_url = DEFAULT_CONFIG["embedding_base_url"] if embedding_base_url is None else embedding_base_url
    embedding_api_key_env = DEFAULT_CONFIG["embedding_api_key_env"] if embedding_api_key_env is None else embedding_api_key_env
    embedding_api_key = DEFAULT_CONFIG["embedding_api_key"] if embedding_api_key is None else embedding_api_key
    embedding_timeout = DEFAULT_CONFIG["embedding_timeout"] if embedding_timeout is None else embedding_timeout
    rag_top_k = DEFAULT_CONFIG["rag_top_k"] if rag_top_k is None else rag_top_k
    rag_candidate_k = DEFAULT_CONFIG["rag_candidate_k"] if rag_candidate_k is None else rag_candidate_k
    rag_reindex = DEFAULT_CONFIG["rag_reindex"] if rag_reindex is None else rag_reindex
    rag_clear_index = DEFAULT_CONFIG["rag_clear_index"] if rag_clear_index is None else rag_clear_index
    rag_show_sources = DEFAULT_CONFIG["rag_show_sources"] if rag_show_sources is None else rag_show_sources
    rag_dry_run = DEFAULT_CONFIG["rag_dry_run"] if rag_dry_run is None else rag_dry_run
    rag_sources = DEFAULT_CONFIG["rag_sources"] if rag_sources is None else rag_sources

    script_dir = script_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script_dir = os.path.abspath(script_dir)
    kb_dir = os.path.join(script_dir, "knowledge_base")
    datasheet_dir = os.path.join(script_dir, "datasheets")
    runs_base_dir = os.path.join(script_dir, "runs")
    vector_db_dir = os.path.join(runs_base_dir, "vector_db")
    error_kb_file = os.path.join(runs_base_dir, "error_memory.txt")
    projects_base_dir = os.path.join(script_dir, "projects")
    os.makedirs(projects_base_dir, exist_ok=True)

    work_mode = work_mode.upper()
    if work_mode == "BUILD_ONLY":
        if not project_dir:
            raise ValueError("BUILD_ONLY 模式必须显式传入 project_dir，禁止自动猜测最近工程。")
        save_dir = resolve_project_dir(project_dir, projects_base_dir)
        src_candidate = os.path.join(save_dir, "src")
        if not os.path.isdir(src_candidate):
            raise ValueError(f"BUILD_ONLY 工程缺少 src 目录: {src_candidate}")
    else:
        final_project_name = f"{project_name}_{time.strftime('%Y%m%d_%H%M%S')}" if auto_timestamp else project_name
        save_dir = os.path.join(projects_base_dir, final_project_name)

    run_dir = os.path.join(save_dir, "runs")
    src_dir = os.path.join(save_dir, "src")
    tb_file = os.path.join(save_dir, "tb_top_module.v")
    xdc_file = os.path.join(save_dir, "constraints.xdc")
    readme_file = os.path.join(save_dir, "README.md")
    output_dir = os.path.join(run_dir, "vivado_out")
    sim_dir = os.path.join(run_dir, "sim_work")
    manifest_file = os.path.join(save_dir, "run_manifest.json")

    for path in [kb_dir, datasheet_dir, vector_db_dir]:
        os.makedirs(path, exist_ok=True)

    return RuntimeContext(
        work_mode=work_mode,
        project_name=project_name,
        auto_timestamp=auto_timestamp,
        script_dir=script_dir,
        vivado_path=vivado_path,
        modelsim_path=modelsim_path,
        iverilog_path=iverilog_path,
        iverilog_timeout=iverilog_timeout,
        modelsim_timeout=modelsim_timeout,
        vivado_timeout=vivado_timeout,
        fpga_part=fpga_part,
        max_retries=max_retries,
        user_requirement=user_requirement,
        llm_provider=llm_provider,
        llm_model=llm_model,
        llm_base_url=llm_base_url,
        llm_api_key_env=llm_api_key_env,
        llm_api_key=llm_api_key,
        llm_temperature=llm_temperature,
        llm_timeout=llm_timeout,
        llm_max_retries=llm_max_retries,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
        embedding_base_url=embedding_base_url,
        embedding_api_key_env=embedding_api_key_env,
        embedding_api_key=embedding_api_key,
        embedding_timeout=embedding_timeout,
        rag_top_k=int(rag_top_k),
        rag_candidate_k=int(rag_candidate_k),
        rag_reindex=bool(rag_reindex),
        rag_clear_index=bool(rag_clear_index),
        rag_show_sources=bool(rag_show_sources),
        rag_dry_run=bool(rag_dry_run),
        rag_sources=list(rag_sources),
        kb_dir=kb_dir,
        datasheet_dir=datasheet_dir,
        vector_db_dir=vector_db_dir,
        error_kb_file=error_kb_file,
        runs_base_dir=runs_base_dir,
        projects_base_dir=projects_base_dir,
        save_dir=save_dir,
        run_dir=run_dir,
        src_dir=src_dir,
        tb_file=tb_file,
        xdc_file=xdc_file,
        readme_file=readme_file,
        output_dir=output_dir,
        sim_dir=sim_dir,
        manifest_file=manifest_file,
        config_file=os.path.abspath(config_file) if config_file else None,
    )


def resolve_project_dir(project_dir, projects_base_dir):
    project_dir = os.path.expanduser(project_dir)
    if os.path.isabs(project_dir):
        return os.path.abspath(project_dir)
    direct = os.path.abspath(project_dir)
    if os.path.isdir(direct):
        return direct
    return os.path.abspath(os.path.join(projects_base_dir, project_dir))


def load_config_file(path):
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_text_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write_run_manifest(ctx, status, stage=None, error=None, extra=None):
    os.makedirs(ctx.save_dir, exist_ok=True)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    existing = {}
    if os.path.exists(ctx.manifest_file):
        try:
            with open(ctx.manifest_file, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = {}

    history = existing.get("history", [])
    entry = {"time": now, "status": status, "stage": stage, "error": str(error) if error else None}
    if extra:
        entry["extra"] = extra
    history.append(entry)

    manifest = {
        "schema_version": 1,
        "status": status,
        "stage": stage,
        "created_at": existing.get("created_at", now),
        "updated_at": now,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "config": runtime_config_dict(ctx),
        "paths": runtime_paths_dict(ctx),
        "design": collect_design_summary(ctx),
        "artifacts": collect_artifacts(ctx),
        "reports": collect_report_summary(ctx),
        "history": history[-100:],
    }
    if error:
        manifest["error"] = str(error)
    if extra:
        manifest["extra"] = extra

    with open(ctx.manifest_file, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def runtime_config_dict(ctx):
    return {
        "work_mode": ctx.work_mode,
        "project_name": ctx.project_name,
        "auto_timestamp": ctx.auto_timestamp,
        "vivado_path": ctx.vivado_path,
        "modelsim_path": ctx.modelsim_path,
        "iverilog_path": ctx.iverilog_path,
        "iverilog_timeout": ctx.iverilog_timeout,
        "modelsim_timeout": ctx.modelsim_timeout,
        "vivado_timeout": ctx.vivado_timeout,
        "fpga_part": ctx.fpga_part,
        "max_retries": ctx.max_retries,
        "user_requirement": ctx.user_requirement,
        "llm_provider": ctx.llm_provider,
        "llm_model": ctx.llm_model,
        "llm_base_url": ctx.llm_base_url,
        "llm_api_key_env": ctx.llm_api_key_env,
        "llm_temperature": ctx.llm_temperature,
        "llm_timeout": ctx.llm_timeout,
        "llm_max_retries": ctx.llm_max_retries,
        "embedding_provider": ctx.embedding_provider,
        "embedding_model": ctx.embedding_model,
        "embedding_base_url": ctx.embedding_base_url,
        "embedding_api_key_env": ctx.embedding_api_key_env,
        "embedding_timeout": ctx.embedding_timeout,
        "rag_top_k": ctx.rag_top_k,
        "rag_candidate_k": ctx.rag_candidate_k,
        "rag_reindex": ctx.rag_reindex,
        "rag_clear_index": ctx.rag_clear_index,
        "rag_show_sources": ctx.rag_show_sources,
        "rag_dry_run": ctx.rag_dry_run,
        "rag_sources": ctx.rag_sources,
        "config_file": ctx.config_file,
    }


def runtime_paths_dict(ctx):
    data = asdict(ctx)
    return {
        key: value
        for key, value in data.items()
        if key.endswith("_dir") or key.endswith("_file") or key in {"script_dir", "save_dir", "projects_base_dir"}
    }


def collect_artifacts(ctx):
    bitstreams = sorted(glob.glob(os.path.join(ctx.output_dir, "**", "*.bit"), recursive=True))
    candidates = {
        "readme": ctx.readme_file,
        "testbench": ctx.tb_file,
        "constraints": ctx.xdc_file,
        "bitstream": bitstreams[-1] if bitstreams else "",
        "vivado_script": os.path.join(ctx.run_dir, "scripts", "run.tcl"),
        "vivado_log": os.path.join(ctx.run_dir, "vivado_logs", "vivado.log"),
        "vivado_journal": os.path.join(ctx.run_dir, "vivado_logs", "vivado.jou"),
        "vivado_project": os.path.join(ctx.output_dir, "ai_project.xpr"),
        "utilization_report": os.path.join(ctx.output_dir, "report_utilization.rpt"),
        "timing_report": os.path.join(ctx.output_dir, "report_timing.rpt"),
        "power_report": os.path.join(ctx.output_dir, "report_power.rpt"),
        "manifest": ctx.manifest_file,
    }
    src_files = []
    if os.path.isdir(ctx.src_dir):
        src_files = [
            os.path.join(ctx.src_dir, fname)
            for fname in sorted(os.listdir(ctx.src_dir))
            if fname.endswith(".v")
        ]
    return {
        "files": {name: path for name, path in candidates.items() if name == "manifest" or os.path.exists(path)},
        "src_files": src_files,
    }


def collect_design_summary(ctx):
    summary = {"top_module": None, "testbench_module": None}
    try:
        from .tools import discover_top_module

        summary["top_module"] = discover_top_module(ctx)
    except Exception:
        pass
    try:
        if os.path.exists(ctx.tb_file):
            from .code_utils import infer_testbench_module_name

            with open(ctx.tb_file, "r", encoding="utf-8", errors="ignore") as f:
                summary["testbench_module"] = infer_testbench_module_name(
                    f.read(), expected_dut_module=summary["top_module"]
                )
    except Exception:
        pass
    return summary


def collect_report_summary(ctx):
    return {
        "timing": parse_timing_summary(os.path.join(ctx.output_dir, "report_timing.rpt")),
        "utilization": parse_utilization_summary(os.path.join(ctx.output_dir, "report_utilization.rpt")),
        "power": parse_power_summary(os.path.join(ctx.output_dir, "report_power.rpt")),
    }


def parse_timing_summary(path):
    data = {
        "constraints_met": None,
        "setup_failing_endpoints": None,
        "setup_worst_slack_ns": None,
        "hold_failing_endpoints": None,
        "hold_worst_slack_ns": None,
        "pulse_width_failing_endpoints": None,
        "pulse_width_worst_slack_ns": None,
    }
    if not os.path.exists(path):
        return data
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        data["constraints_met"] = "All user specified timing constraints are met" in text
        setup = re.search(r"Setup\s*:\s*(\d+)\s+Failing Endpoints,\s+Worst Slack\s+(-?\d+(?:\.\d+)?)ns", text)
        hold = re.search(r"Hold\s*:\s*(\d+)\s+Failing Endpoints,\s+Worst Slack\s+(-?\d+(?:\.\d+)?)ns", text)
        pulse = re.search(r"PW\s*:\s*(\d+)\s+Failing Endpoints,\s+Worst Slack\s+(-?\d+(?:\.\d+)?)ns", text)
        if setup:
            data["setup_failing_endpoints"] = int(setup.group(1))
            data["setup_worst_slack_ns"] = float(setup.group(2))
        if hold:
            data["hold_failing_endpoints"] = int(hold.group(1))
            data["hold_worst_slack_ns"] = float(hold.group(2))
        if pulse:
            data["pulse_width_failing_endpoints"] = int(pulse.group(1))
            data["pulse_width_worst_slack_ns"] = float(pulse.group(2))
    except Exception:
        pass
    return data


def parse_utilization_summary(path):
    data = {
        "slice_luts_used": None,
        "slice_luts_available": None,
        "slice_luts_percent": None,
        "slice_registers_used": None,
        "slice_registers_available": None,
        "slice_registers_percent": None,
        "bonded_iob_used": None,
        "bonded_iob_available": None,
        "bonded_iob_percent": None,
        "bufgctrl_used": None,
        "bufgctrl_available": None,
        "bufgctrl_percent": None,
    }
    if not os.path.exists(path):
        return data
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                cols = [c.strip() for c in line.split("|")]
                if len(cols) < 6:
                    continue
                name = cols[1]
                used = parse_int(cols[2])
                available = parse_int(cols[4])
                percent = parse_float(cols[5])
                if name == "Slice LUTs":
                    data.update({"slice_luts_used": used, "slice_luts_available": available, "slice_luts_percent": percent})
                elif name == "Slice Registers":
                    data.update({"slice_registers_used": used, "slice_registers_available": available, "slice_registers_percent": percent})
                elif name == "Bonded IOB":
                    data.update({"bonded_iob_used": used, "bonded_iob_available": available, "bonded_iob_percent": percent})
                elif name == "BUFGCTRL":
                    data.update({"bufgctrl_used": used, "bufgctrl_available": available, "bufgctrl_percent": percent})
    except Exception:
        pass
    return data


def parse_power_summary(path):
    data = {"total_on_chip_power_w": None}
    if not os.path.exists(path):
        return data
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        match = re.search(r"Total On-Chip Power \(W\)\s*\|\s*([0-9.]+)", text)
        if match:
            data["total_on_chip_power_w"] = float(match.group(1))
    except Exception:
        pass
    return data


def parse_int(value):
    value = (value or "").replace(",", "").strip()
    return int(value) if re.fullmatch(r"\d+", value) else None


def parse_float(value):
    value = (value or "").replace("<", "").strip()
    try:
        return float(value)
    except Exception:
        return None
