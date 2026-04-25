`timescale 1ns / 1ps

module tb_counter_load_updown_top;

    reg clk;
    reg rst_n;
    reg en;
    reg load;
    reg up_down;
    reg [3:0] load_value;
    wire [3:0] count;
    wire overflow;
    wire underflow;

    reg test_failed;
    integer i;

    counter_load_updown_top dut (
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

    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    initial begin
        test_failed = 1'b0;
        rst_n = 1'b0;
        en = 1'b0;
        load = 1'b0;
        up_down = 1'b1;
        load_value = 4'h0;

        #12;
        if (count !== 4'h0) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: reset count expected 0, got %b", count);
            test_failed = 1'b1;
        end

        @(negedge clk);
        rst_n = 1'b1;
        en = 1'b0;
        load = 1'b0;
        @(posedge clk);
        #1;
        if (count !== 4'h0) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: disabled counter changed after reset, got %b", count);
            test_failed = 1'b1;
        end

        @(negedge clk);
        load_value = 4'ha;
        load = 1'b1;
        en = 1'b0;
        @(posedge clk);
        #1;
        if (count !== 4'ha) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: load expected a, got %b", count);
            test_failed = 1'b1;
        end

        @(negedge clk);
        load = 1'b0;
        en = 1'b1;
        up_down = 1'b1;
        for (i = 0; i < 3; i = i + 1) begin
            @(posedge clk);
            #1;
        end
        if (count !== 4'hd) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: up count from a for 3 cycles expected d, got %b", count);
            test_failed = 1'b1;
        end

        @(negedge clk);
        load = 1'b1;
        load_value = 4'hf;
        @(posedge clk);
        #1;
        if (count !== 4'hf) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: load expected f, got %b", count);
            test_failed = 1'b1;
        end

        @(negedge clk);
        load = 1'b0;
        en = 1'b1;
        up_down = 1'b1;
        @(posedge clk);
        #1;
        if (count !== 4'h0) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: overflow wrap expected 0, got %b", count);
            test_failed = 1'b1;
        end
        if (overflow !== 1'b1) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: overflow flag expected 1 on wrap up");
            test_failed = 1'b1;
        end

        if (underflow !== 1'b0) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: underflow flag expected 0 on wrap up");
            test_failed = 1'b1;
        end

        @(posedge clk);
        #1;
        if (count !== 4'h1) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: count after overflow expected 1, got %b", count);
            test_failed = 1'b1;
        end
        if (overflow !== 1'b0) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: overflow flag should clear after one cycle");
            test_failed = 1'b1;
        end

        @(negedge clk);
        load = 1'b1;
        load_value = 4'h0;
        @(posedge clk);
        #1;
        if (count !== 4'h0) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: load expected 0, got %b", count);
            test_failed = 1'b1;
        end

        @(negedge clk);
        load = 1'b0;
        en = 1'b1;
        up_down = 1'b0;
        @(posedge clk);
        #1;
        if (count !== 4'hf) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: underflow wrap expected f, got %b", count);
            test_failed = 1'b1;
        end
        if (underflow !== 1'b1) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: underflow flag expected 1 on wrap down");
            test_failed = 1'b1;
        end

        if (overflow !== 1'b0) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: overflow flag expected 0 on wrap down");
            test_failed = 1'b1;
        end

        @(posedge clk);
        #1;
        if (count !== 4'he) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: count after underflow expected e, got %b", count);
            test_failed = 1'b1;
        end
        if (underflow !== 1'b0) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: underflow flag should clear after one cycle");
            test_failed = 1'b1;
        end

        @(negedge clk);
        en = 1'b0;
        @(posedge clk);
        #1;
        if (count !== 4'he) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: disabled counter expected hold e, got %b", count);
            test_failed = 1'b1;
        end

        #2;
        rst_n = 1'b0;
        #1;
        if (count !== 4'h0) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: async reset count expected 0, got %b", count);
            test_failed = 1'b1;
        end

        if (test_failed) begin
            $display("SIM_RESULT: FAILED");
        end else begin
            $display("SIM_RESULT: PASSED");
        end
        $stop;
    end

endmodule