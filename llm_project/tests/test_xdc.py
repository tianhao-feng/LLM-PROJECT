import os
import unittest
import uuid

from autofpga.xdc import build_xdc_from_ports, parse_top_module_ports


def reset_tmp(name):
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "codex_test_tmp", f"{name}_{uuid.uuid4().hex}")
    os.makedirs(path)
    return path


class XdcTests(unittest.TestCase):
    def test_parse_top_module_ports_and_generate_xdc(self):
        tmp = reset_tmp("xdc_counter")
        src_dir = os.path.join(tmp, "src")
        os.makedirs(src_dir)
        top_file = os.path.join(src_dir, "counter_top.v")
        with open(top_file, "w", encoding="utf-8") as f:
            f.write(
                """
module counter_top (
    input clk,
    input rst_n,
    input en,
    output reg [3:0] count,
    output overflow
);
endmodule
"""
            )

        parsed_file, ports = parse_top_module_ports(src_dir, "counter_top")

        self.assertEqual(parsed_file, top_file)
        self.assertEqual([port["name"] for port in ports], ["clk", "rst_n", "en", "count", "overflow"])
        self.assertEqual(ports[-2]["bits"], ["count[3]", "count[2]", "count[1]", "count[0]"])

        db = {
            "default_iostandard": "LVCMOS33",
            "default_clock_period_ns": 20.0,
            "ports": {
                "clk": {"pin": "K17", "clock": True, "clock_name": "sys_clk_pin"},
                "rst_n": {"pin": "M19"},
                "en": {"pin": "N18"},
                "count[0]": {"pin": "M14"},
                "count[1]": {"pin": "M15"},
                "count[2]": {"pin": "K16"},
                "count[3]": {"pin": "J16"},
                "overflow": {"pin": "N15"},
            },
        }

        xdc = build_xdc_from_ports(ports, db, "counter_top", parsed_file)

        self.assertIn("create_clock -period 20.000", xdc)
        self.assertIn("set_property PACKAGE_PIN N18 [get_ports en]", xdc)
        self.assertIn("set_property PACKAGE_PIN J16 [get_ports {count[3]}]", xdc)
        self.assertIn("set_property PACKAGE_PIN N15 [get_ports overflow]", xdc)

    def test_xdc_rejects_missing_pin_mapping(self):
        ports = [{"name": "en", "direction": "input", "range": None, "bits": ["en"]}]
        db = {"ports": {}}

        with self.assertRaisesRegex(RuntimeError, "没有 board_pins.json 映射"):
            build_xdc_from_ports(ports, db, "top", "top.v")

    def test_xdc_rejects_duplicate_pin_mapping(self):
        ports = [
            {"name": "a", "direction": "input", "range": None, "bits": ["a"]},
            {"name": "b", "direction": "input", "range": None, "bits": ["b"]},
        ]
        db = {"ports": {"a": {"pin": "K17"}, "b": {"pin": "K17"}}}

        with self.assertRaisesRegex(RuntimeError, "引脚冲突"):
            build_xdc_from_ports(ports, db, "top", "top.v")


if __name__ == "__main__":
    unittest.main()
