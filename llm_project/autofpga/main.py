import argparse
import os
import sys

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

if __package__ in {None, ""}:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autofpga.config import DEFAULT_CONFIG, build_context, load_config_file, read_text_file
from autofpga.llm_client import configure_llm_from_context
from autofpga.manifest import validate_manifest_file
from autofpga.pipeline import main as run_pipeline
from autofpga.rag import dump_rag_index, execute_rag_skill


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="AutoFPGA multi-agent workflow")
    parser.add_argument("--config", help="JSON 配置文件路径")
    parser.add_argument("--work-mode", choices=["AUTO", "BUILD_ONLY"], help="运行模式")
    parser.add_argument("--project-name", help="新工程名称")
    parser.add_argument("--project-dir", help="已有工程路径或 projects 下的工程目录名；BUILD_ONLY 必填")
    parser.add_argument("--no-timestamp", action="store_true", help="新工程目录不追加时间戳")
    parser.add_argument("--script-dir", help="工程根目录，默认取 autofpga 包的上一级")
    parser.add_argument("--vivado-path", help="Vivado batch 可执行文件路径")
    parser.add_argument("--modelsim-path", help="ModelSim vsim 可执行文件路径")
    parser.add_argument("--iverilog-path", help="Icarus Verilog 可执行文件路径")
    parser.add_argument("--iverilog-timeout", type=int, help="Icarus Verilog 单次预审超时秒数")
    parser.add_argument("--modelsim-timeout", type=int, help="ModelSim 仿真超时秒数")
    parser.add_argument("--vivado-timeout", type=int, help="Vivado 构建超时秒数")
    parser.add_argument("--fpga-part", help="Vivado FPGA part，例如 xc7z020clg400-2")
    parser.add_argument("--max-retries", type=int, help="自愈最大迭代次数")
    parser.add_argument("--requirement", help="直接传入用户需求文本")
    parser.add_argument("--requirement-file", help="从 UTF-8 文本文件读取用户需求")
    parser.add_argument("--llm-provider", choices=["deepseek", "openai", "openai_compatible", "cloud", "ollama"], help="LLM 提供方")
    parser.add_argument("--llm-model", help="LLM 模型名")
    parser.add_argument("--llm-base-url", help="云端 OpenAI-compatible base URL 或 Ollama base URL")
    parser.add_argument("--llm-api-key-env", help="云端 API key 环境变量名")
    parser.add_argument("--llm-api-key", help="直接传入云端 API key，不建议写入配置文件")
    parser.add_argument("--llm-temperature", type=float, help="LLM temperature")
    parser.add_argument("--llm-timeout", type=int, help="LLM 请求超时秒数")
    parser.add_argument("--llm-max-retries", type=int, help="LLM 网络重试次数")
    parser.add_argument("--embedding-provider", choices=["ollama", "openai", "openai_compatible", "cloud", "none"], help="Embedding 提供方")
    parser.add_argument("--embedding-model", help="Embedding 模型名")
    parser.add_argument("--embedding-base-url", help="Embedding base URL")
    parser.add_argument("--embedding-api-key-env", help="Embedding API key 环境变量名")
    parser.add_argument("--embedding-api-key", help="直接传入 embedding API key，不建议写入配置文件")
    parser.add_argument("--embedding-timeout", type=int, help="Embedding 请求超时秒数")
    parser.add_argument("--rag-top-k", type=int, help="RAG 最终传入回答模型的片段数量")
    parser.add_argument("--rag-candidate-k", type=int, help="RAG 向量/关键词候选片段数量")
    parser.add_argument("--rag-reindex", action="store_true", help="强制重建当前知识文件的索引")
    parser.add_argument("--rag-clear-index", action="store_true", help="先清空 RAG 向量库再重新索引")
    parser.add_argument("--rag-hide-sources", action="store_true", help="检索回答时不在终端打印来源列表")
    parser.add_argument("--rag-dry-run", action="store_true", help="只打印 RAG 检索片段和来源，不调用 LLM")
    parser.add_argument("--rag-dump-index", action="store_true", help="打印当前 RAG 索引文件、chunk 数和 hash 后退出")
    parser.add_argument(
        "--rag-source",
        action="append",
        choices=["datasheets", "knowledge_base"],
        help="限定 RAG 检索源，可重复传入；默认同时使用 datasheets 和 knowledge_base",
    )
    parser.add_argument("--rag-query", help="直接执行一次 RAG 文档检索问答并退出，绕过 AUTO 路由")
    parser.add_argument("--rag-skill", choices=["CONCEPT", "TABLE"], default="CONCEPT", help="--rag-query 使用的 RAG 问答类型")
    parser.add_argument("--validate-manifest", help="Validate a run_manifest.json and exit")
    parser.add_argument("--expected-manifest", help="Optional expected_manifest.json contract")
    return parser.parse_args(argv)


