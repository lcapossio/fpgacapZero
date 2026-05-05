-- SPDX-License-Identifier: Apache-2.0
-- Copyright (c) 2026 Leonardo Capossio - bard0 design - <hello@bard0.com>

package fcapz_util_pkg is
    function fcapz_clog2(n : positive) return positive;
    function fcapz_nonzero_width(n : natural) return positive;
    function fcapz_probe_width(probe_mux_w : natural; num_channels : positive; sample_w : positive) return positive;
end package fcapz_util_pkg;

package body fcapz_util_pkg is
    function fcapz_clog2(n : positive) return positive is
        variable value : natural := n - 1;
        variable width : natural := 0;
    begin
        while value > 0 loop
            width := width + 1;
            value := value / 2;
        end loop;
        if width = 0 then
            return 1;
        end if;
        return width;
    end function;

    function fcapz_nonzero_width(n : natural) return positive is
    begin
        if n = 0 then
            return 1;
        end if;
        return n;
    end function;

    function fcapz_probe_width(probe_mux_w : natural; num_channels : positive; sample_w : positive) return positive is
    begin
        if probe_mux_w > 0 then
            return probe_mux_w;
        end if;
        return num_channels * sample_w;
    end function;
end package body fcapz_util_pkg;
