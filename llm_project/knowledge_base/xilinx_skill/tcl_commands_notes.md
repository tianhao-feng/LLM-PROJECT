# Vivado Tcl Command Notes

Derived from:
https://github.com/QingquanYao/xilinx-skill/blob/main/plugins/xilinx-suite/references/tcl_commands.md

## Project and File Commands

- `create_project`: create a project for a target part.
- `add_files`: add RTL sources.
- `add_files -fileset constrs_1`: add XDC constraints.
- `update_compile_order`: refresh source order.
- `set_property top <module> [current_fileset]`: set the RTL top.

## Direct Build Commands

- `synth_design`: synthesize the design.
- `opt_design`: optimize the synthesized netlist.
- `place_design`: place the design.
- `phys_opt_design`: optional physical optimization for harder timing closure.
- `route_design`: route the design.
- `write_bitstream`: generate the bitstream.

## Report Commands

- `report_timing_summary`: timing pass/fail summary.
- `report_timing`: detailed timing paths.
- `report_utilization`: LUT/FF/IO/resource usage.
- `report_power`: power estimate.
- `report_drc`: design rule checks.
- `report_io`: IO pin and standard report.

## Diagnostic Commands Worth Adding Later

These are useful future extensions for AutoFPGA:

```tcl
report_drc -file <out_dir>/report_drc.rpt
report_io -file <out_dir>/report_io.rpt
report_clock_utilization -file <out_dir>/report_clocks.rpt
report_clock_interaction -file <out_dir>/report_clock_interaction.rpt
```

They can make `run_manifest.json` richer and improve automatic debugging.
