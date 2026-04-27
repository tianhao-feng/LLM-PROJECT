# AutoFPGA

AutoFPGA is a Python workflow for generating, checking, simulating, and building Verilog-2001 FPGA projects with an LLM-assisted pipeline.

The repository is intentionally split into stable source/configuration files and generated runtime output:

- `autofpga/`: Python package and CLI entry point.
- `knowledge_base/`: stable board and coding knowledge.
- `knowledge_base/xilinx_skill/`: curated Vivado/XDC/Tcl notes derived from `QingquanYao/xilinx-skill`.
- `datasheets/`: source documents used by RAG.
- `examples/`: small known-good reference projects and expected output contracts.
- `runs/`: generated runtime state such as vector DBs and error memory. This directory is ignored by git.
- `projects/`: generated FPGA projects. This directory is created at runtime and ignored by git.

## Install

```powershell
pip install -r requirements.txt
```

External FPGA tools are configured separately and are not installed by pip:

- Vivado
- ModelSim
- Icarus Verilog
- Ollama, when local embeddings are used

## CLI

Show available options:

```powershell
python -m autofpga --help
```

Run with the example configuration:

```powershell
python -m autofpga --config autofpga.example.json
```

Run with a requirement file:

```powershell
python -m autofpga --work-mode AUTO --project-name counter_4bit --requirement-file spec.txt
```

Use cloud LLM inference with DeepSeek:

```powershell
set DEEPSEEK_API_KEY=your_key
python -m autofpga --config autofpga.example.json
```

Use a local Ollama chat model instead:

```powershell
python -m autofpga --llm-provider ollama --llm-model qwen2.5-coder:7b --llm-base-url http://localhost:11434
```

Embeddings default to Ollama:

```powershell
ollama pull nomic-embed-text
```

Build an existing generated project:

```powershell
python -m autofpga --work-mode BUILD_ONLY --project-dir <project_name_or_path>
```

`BUILD_ONLY` never guesses the latest project. You must pass `--project-dir` explicitly.

## Board Pins

XDC generation is deterministic. AutoFPGA reads `knowledge_base/board_pins.json`, parses the top-level RTL ports, and refuses to generate constraints if any top-level port lacks a pin mapping.

Do not rely on the LLM to invent pins. Add real board mappings to `board_pins.json` before building.

## Xilinx Skill Notes

AutoFPGA keeps a curated local subset of the public `QingquanYao/xilinx-skill` guidance under `knowledge_base/xilinx_skill/`. These notes strengthen Vivado Tcl, XDC, and diagnostics knowledge while preserving AutoFPGA's own execution model.

RAG indexing now scans both `datasheets/` and `knowledge_base/` recursively, so `.md`, `.txt`, and `.pdf` knowledge files under `knowledge_base/xilinx_skill/` can be retrieved by concept/table queries.

The RAG index stores file hashes and chunk metadata. Modified files are re-indexed automatically, deleted files are removed from the vector DB, and answers print ranked sources by default. Retrieval combines vector similarity with keyword matches so exact FPGA terms such as `create_clock`, `PACKAGE_PIN`, `UCIO-1`, and `CFGBVS` can still rank well.

Useful RAG debugging options:

```powershell
python -m autofpga --rag-reindex --rag-top-k 8 --requirement "create_clock 怎么写？"
python -m autofpga --rag-clear-index --rag-source knowledge_base --requirement "Vivado build flow 是什么？"
python -m autofpga --rag-hide-sources --requirement "解释 XDC PACKAGE_PIN"
python -m autofpga --rag-query "create_clock 怎么写？" --rag-dry-run
python -m autofpga --rag-dump-index
```

For retrieval debugging, bypass AUTO routing and run RAG directly:

```powershell
python -m autofpga --rag-query "create_clock 怎么写？" --rag-skill CONCEPT
python -m autofpga --rag-query "列出配置电压相关表格" --rag-skill TABLE --rag-source datasheets
```

