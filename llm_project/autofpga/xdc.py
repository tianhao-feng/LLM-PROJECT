import json
import os
import re

from .tools import discover_top_module


DEFAULT_BOARD_PIN_DB = {
    "board": "Zynq 7020 CLG400 reference mapping",
    "part": "xc7z020clg400-2",
    "default_iostandard": "LVCMOS33",
    "default_clock_period_ns": 20.0,
    "ports": {
        "clk": {"pin": "K17", "clock": True, "clock_name": "sys_clk_pin"},
        "rst_n": {"pin": "M19"},
        "en": {"pin": "N18"},
        "led_out[0]": {"pin": "M14"},
        "led_out[1]": {"pin": "M15"},
        "led_out[2]": {"pin": "K16"},
        "led_out[3]": {"pin": "J16"},
        "led_out[4]": {"pin": "N15"},
        "led_out[5]": {"pin": "P16"},
        "led_out[6]": {"pin": "R16"},
        "led_out[7]": {"pin": "T17"},
        "count[0]": {"pin": "M14"},
        "count[1]": {"pin": "M15"},
        "count[2]": {"pin": "K16"},
        "count[3]": {"pin": "J16"},
        "overflow": {"pin": "N15"},
    },
}


def ensure_board_pin_database(ctx):
    os.makedirs(ctx.kb_dir, exist_ok=True)
    path = board_pin_db_path(ctx)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_BOARD_PIN_DB, f, ensure_ascii=False, indent=2)
    return path


def board_pin_db_path(ctx):
    return os.path.join(ctx.kb_dir, "board_pins.json")


def load_board_pin_database(ctx):
    path = ensure_board_pin_database(ctx)
    with open(path, "r", encoding="utf-8") as f:
        db = json.load(f)
    if not isinstance(db, dict) or not isinstance(db.get("ports"), dict):
        raise ValueError(f"板卡 pin database 格式错误: {path}")
    return db


def generate_structured_xdc(ctx):
    top_module = discover_top_module(ctx)
    if not top_module:
        raise RuntimeError("无法生成 XDC：未能自动识别顶层模块。")

    top_file, top_ports = parse_top_module_ports(ctx.src_dir, top_module)
    if not top_ports:
        raise RuntimeError(f"无法生成 XDC：顶层模块 {top_module} 未解析到端口。")

    db = load_board_pin_database(ctx)
    xdc_code = build_xdc_from_ports(top_ports, db, top_module, top_file)
    with open(ctx.xdc_file, "w", encoding="utf-8") as f:
        f.write(xdc_code)
    return xdc_code


def parse_top_module_ports(src_dir, top_module):
    for fname in sorted(os.listdir(src_dir)):
        if not fname.endswith(".v"):
            continue
        path = os.path.join(src_dir, fname)
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
        clean = strip_verilog_comments(text)
        match = re.search(
            rf"\bmodule\s+{re.escape(top_module)}\b\s*(?:#\s*\([\s\S]*?\)\s*)?\((?P<header>[\s\S]*?)\)\s*;",
            clean,
            flags=re.MULTILINE,
        )
        if not match:
            continue
        module_text = clean[match.start():]
        ports = parse_ansi_ports(match.group("header"))
        if not ports:
            ports = parse_non_ansi_ports(module_text)
        return path, ports
    return None, []


def strip_verilog_comments(text):
    text = re.sub(r"/\*[\s\S]*?\*/", "", text or "")
    text = re.sub(r"//.*", "", text)
    return text


def parse_ansi_ports(header):
    ports = []
    current_direction = None
    current_range = None
    for raw_entry in split_port_entries(header):
        entry = raw_entry.strip()
        if not entry:
            continue
        match = re.match(r"^(input|output|inout)\b\s*(.*)$", entry, flags=re.IGNORECASE | re.DOTALL)
        if match:
            current_direction = match.group(1).lower()
            rest = match.group(2).strip()
            rest = re.sub(r"^(wire|reg)\b\s*", "", rest, flags=re.IGNORECASE)
            range_match = re.match(r"^(\[[^\]]+\])\s*(.*)$", rest, flags=re.DOTALL)
            if range_match:
                current_range = range_match.group(1)
                rest = range_match.group(2).strip()
            else:
                current_range = None
            name = clean_port_name(rest)
        else:
            if not current_direction:
                continue
            name = clean_port_name(entry)
        if name:
            ports.append(make_port(name, current_direction, current_range))
    return ports


