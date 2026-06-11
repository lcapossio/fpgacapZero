// SPDX-License-Identifier: Apache-2.0
// Deliberately bad RTL used by sim/run_verilator_lint.py --self-test.
// The Verilator run must reject this because .v files are linted as
// Verilog-2001, where the ++ increment operator is not valid syntax.

module verilator_sv_syntax_bad (
    input wire clk,
    output reg [1:0] q
);
    integer i;

    always @(posedge clk) begin
        for (i = 0; i < 2; i++) begin
            q[i] <= 1'b1;
        end
    end
endmodule