When `--rag-dry-run` is used, AutoFPGA prints retrieved chunks and sources without calling the LLM. `--rag-dump-index` prints indexed files, chunk counts, hashes, and metadata. Normal RAG answers are checked for source-number citations and whether technical terms in the answer appear in retrieved chunks; if either check fails, AutoFPGA prints a warning and repeats the retrieved sources for review.

## Runtime Output

Generated data is kept out of the source tree:

- `runs/vector_db/`
- `runs/error_memory.txt`
- `projects/<project>/`
- `projects/<project>/runs/vivado_out/`
- `projects/<project>/runs/scripts/run.tcl`
- `projects/<project>/runs/vivado_logs/vivado.log`
- `projects/<project>/runs/vivado_logs/vivado.jou`
- `projects/<project>/runs/vivado_logs/.Xil/`
- `projects/<project>/runs/sim_work/`
- `projects/<project>/run_manifest.json`

`run_manifest.json` records the current stage, paths, artifacts, and failure history for each run.

Only stable source files, curated knowledge, and known-good examples belong in git. Runtime directories such as `projects/`, `runs/`, and `tests/_tmp/` are disposable and ignored. If a generated project should become a regression fixture, copy the minimal stable files into `examples/<name>/` and add an `expected_manifest.json` contract.

Validate a completed run against an expected manifest contract:

```powershell
python -B -m autofpga --validate-manifest projects/<project>/run_manifest.json --expected-manifest examples/counter_4bit/expected_manifest.json
```

## Verification Flow

Generated RTL is checked in three stages:

1. Icarus Verilog performs the fast RTL/testbench syntax and contract precheck.
2. ModelSim runs the self-checking testbench for functional verification.
3. Vivado performs synthesis, implementation, report generation, and bitstream creation.

The testbench must be self-checking. AutoFPGA saves the testbench file as `tb_top_module.v`, parses the actual testbench module name from the file, and rejects generated testbenches that do not include DUT instantiation, `SIM_RESULT: PASSED`, `SIM_RESULT: FAILED`, `$stop`, and explicit conditional comparisons.

External tools are executed through a common command layer. Missing tools, timeouts, non-zero return codes, stdout, stderr, and execution exceptions are normalized before the pipeline decides whether to repair RTL/TB, rerun simulation, or stop.

`tests/test_pipeline_e2e.py` runs the pipeline orchestration with mocked agents and mocked tools. This test does not call a real LLM, Icarus Verilog, ModelSim, or Vivado; it exists to keep the manifest and stage sequencing reproducible.

Tool timeouts can be configured from CLI or JSON:

```powershell
python -m autofpga --iverilog-timeout 60 --modelsim-timeout 120 --vivado-timeout 7200
```

## Examples

The `examples/counter_4bit/` directory contains a known-good generated counter project plus an expected manifest contract. It is useful as a quick sanity check after changing the pipeline:

```powershell
python -B -m autofpga --config examples/counter_4bit/requirement.json
```

The `examples/counter_load_updown/` directory increases complexity with load, count direction, load value, overflow, and underflow behavior:

```powershell
python -B -m autofpga --config examples/counter_load_updown/requirement.json
```

After the run completes, validate the generated manifest:

```powershell
python -B -m autofpga --validate-manifest projects/<project>/run_manifest.json --expected-manifest examples/counter_load_updown/expected_manifest.json
```

## Tests

Run the unit tests:

```powershell
python -m unittest discover -s tests
```

Run the focused RAG retrieval checks after changing chunking, ranking, or source metadata:

```powershell
python -m unittest tests.test_rag tests.test_rag_quality
```

Run the real local-document retrieval checks:

```powershell
python -m unittest tests.test_rag_real_docs
```

Run the optional Chroma smoke test only when you want to exercise the real vector DB path:

```powershell
set AUTOFPGARAG_CHROMA_SMOKE=1
python -m unittest tests.test_rag_chroma_smoke
```

Before using a board for bitstream generation, verify every `knowledge_base/board_pins.json` mapping against the board schematic or vendor constraints. The default mapping is a development reference, not proof that the connected board uses those exact pins.
