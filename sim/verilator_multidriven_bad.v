// SPDX-License-Identifier: Apache-2.0
// Deliberately bad RTL used by sim/run_verilator_lint.py --self-test.
// The Verilator run must reject this with %Warning-MULTIDRIVEN; if it does not,
// the lint gate is no longer proving the bug class that escaped iverilog.

module verilator_multidriven_bad (
    input  wire clk_a,
    input  wire clk_b,
    input  wire rst,
    output reg  q
);
    always @(posedge clk_a or posedge rst) begin
        if (rst)
            q <= 1'b0;
        else
            q <= 1'b1;
    end

    always @(posedge clk_b or posedge rst) begin
        if (rst)
            q <= 1'b0;
        else
            q <= 1'b0;
    end
endmodule