def parse_non_ansi_ports(module_text):
    ports = []
    for match in re.finditer(
        r"\b(input|output|inout)\b\s*(?:wire|reg)?\s*(\[[^\]]+\])?\s*([^;]+);",
        module_text,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        direction = match.group(1).lower()
        width_range = match.group(2)
        for name_part in match.group(3).split(","):
            name = clean_port_name(name_part)
            if name:
                ports.append(make_port(name, direction, width_range))
    return ports


def split_port_entries(header):
    entries = []
    current = []
    bracket_depth = 0
    for char in header:
        if char == "[":
            bracket_depth += 1
        elif char == "]" and bracket_depth:
            bracket_depth -= 1
        if char == "," and bracket_depth == 0:
            entries.append("".join(current))
            current = []
        else:
            current.append(char)
    if current:
        entries.append("".join(current))
    return entries


def clean_port_name(text):
    text = (text or "").strip()
    text = re.sub(r"=.*$", "", text).strip()
    text = re.sub(r"\b(wire|reg)\b", "", text, flags=re.IGNORECASE).strip()
    match = re.match(r"([a-zA-Z_][a-zA-Z0-9_$]*)", text)
    return match.group(1) if match else ""


def make_port(name, direction, width_range):
    bits = expand_port_bits(name, width_range)
    return {
        "name": name,
        "direction": direction,
        "range": width_range,
        "bits": bits,
    }


def expand_port_bits(name, width_range):
    if not width_range:
        return [name]
    match = re.match(r"\[\s*(\d+)\s*:\s*(\d+)\s*\]", width_range.strip())
    if not match:
        raise ValueError(f"暂不支持参数化或非数字位宽端口约束: {name} {width_range}")
    left, right = int(match.group(1)), int(match.group(2))
    step = 1 if right >= left else -1
    return [f"{name}[{idx}]" for idx in range(left, right + step, step)]


def build_xdc_from_ports(top_ports, db, top_module, top_file):
    pin_map = db["ports"]
    default_iostandard = db.get("default_iostandard", "LVCMOS33")
    default_period = float(db.get("default_clock_period_ns", 20.0))

    required_bits = []
    for port in top_ports:
        required_bits.extend(port["bits"])

    missing = [bit for bit in required_bits if bit not in pin_map]
    if missing:
        raise RuntimeError(
            "XDC 生成被拒绝：以下顶层端口没有 board_pins.json 映射，不能让 LLM 发明引脚: "
            + ", ".join(missing)
        )

    used_pins = {}
    duplicates = []
    for bit in required_bits:
        pin = pin_map[bit].get("pin")
        if not pin:
            raise RuntimeError(f"XDC 生成被拒绝：board_pins.json 中 {bit} 缺少 pin 字段。")
        if pin in used_pins:
            duplicates.append(f"{bit} 与 {used_pins[pin]} 复用 PACKAGE_PIN {pin}")
        used_pins[pin] = bit
    if duplicates:
        raise RuntimeError("XDC 生成被拒绝：当前顶层端口存在引脚冲突: " + "; ".join(duplicates))

    lines = [
        f"# Auto-generated structured XDC for top module {top_module}",
        f"# Source: {top_file}",
        "# Pin assignments are taken only from knowledge_base/board_pins.json.",
        "",
    ]

    for bit in required_bits:
        entry = pin_map[bit]
        if entry.get("clock"):
            period = float(entry.get("period_ns", default_period))
            half = period / 2.0
            clock_name = entry.get("clock_name", bit)
            lines.append(
                f"create_clock -period {period:.3f} -name {clock_name} "
                f"-waveform {{0.000 {half:.3f}}} [get_ports {format_get_ports(bit)}]"
            )
            lines.append("")

    for bit in required_bits:
        entry = pin_map[bit]
        iostandard = entry.get("iostandard", default_iostandard)
        lines.append(f"set_property PACKAGE_PIN {entry['pin']} [get_ports {format_get_ports(bit)}]")
        lines.append(f"set_property IOSTANDARD {iostandard} [get_ports {format_get_ports(bit)}]")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def format_get_ports(port_bit):
    if "[" in port_bit or "]" in port_bit:
        return "{" + port_bit + "}"
    return port_bit
