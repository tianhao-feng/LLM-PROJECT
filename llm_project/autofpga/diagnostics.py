import os
import re
import time


def update_error_memory(ctx, new_entry):
    header = "[AI FPGA error memory]\n"
    records = []
    try:
        os.makedirs(os.path.dirname(ctx.error_kb_file), exist_ok=True)
        if os.path.exists(ctx.error_kb_file):
            with open(ctx.error_kb_file, "r", encoding="utf-8") as f:
                content = f.read()
            records = [r.strip() for r in content.split("###_ERR_RECORD_###") if r.strip()]
            if records and records[0].startswith(header.strip()):
                records[0] = records[0][len(header.strip()):].strip()
        records.append(new_entry.strip())
        with open(ctx.error_kb_file, "w", encoding="utf-8") as f:
            f.write(header + "\n" + "\n\n".join(["###_ERR_RECORD_###\n" + r for r in records[-5:]]))
    except OSError as exc:
        print(f"[ErrorMemory] skip write: {exc}")


def extract_and_classify_errors(ctx, error_text, stage):
    if not error_text or error_text.isspace():
        return [], "", ""

    error_patterns = {
        "SystemVerilog syntax violation": [
            r"Variable declaration in unnamed block requires SystemVerilog",
            r"requires SystemVerilog",
            r"SystemVerilog keyword",
            r"syntax error.*logic",
        ],
        "width mismatch": [r"width mismatch", r"expects \d+ bits, got", r"size mismatch"],
        "undeclared or unconnected port": [r"unconnected", r"floating", r"not declared", r"undeclared identifier"],
        "illegal assignment or multiple drivers": [r"cannot be driven by", r"multi-driven", r"multiple drivers", r"illegal reference"],
        "missing module": [r"Could not find a top module", r"instantiation of undefined module"],
        "constraint port mismatch": [r"No ports matched", r"No valid object\(s\) found for '-objects \[get_ports"],
        "syntax error": [r"syntax error", r"parse error", r"expecting"],
        "unconstrained IO": [r"DRC UCIO-1", r"Unconstrained Logical Port"],
        "missing IO standard": [r"DRC NSTD-1", r"Unspecified I/O Standard"],
        "invalid package pin": [
            r"not a valid site or package pin name",
            r"Package pin .* is not valid",
            r"Cannot set LOC property",
        ],
        "IO bank or standard conflict": [
            r"Bank.*VCCIO",
            r"Conflicting.*IOSTANDARD",
            r"Place.*IO.*bank",
        ],
        "timing violation": [
            r"Timing constraints are not met",
            r"WNS\(ns\).*-\d",
            r"VIOLATED",
            r"Slack.*-\d",
        ],
        "bitstream generation failed": [r"write_bitstream.*failed", r"Bitgen not run"],
    }
    advice_map = {
        "SystemVerilog syntax violation": "Project is Verilog-2001 only. Move declarations to module scope and avoid logic/always_ff.",
        "width mismatch": "Check instance port widths and vector declarations.",
        "missing module": "Check module names, filenames, and instantiated submodules.",
        "undeclared or unconnected port": "Check port spelling and wire/reg declarations.",
        "illegal assignment or multiple drivers": "Avoid assigning a reg from both assign and always blocks.",
        "syntax error": "Check semicolons, begin/end pairs, and module/endmodule pairs.",
        "constraint port mismatch": "Check that XDC get_ports names match top-level Verilog ports.",
        "unconstrained IO": "Add the missing top-level port to board_pins.json or remove it from the physical top level.",
        "missing IO standard": "Ensure every physical IO gets an IOSTANDARD from board_pins.json or the default board setting.",
        "invalid package pin": "The pin is not valid for the selected part/package. Verify it with the board schematic or Vivado.",
        "IO bank or standard conflict": "Check whether all pins in the same IO bank use a compatible VCCIO/IOSTANDARD.",
        "timing violation": "Inspect report_timing_summary. Consider pipelining, reducing logic depth, phys_opt_design, or a slower clock.",
        "bitstream generation failed": "Fix earlier DRC, timing, or IO errors before write_bitstream can complete.",
        "unknown fatal error": "Inspect the tool log tail and fix the nearest ERROR/CRITICAL WARNING.",
    }

    found_cats = set()
    for cat, patterns in error_patterns.items():
        if any(re.search(pattern, error_text, re.IGNORECASE) for pattern in patterns):
            found_cats.add(cat)
    if not found_cats and re.search(r"(?i)(error:|CRITICAL WARNING:|fatal)", error_text):
        found_cats.add("unknown fatal error")

    cat_list = sorted(found_cats)
    advice_str = "\n".join([advice_map.get(cat, "") for cat in cat_list])
    level_str = ", ".join(cat_list)
    if found_cats:
        update_error_memory(
            ctx,
            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] stage: {stage}\n"
            f"- categories: {level_str}\n- summary: {error_text.strip()[:400]}\n- advice: {advice_str}",
        )
        print(f"[Diagnostics] found issue: {level_str}")
    return cat_list, advice_str, level_str


def classify_iverilog_log(log, returncode):
    lines = [line.strip() for line in (log or "").splitlines() if line.strip()]
    errors, blocking_warnings, nonblocking_warnings = [], [], []
    nonblocking_warning_patterns = [
        r"warning:\s*timescale .* inherited from another file",
        r"\.\.\.:\s*the inherited timescale is here\.",
        r"warning:\s*@\* is sensitive to all \d+ words in array",
    ]
    blocking_warning_patterns = [
        r"warning:.*implicit",
        r"warning:.*port .* expects",
        r"warning:.*pruning",
        r"warning:.*padding",
        r"warning:.*sensitivity",
        r"warning:.*latch",
        r"warning:.*constant selects",
    ]
    for line in lines:
        lower = line.lower()
        if "requires systemverilog" in lower:
            errors.append(
                line
                + " [Verilog-2001 violation: move declarations to module scope or remove SystemVerilog syntax]"
            )
        elif "error:" in lower or "syntax error" in lower or "i give up" in lower:
            errors.append(line)
        elif "warning:" in lower or "the inherited timescale is here" in lower:
            if any(re.search(pattern, line, re.IGNORECASE) for pattern in nonblocking_warning_patterns):
                nonblocking_warnings.append(line)
            elif any(re.search(pattern, line, re.IGNORECASE) for pattern in blocking_warning_patterns):
                blocking_warnings.append(line)
            else:
                blocking_warnings.append(line)
    if returncode != 0 and not errors:
        errors.append(log.strip() or f"iverilog exited with code {returncode}")
    return {
        "errors": errors,
        "blocking_warnings": blocking_warnings,
        "nonblocking_warnings": nonblocking_warnings,
        "raw_log": log,
    }


def format_iverilog_result(stage_name, result):
    chunks = []
    if result["errors"]:
        chunks.append("[Errors]\n" + "\n".join(result["errors"]))
    if result["blocking_warnings"]:
        chunks.append("[Blocking Warnings]\n" + "\n".join(result["blocking_warnings"]))
    if result["nonblocking_warnings"]:
        chunks.append("[Non-blocking Warnings]\n" + "\n".join(result["nonblocking_warnings"]))
    return f"{stage_name} check failed:\n" + "\n\n".join(chunks)
