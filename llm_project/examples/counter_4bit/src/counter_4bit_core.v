`timescale 1ns / 1ps

module counter_4bit_core (
    input wire clk,
    input wire rst_n,
    input wire en,
    output reg [3:0] count,
    output reg overflow
);

always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        count <= 4'b0000;
        overflow <= 1'b0;
    end else begin
        if (en) begin
            if (count == 4'b1111) begin
                count <= 4'b0000;
                overflow <= 1'b1;
            end else begin
                count <= count + 1'b1;
                overflow <= 1'b0;
            end
        end else begin
            overflow <= 1'b0;
        end
    end
end

endmodule