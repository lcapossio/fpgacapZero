// SPDX-License-Identifier: Apache-2.0
// Deliberately bad RTL used by sim/run_yosys_check.py --self-test.
// One module-level integer is the loop index of two clocked blocks. After
// `proc` each block owns a flop for it, so yosys `check` must report
// conflicting drivers; if it does not, the gate no longer proves the bug class
// that LibreLane's pre-synthesis check rejects.

module yosys_shared_loop_index_bad (
    input  wire       clk,
    input  wire       rst,
    input  wire [3:0] d,
    output reg  [3:0] q_a,
    output reg  [3:0] q_b
);
    integer i;

    always @(posedge clk or posedge rst) begin
        if (rst)
            q_a <= 4'd0;
        else
            for (i = 0; i < 4; i = i + 1)
                q_a[i] <= d[i];
    end

    always @(posedge clk or posedge rst) begin
        if (rst)
            q_b <= 4'd0;
        else
            for (i = 0; i < 4; i = i + 1)
                q_b[i] <= ~d[i];
    end
endmodule
