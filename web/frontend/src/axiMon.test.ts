// Unit tests for the AXI monitor helpers: trigger value/mask construction
// must place bits exactly where the server's probe map says the fields live.

import { describe, expect, it } from "vitest";
import { axiEventProbes, axiEventTrigger, axiWriteAddrTrigger, probesToText } from "./axiMon";
import type { AxiMonInfo } from "./axiMon";

// Mirrors the bundled axi4lite_32_decode.prob layout (events in the low byte).
const DECODE_INFO: AxiMonInfo = {
  proto: "AXI4LITE",
  addr_w: 32,
  data_w: 32,
  decode: true,
  sample_width: 160,
  probes: [
    { name: "aw_hs", width: 1, lsb: 0 },
    { name: "b_err", width: 1, lsb: 5 },
    { name: "any_err", width: 1, lsb: 7 },
    { name: "awaddr", width: 32, lsb: 8 },
    { name: "wdata", width: 32, lsb: 45 },
  ],
};

// Mirrors axi4lite_32.prob (no decode layer; awaddr in the low 32 bits).
const PLAIN_INFO: AxiMonInfo = {
  proto: "AXI4LITE",
  addr_w: 32,
  data_w: 32,
  decode: false,
  sample_width: 152,
  probes: [
    { name: "awaddr", width: 32, lsb: 0 },
    { name: "awvalid", width: 1, lsb: 35 },
  ],
};

describe("probesToText", () => {
  it("renders the ELA tab's name:width:lsb lines", () => {
    expect(probesToText(PLAIN_INFO.probes)).toBe("awaddr:32:0\nawvalid:1:35");
  });
});

describe("axiEventProbes", () => {
  it("returns the low-byte single-bit events in bit order (decode builds)", () => {
    expect(axiEventProbes(DECODE_INFO).map((p) => p.name)).toEqual([
      "aw_hs",
      "b_err",
      "any_err",
    ]);
  });

  it("is empty without the decode layer, even if 1-bit probes exist", () => {
    expect(axiEventProbes(PLAIN_INFO)).toEqual([]);
  });
});

describe("axiEventTrigger", () => {
  it("ORs the selected events' bits into value == mask", () => {
    expect(axiEventTrigger(DECODE_INFO, ["any_err"])).toEqual({
      value: "0x80",
      mask: "0x80",
    });
    expect(axiEventTrigger(DECODE_INFO, ["aw_hs", "b_err"])).toEqual({
      value: "0x21",
      mask: "0x21",
    });
  });

  it("rejects unknown events and empty selections", () => {
    expect(() => axiEventTrigger(DECODE_INFO, ["nope"])).toThrow(/unknown AXI event/);
    expect(() => axiEventTrigger(DECODE_INFO, [])).toThrow(/at least one/);
  });
});

describe("axiWriteAddrTrigger", () => {
  it("places the address at awaddr's lsb with a full-field mask", () => {
    expect(axiWriteAddrTrigger(PLAIN_INFO, "0x4000")).toEqual({
      value: "0x4000",
      mask: "0xFFFFFFFF",
    });
    // Decimal input goes through the same canonical-hex normalization.
    expect(axiWriteAddrTrigger(PLAIN_INFO, "64").value).toBe("0x40");
  });

  it("refuses when awaddr is out of the 32-bit comparator's reach (decode builds)", () => {
    expect(() => axiWriteAddrTrigger(DECODE_INFO, "0x0")).toThrow(/DECODE_EN=0/);
  });

  it("refuses addresses wider than the awaddr field", () => {
    expect(() => axiWriteAddrTrigger(PLAIN_INFO, "0x1FFFFFFFF")).toThrow(/exceeds/);
  });
});