def merge_config(args):
    config = dict(DEFAULT_CONFIG)
    file_config = load_config_file(args.config)
    unknown = sorted(set(file_config) - set(DEFAULT_CONFIG))
    if unknown:
        raise ValueError("配置文件包含未知字段: " + ", ".join(unknown))
    config.update(file_config)

    cli_values = {
        "work_mode": args.work_mode,
        "project_name": args.project_name,
        "project_dir": args.project_dir,
        "script_dir": args.script_dir,
        "vivado_path": args.vivado_path,
        "modelsim_path": args.modelsim_path,
        "iverilog_path": args.iverilog_path,
        "iverilog_timeout": args.iverilog_timeout,
        "modelsim_timeout": args.modelsim_timeout,
        "vivado_timeout": args.vivado_timeout,
        "fpga_part": args.fpga_part,
        "max_retries": args.max_retries,
        "user_requirement": args.requirement,
        "llm_provider": args.llm_provider,
        "llm_model": args.llm_model,
        "llm_base_url": args.llm_base_url,
        "llm_api_key_env": args.llm_api_key_env,
        "llm_api_key": args.llm_api_key,
        "llm_temperature": args.llm_temperature,
        "llm_timeout": args.llm_timeout,
        "llm_max_retries": args.llm_max_retries,
        "embedding_provider": args.embedding_provider,
        "embedding_model": args.embedding_model,
        "embedding_base_url": args.embedding_base_url,
        "embedding_api_key_env": args.embedding_api_key_env,
        "embedding_api_key": args.embedding_api_key,
        "embedding_timeout": args.embedding_timeout,
        "rag_top_k": args.rag_top_k,
        "rag_candidate_k": args.rag_candidate_k,
    }
    for key, value in cli_values.items():
        if value is not None:
            config[key] = value

    if args.requirement_file:
        config["user_requirement"] = read_text_file(args.requirement_file)
    if args.no_timestamp:
        config["auto_timestamp"] = False
    if args.rag_reindex:
        config["rag_reindex"] = True
    if args.rag_clear_index:
        config["rag_clear_index"] = True
    if args.rag_hide_sources:
        config["rag_show_sources"] = False
    if args.rag_dry_run:
        config["rag_dry_run"] = True
    if args.rag_source:
        config["rag_sources"] = args.rag_source

    config["work_mode"] = str(config["work_mode"]).upper()
    config["auto_timestamp"] = bool(config["auto_timestamp"])
    config["max_retries"] = int(config["max_retries"])
    config["iverilog_timeout"] = int(config["iverilog_timeout"])
    config["modelsim_timeout"] = int(config["modelsim_timeout"])
    config["vivado_timeout"] = int(config["vivado_timeout"])
    config["llm_temperature"] = float(config["llm_temperature"])
    config["llm_timeout"] = int(config["llm_timeout"])
    config["llm_max_retries"] = int(config["llm_max_retries"])
    config["embedding_timeout"] = int(config["embedding_timeout"])
    config["rag_top_k"] = int(config["rag_top_k"])
    config["rag_candidate_k"] = int(config["rag_candidate_k"])
    config["rag_reindex"] = bool(config["rag_reindex"])
    config["rag_clear_index"] = bool(config["rag_clear_index"])
    config["rag_show_sources"] = bool(config["rag_show_sources"])
    config["rag_dry_run"] = bool(config["rag_dry_run"])
    config["rag_sources"] = list(config["rag_sources"])
    if config["llm_provider"] == "ollama":
        if config["llm_base_url"] == DEFAULT_CONFIG["llm_base_url"]:
            config["llm_base_url"] = config["embedding_base_url"] or "http://localhost:11434"
        if config["llm_model"] == DEFAULT_CONFIG["llm_model"]:
            config["llm_model"] = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b")
    return config


def main(argv=None):
    args = parse_args(argv)
    if args.validate_manifest:
        problems = validate_manifest_file(args.validate_manifest, args.expected_manifest)
        if problems:
            print("Manifest validation failed:")
            for problem in problems:
                print(f"- {problem}")
            raise SystemExit(1)
        print("Manifest validation passed.")
        return

    config = merge_config(args)
    ctx = build_context(
        work_mode=config["work_mode"],
        project_name=config["project_name"],
        auto_timestamp=config["auto_timestamp"],
        script_dir=config.get("script_dir"),
        project_dir=config.get("project_dir"),
        vivado_path=config["vivado_path"],
        modelsim_path=config["modelsim_path"],
        iverilog_path=config["iverilog_path"],
        iverilog_timeout=config["iverilog_timeout"],
        modelsim_timeout=config["modelsim_timeout"],
        vivado_timeout=config["vivado_timeout"],
        fpga_part=config["fpga_part"],
        max_retries=config["max_retries"],
        user_requirement=config["user_requirement"],
        llm_provider=config["llm_provider"],
        llm_model=config["llm_model"],
        llm_base_url=config["llm_base_url"],
        llm_api_key_env=config["llm_api_key_env"],
        llm_api_key=config["llm_api_key"],
        llm_temperature=config["llm_temperature"],
        llm_timeout=config["llm_timeout"],
        llm_max_retries=config["llm_max_retries"],
        embedding_provider=config["embedding_provider"],
        embedding_model=config["embedding_model"],
        embedding_base_url=config["embedding_base_url"],
        embedding_api_key_env=config["embedding_api_key_env"],
        embedding_api_key=config["embedding_api_key"],
        embedding_timeout=config["embedding_timeout"],
        rag_top_k=config["rag_top_k"],
        rag_candidate_k=config["rag_candidate_k"],
        rag_reindex=config["rag_reindex"],
        rag_clear_index=config["rag_clear_index"],
        rag_show_sources=config["rag_show_sources"],
        rag_dry_run=config["rag_dry_run"],
        rag_sources=config["rag_sources"],
        config_file=os.path.abspath(args.config) if args.config else None,
    )
    configure_llm_from_context(ctx)
    if args.rag_dump_index:
        dump_rag_index(ctx)
        return
    if args.rag_query:
        execute_rag_skill(ctx, args.rag_query, args.rag_skill)
        return
    run_pipeline(ctx)


if __name__ == "__main__":
    main()
