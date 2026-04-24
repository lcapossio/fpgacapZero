`timescale 1ns/1ps

module trig_compare_tb;
    reg  [7:0] probe;
    reg  [7:0] probe_prev;
    reg  [7:0] value;
    reg  [7:0] mask;
    reg  [3:0] mode;
    wire       hit_light;
    wire       hit_full;

    integer passed = 0;
    integer failed = 0;

    trig_compare #(.W(8), .REL_COMPARE(0)) dut_light (
        .probe(probe),
        .probe_prev(probe_prev),
        .value(value),
        .mask(mask),
        .mode(mode),
        .hit(hit_light)
    );

    trig_compare #(.W(8), .REL_COMPARE(1)) dut_full (
        .probe(probe),
        .probe_prev(probe_prev),
        .value(value),
        .mask(mask),
        .mode(mode),
        .hit(hit_full)
    );

    task check;
        input string name;
        input actual;
        input expected;
        begin
            if (actual === expected) begin
                passed = passed + 1;
                $display("PASS: %0s", name);
            end else begin
                failed = failed + 1;
                $display("FAIL: %0s expected %0b got %0b", name, expected, actual);
            end
        end
    endtask

    initial begin
        probe = 8'h12;
        probe_prev = 8'h10;
        value = 8'h12;
        mask = 8'hff;
        mode = 4'd0;
        #1;
        check("EQ works in lightweight mode", hit_light, 1'b1);
        check("EQ works in full mode", hit_full, 1'b1);

        value = 8'h10;
        mode = 4'd1;
        #1;
        check("NEQ works in lightweight mode", hit_light, 1'b1);
        check("NEQ works in full mode", hit_full, 1'b1);

        probe_prev = 8'h00;
        probe = 8'h01;
        value = 8'h00;
        mode = 4'd6;
        #1;
        check("RISING works in lightweight mode", hit_light, 1'b1);
        check("RISING works in full mode", hit_full, 1'b1);

        probe_prev = 8'h01;
        probe = 8'h00;
        mode = 4'd7;
        #1;
        check("FALLING works in lightweight mode", hit_light, 1'b1);
        check("FALLING works in full mode", hit_full, 1'b1);

        probe_prev = 8'h55;
        probe = 8'h5d;
        mode = 4'd8;
        #1;
        check("CHANGED works in lightweight mode", hit_light, 1'b1);
        check("CHANGED works in full mode", hit_full, 1'b1);

        probe = 8'h05;
        value = 8'h10;
        mask = 8'hff;
        mode = 4'd2;
        #1;
        check("LT is compiled out in lightweight mode", hit_light, 1'b0);
        check("LT works in full mode", hit_full, 1'b1);

        probe = 8'h20;
        value = 8'h10;
        mode = 4'd3;
        #1;
        check("GT is compiled out in lightweight mode", hit_light, 1'b0);
        check("GT works in full mode", hit_full, 1'b1);

        probe = 8'h10;
        value = 8'h10;
        mode = 4'd4;
        #1;
        check("LEQ is compiled out in lightweight mode", hit_light, 1'b0);
        check("LEQ works in full mode", hit_full, 1'b1);

        probe = 8'h10;
        value = 8'h10;
        mode = 4'd5;
        #1;
        check("GEQ is compiled out in lightweight mode", hit_light, 1'b0);
        check("GEQ works in full mode", hit_full, 1'b1);

        $display("\n=== trig_compare summary: %0d passed, %0d failed ===", passed, failed);
        if (failed)
            $fatal(1);
        $finish;
    end
endmodule
