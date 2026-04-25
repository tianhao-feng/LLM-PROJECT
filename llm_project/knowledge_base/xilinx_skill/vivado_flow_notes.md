# Vivado Flow Notes

Derived from:
https://github.com/QingquanYao/xilinx-skill/blob/main/plugins/xilinx-suite/references/vivado_guide.md

## Scope

AutoFPGA currently targets generated Verilog RTL projects and runs Vivado in
batch mode after Icarus and ModelSim pass. For this use case, the most useful
Vivado flow is a direct build sequence:

```tcl
create_project -force ai_project <out_dir> -part <part>
add_files <rtl_files>
add_files -fileset constrs_1 -norecurse <xdc_file>
update_compile_order -fileset sources_1
set_property top <top_module> [current_fileset]
synth_design -top <top_module> -part <part>
opt_design
place_design
route_design
report_utilization -file <out_dir>/report_utilization.rpt
report_timing_summary -delay_type min_max -max_paths 10 -file <out_dir>/report_timing.rpt
report_power -file <out_dir>/report_power.rpt
write_bitstream -force <out_dir>/<top_module>.bit
```

## Why AutoFPGA Uses This Style

- It keeps synthesis, implementation, reports, and bitstream generation in one
  Vivado process.
- It avoids secondary `launch_runs` scripts whose logs may be harder to collect.
- It makes stdout/stderr classification more reliable for self-healing.
- It maps cleanly to `run_manifest.json` artifact collection.

## Report Interpretation

- Timing passes only when setup, hold, and pulse width checks have no failing
  endpoints.
- `WNS < 0` means the requested clock period is too aggressive for at least one
  path.
- Useful next actions for timing failures:
  - add pipeline registers in RTL,
  - reduce combinational logic depth,
  - use `phys_opt_design` after placement for harder designs,
  - lower the target clock frequency when the requirement allows it.

## Common Vivado Build Checks

- Confirm the selected top module is not a submodule.
- Confirm every top-level IO appears in XDC if the design writes a bitstream.
- Confirm `write_bitstream` is reached and the bitstream path is captured in
  `run_manifest.json`.
- Keep Vivado logs under `projects/<project>/runs/vivado_logs/`.
