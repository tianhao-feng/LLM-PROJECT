# Xilinx Skill Integration Notes

This directory contains curated notes derived from the public
`QingquanYao/xilinx-skill` repository.

Source repository:
https://github.com/QingquanYao/xilinx-skill

Purpose in AutoFPGA:

- Strengthen Vivado Tcl generation rules.
- Strengthen XDC timing and IO constraint guidance.
- Improve diagnostics for Vivado and XDC failures.
- Keep AutoFPGA's execution model unchanged: AutoFPGA still owns RTL/TB/XDC
  generation, Icarus precheck, ModelSim simulation, Vivado build, and
  `run_manifest.json` validation.

Integration policy:

- Treat these files as reference knowledge, not executable source.
- Do not allow the LLM to invent physical pins. `board_pins.json` remains the
  only source for package pin mappings.
- Prefer deterministic structured XDC generation over free-form XDC generated
  by an LLM.
- Use Vivado non-project style commands in batch builds when it makes logs and
  failures easier to capture.
