`timescale 1ns / 1ps

module counter_load_updown_top (
    input wire clk,
    input wire rst_n,
    input wire en,
    input wire load,
    input wire up_down,
    input wire [3:0] load_value,
    output wire [3:0] count,
    output wire overflow,
    output wire underflow
);

counter_load_updown_core u_core (
    .clk(clk),
    .rst_n(rst_n),
    .en(en),
    .load(load),
    .up_down(up_down),
    .load_value(load_value),
    .count(count),
    .overflow(overflow),
    .underflow(underflow)
);

endmodule