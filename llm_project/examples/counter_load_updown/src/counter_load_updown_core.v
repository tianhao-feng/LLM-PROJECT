`timescale 1ns / 1ps

module counter_load_updown_core (
    input wire clk,
    input wire rst_n,
    input wire en,
    input wire load,
    input wire up_down,
    input wire [3:0] load_value,
    output reg [3:0] count,
    output reg overflow,
    output reg underflow
);

reg [3:0] next_count;
reg next_overflow;
reg next_underflow;

always @(*) begin
    if (load) begin
        next_count = load_value;
        next_overflow = 1'b0;
        next_underflow = 1'b0;
    end else if (en) begin
        if (up_down) begin
            if (count == 4'd15) begin
                next_count = 4'd0;
                next_overflow = 1'b1;
                next_underflow = 1'b0;
            end else begin
                next_count = count + 1'b1;
                next_overflow = 1'b0;
                next_underflow = 1'b0;
            end
        end else begin
            if (count == 4'd0) begin
                next_count = 4'd15;
                next_underflow = 1'b1;
                next_overflow = 1'b0;
            end else begin
                next_count = count - 1'b1;
                next_underflow = 1'b0;
                next_overflow = 1'b0;
            end
        end
    end else begin
        next_count = count;
        next_overflow = 1'b0;
        next_underflow = 1'b0;
    end
end

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        count <= 4'd0;
        overflow <= 1'b0;
        underflow <= 1'b0;
    end else begin
        count <= next_count;
        overflow <= next_overflow;
        underflow <= next_underflow;
    end
end

endmodule