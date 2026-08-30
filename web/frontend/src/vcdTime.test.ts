import { describe, expect, it } from "vitest";
import { bigIntTime, vcdTimeAtSample } from "./vcdTime";

// A VCD in the shape Analyzer.export_vcd_text emits: header lines, then one
// `#<time>` line per sample followed by that sample's value lines.
function makeVcd(times: number[]): string {
  const head = [
    "$timescale",
    "  10 ns",
    "$end",
    "$scope module logic $end",
    "$var wire 1 t f $end",
    "$upscope $end",
    "$enddefinitions $end",
    "$dumpvars",
    "b0 t",
    "$end",
  ];
  const body = times.flatMap((t, i) => [`#${t}`, `b${i % 2} t`]);
  return head.concat(body).join("\n") + "\n";
}

describe("bigIntTime", () => {
  it("encodes zero as NoSign with no digits", () => {
    expect(bigIntTime(0)).toEqual([0, []]);
  });

  it("encodes small positive integers as Plus + single digit", () => {
    expect(bigIntTime(8)).toEqual([1, [8]]);
    expect(bigIntTime(20)).toEqual([1, [20]]);
  });

  it("floors fractional and clamps negative to zero", () => {
    expect(bigIntTime(8.9)).toEqual([1, [8]]);
    expect(bigIntTime(-5)).toEqual([0, []]);
  });

  it("splits values wider than 32 bits into little-endian u32 digits", () => {
    // 0x1_0000_0000 -> low word 0, high word 1
    expect(bigIntTime(0x1_0000_0000)).toEqual([1, [0, 1]]);
    // 0x2_0000_0005 -> low word 5, high word 2
    expect(bigIntTime(0x2_0000_0005)).toEqual([1, [5, 2]]);
  });
});

describe("vcdTimeAtSample", () => {
  it("returns the time of the Nth `#` line (contiguous index case)", () => {
    const vcd = makeVcd([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
    expect(vcdTimeAtSample(vcd, 0)).toBe(0);
    expect(vcdTimeAtSample(vcd, 8)).toBe(8);
    expect(vcdTimeAtSample(vcd, 9)).toBe(9);
  });

  it("follows real (non-index) per-sample timestamps", () => {
    const vcd = makeVcd([0, 10, 25, 40, 100]);
    expect(vcdTimeAtSample(vcd, 2)).toBe(25);
    expect(vcdTimeAtSample(vcd, 4)).toBe(100);
  });

  it("returns undefined past the last sample", () => {
    const vcd = makeVcd([0, 1, 2]);
    expect(vcdTimeAtSample(vcd, 3)).toBeUndefined();
    expect(vcdTimeAtSample(vcd, 99)).toBeUndefined();
  });

  it("rejects negative, non-finite, and returns undefined with no samples", () => {
    const vcd = makeVcd([0, 1, 2]);
    expect(vcdTimeAtSample(vcd, -1)).toBeUndefined();
    expect(vcdTimeAtSample(vcd, Number.NaN)).toBeUndefined();
    expect(vcdTimeAtSample("$enddefinitions $end\n", 0)).toBeUndefined();
  });

  it("floors a fractional sample index", () => {
    const vcd = makeVcd([0, 10, 20, 30]);
    expect(vcdTimeAtSample(vcd, 2.7)).toBe(20);
  });
});
