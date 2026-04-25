# Auto-generated structured XDC for top module counter_load_updown_top
# Source: D:\llm_project\llm_project\projects\counter_load_updown_20260424_174029\src\counter_load_updown_top.v
# Pin assignments are taken only from knowledge_base/board_pins.json.

create_clock -period 20.000 -name sys_clk_pin -waveform {0.000 10.000} [get_ports clk]

set_property PACKAGE_PIN K17 [get_ports clk]
set_property IOSTANDARD LVCMOS33 [get_ports clk]

set_property PACKAGE_PIN M19 [get_ports rst_n]
set_property IOSTANDARD LVCMOS33 [get_ports rst_n]

set_property PACKAGE_PIN N18 [get_ports en]
set_property IOSTANDARD LVCMOS33 [get_ports en]

set_property PACKAGE_PIN P16 [get_ports load]
set_property IOSTANDARD LVCMOS33 [get_ports load]

set_property PACKAGE_PIN R16 [get_ports up_down]
set_property IOSTANDARD LVCMOS33 [get_ports up_down]

set_property PACKAGE_PIN P15 [get_ports {load_value[3]}]
set_property IOSTANDARD LVCMOS33 [get_ports {load_value[3]}]

set_property PACKAGE_PIN L15 [get_ports {load_value[2]}]
set_property IOSTANDARD LVCMOS33 [get_ports {load_value[2]}]

set_property PACKAGE_PIN L14 [get_ports {load_value[1]}]
set_property IOSTANDARD LVCMOS33 [get_ports {load_value[1]}]

set_property PACKAGE_PIN T17 [get_ports {load_value[0]}]
set_property IOSTANDARD LVCMOS33 [get_ports {load_value[0]}]

set_property PACKAGE_PIN J16 [get_ports {count[3]}]
set_property IOSTANDARD LVCMOS33 [get_ports {count[3]}]

set_property PACKAGE_PIN K16 [get_ports {count[2]}]
set_property IOSTANDARD LVCMOS33 [get_ports {count[2]}]

set_property PACKAGE_PIN M15 [get_ports {count[1]}]
set_property IOSTANDARD LVCMOS33 [get_ports {count[1]}]

set_property PACKAGE_PIN M14 [get_ports {count[0]}]
set_property IOSTANDARD LVCMOS33 [get_ports {count[0]}]

set_property PACKAGE_PIN N15 [get_ports overflow]
set_property IOSTANDARD LVCMOS33 [get_ports overflow]

set_property PACKAGE_PIN U17 [get_ports underflow]
set_property IOSTANDARD LVCMOS33 [get_ports underflow]
