# XDC Constraint Notes

Derived from:
https://github.com/QingquanYao/xilinx-skill/blob/main/plugins/xilinx-suite/references/xdc_constraints.md

## Constraint Order

Use this order:

1. clock definitions,
2. IO package pin and IO standard constraints,
3. timing exceptions.

AutoFPGA's structured XDC generator follows this order.

## Required IO Properties

Every top-level physical IO must have both:

```xdc
set_property PACKAGE_PIN <pin> [get_ports <port>]
set_property IOSTANDARD <standard> [get_ports <port>]
```

For indexed vector ports, use braces:

```xdc
set_property PACKAGE_PIN M14 [get_ports {count[0]}]
set_property IOSTANDARD LVCMOS33 [get_ports {count[0]}]
```

## Clock Constraint

The primary clock should be constrained with `create_clock`:

```xdc
create_clock -period 20.000 -name sys_clk_pin -waveform {0.000 10.000} [get_ports clk]
```

## AutoFPGA Policy

- Parse top-level RTL ports before generating XDC.
- Load pin mappings only from `knowledge_base/board_pins.json`.
- Refuse to generate XDC if a top-level port has no mapping.
- Refuse duplicate package pins among currently used top-level ports.
- Do not ask the LLM to invent board pins.

## Common Errors

- `No ports matched`: XDC port name does not match the RTL top-level port.
- `DRC UCIO-1`: at least one logical port has no package pin.
- `DRC NSTD-1`: at least one logical port has no IO standard.
- `not a valid site or package pin name`: the pin does not exist for the
  selected part/package.
- Mixed IO standards in one bank may fail DRC depending on board VCCIO.
