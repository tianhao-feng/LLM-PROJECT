`timescale 1ns / 1ps

module tb_counter_4bit_top;

    reg clk;
    reg rst_n;
    reg en;
    wire [3:0] count;
    wire overflow;

    reg test_failed;
    reg [3:0] expected_count;
    reg [3:0] hold_count;
    integer i;

    counter_4bit_top dut (
        .clk(clk),
        .rst_n(rst_n),
        .en(en),
        .count(count),
        .overflow(overflow)
    );

    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    initial begin
        test_failed = 1'b0;
        expected_count = 4'h0;
        hold_count = 4'h0;
        rst_n = 1'b0;
        en = 1'b0;

        #12;
        if (count !== 4'h0) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: reset count expected 0, got %b", count);
            test_failed = 1'b1;
        end

        @(negedge clk);
        rst_n = 1'b1;
        en = 1'b0;
        @(posedge clk);
        #1;
        if (count !== 4'h0) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: count changed while disabled after reset, got %b", count);
            test_failed = 1'b1;
        end

        @(negedge clk);
        en = 1'b1;
        expected_count = 4'h0;
        for (i = 0; i < 20; i = i + 1) begin
            @(posedge clk);
            #1;
            expected_count = expected_count + 1'b1;
            if (count !== expected_count) begin
                $display("SIM_RESULT: FAILED");
                $display("ERROR: count mismatch at step %0d, expected %b, got %b", i, expected_count, count);
                test_failed = 1'b1;
            end

        end

        @(negedge clk);
        en = 1'b0;
        hold_count = count;
        for (i = 0; i < 3; i = i + 1) begin
            @(posedge clk);
            #1;
            if (count !== hold_count) begin
                $display("SIM_RESULT: FAILED");
                $display("ERROR: count changed while disabled, expected %b, got %b", hold_count, count);
                test_failed = 1'b1;
            end

        end

        @(negedge clk);
        en = 1'b1;
        @(posedge clk);
        #1;
        hold_count = hold_count + 1'b1;
        if (count !== hold_count) begin
            $display("SIM_RESULT: FAILED");
            $display("ERROR: count did not increment after re-enable, expected %b, got %b", hold_count, count);
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