`timescale 1ns / 1ps

module counter_4bit_top (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       en,
    output wire [3:0] count,
    output wire       overflow
);

    counter_4bit_core u_core (
        .clk      (clk),
        .rst_n    (rst_n),
        .en       (en),
        .count    (count),
        .overflow (overflow)
    );

endmodule