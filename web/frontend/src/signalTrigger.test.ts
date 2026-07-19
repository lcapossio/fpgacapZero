import { describe, expect, it } from "vitest";
import type { Identity, ProbeSpec } from "./api";
import type { TriggerTerm } from "./signalTrigger";
import {
  composeTrigger,
  defaultTerm,
  describeTerms,
  groupTerms,
  hasDirectionalEdges,
  parseTermValue,
  termWidth,
  triggerable,
} from "./signalTrigger";

const VALID: ProbeSpec = { name: "valid", width: 1, lsb: 3 };
const READY: ProbeSpec = { name: "ready", width: 1, lsb: 4 };
const STATE: ProbeSpec = { name: "state", width: 4, lsb: 8 };
const HIGH_FIELD: ProbeSpec = { name: "wdata", width: 32, lsb: 66 };
// A byte pair for the grouping tests: addr_hi is the MSB half, addr_lo the LSB.
const ADDR_HI: ProbeSpec = { name: "addr_hi", width: 8, lsb: 16 };
const ADDR_LO: ProbeSpec = { name: "addr_lo", width: 8, lsb: 0 };

function t(
  probe: ProbeSpec,
  value: string,
  op: TriggerTerm["op"] = "==",
  radix: TriggerTerm["radix"] = "B",
): TriggerTerm {
  return { probes: [probe], op, radix, value };
}

/** A grouped row (probes concatenated MSB-first). */
function g(
  probes: ProbeSpec[],
  value: string,
  op: TriggerTerm["op"] = "==",
  radix: TriggerTerm["radix"] = "H",
): TriggerTerm {
  return { probes, op, radix, value };
}

function ident(patch: Partial<Identity>): Identity {
  return {
    version_major: 0,
    version_minor: 4,
    core_id: 0x4c41,
    sample_width: 32,
    depth: 64,
    num_channels: 1,
    ...patch,
  };
}

const SEQ_BUILD = ident({
  trig_stages: 4,
  has_dual_compare: true,
  compare_modes: [0, 1, 6, 7, 8],
});
const SIMPLE_BUILD = ident({ trig_stages: 1 });

describe("parseTermValue", () => {
  it("binary with X don't-cares", () => {
    expect(parseTermValue(t(STATE, "1X0X"))).toEqual({ value: 0b1000n, mask: 0b1010n });
  });
  it("hex with X nibbles", () => {
    const p = parseTermValue({ probes: [{ name: "a", width: 8, lsb: 0 }], op: "==", radix: "H", value: "AX" });
    expect(p).toEqual({ value: 0xa0n, mask: 0xf0n });
  });
  it("edge tokens on 1-bit probes", () => {
    expect(parseTermValue(t(VALID, "R")).edge).toBe("R");
    expect(parseTermValue(t(VALID, "r")).edge).toBe("R");
    expect(() => parseTermValue(t(STATE, "R"))).toThrow(/binary value/);
  });
  it("range and character checks", () => {
    expect(() => parseTermValue(t(STATE, "10101"))).toThrow(/wider/);
    expect(() =>
      parseTermValue({ probes: [STATE], op: "==", radix: "U", value: "16" }),
    ).toThrow(/exceeds/);
    expect(() => parseTermValue(t(VALID, "Z"))).toThrow(/may use/);
  });
  it("parses a group value across the combined width (bit 0 = LSB of the field)", () => {
    // {addr_hi, addr_lo} is a 16-bit field; the value is relative to the field,
    // not yet placed onto the probes' real bit positions.
    expect(parseTermValue(g([ADDR_HI, ADDR_LO], "1234"))).toEqual({
      value: 0x1234n,
      mask: 0xffffn,
    });
  });
});

describe("composeTrigger", () => {
  it("a single == row is a plain value_match", () => {
    expect(composeTrigger([t(VALID, "1")], "and", SIMPLE_BUILD)).toMatchObject({
      triggerMode: "value_match",
      triggerValue: "0x8",
      triggerMask: "0x8",
      useSequencer: false,
    });
  });

  it("Global AND merges == rows (X bits drop out of the mask)", () => {
    expect(
      composeTrigger(
        [t(VALID, "1"), t(READY, "0"), { probes: [STATE], op: "==", radix: "H", value: "A" }],
        "and",
        SIMPLE_BUILD,
      ),
    ).toMatchObject({
      triggerMode: "value_match",
      triggerValue: "0xA08",
      triggerMask: "0xF18",
      useSequencer: false,
    });
  });

  it("AND rejects contradictions on the same bits", () => {
    expect(() => composeTrigger([t(VALID, "1"), t(VALID, "0")], "and", SIMPLE_BUILD)).toThrow(
      /conflicting/,
    );
  });

  it("all-X rows are refused", () => {
    expect(() => composeTrigger([t(STATE, "XXXX")], "and", SIMPLE_BUILD)).toThrow(/matches always/);
  });

  it("Global OR of B (either-edge) rows merges into one edge_detect", () => {
    expect(
      composeTrigger([t(VALID, "B"), t(READY, "B")], "or", SIMPLE_BUILD),
    ).toMatchObject({
      triggerMode: "edge_detect",
      triggerMask: "0x18",
      useSequencer: false,
    });
  });

  it("a single R row becomes a one-stage sequence on sequencer builds", () => {
    const r = composeTrigger([t(VALID, "R")], "and", SEQ_BUILD);
    expect(r.useSequencer).toBe(true);
    expect(JSON.parse(r.sequenceJson ?? "")).toEqual([
      { cmp_mode_a: 6, value_a: "0x0", mask_a: "0x8", is_final: true },
    ]);
  });

  it("== rows AND one edge use both comparators with combine=AND", () => {
    const r = composeTrigger(
      [{ probes: [STATE], op: "==", radix: "H", value: "3" }, t(VALID, "R")],
      "and",
      SEQ_BUILD,
    );
    expect(JSON.parse(r.sequenceJson ?? "")).toEqual([
      {
        cmp_mode_a: 0,
        value_a: "0x300",
        mask_a: "0xF00",
        cmp_mode_b: 6,
        value_b: "0x0",
        mask_b: "0x8",
        combine: 2,
        is_final: true,
      },
    ]);
  });

  it("!= takes its own comparator (NEQ mode)", () => {
    const r = composeTrigger(
      [{ probes: [STATE], op: "!=", radix: "H", value: "0" }],
      "and",
      SEQ_BUILD,
    );
    expect(JSON.parse(r.sequenceJson ?? "")[0].cmp_mode_a).toBe(1);
  });

  it("Global OR of two patterns uses both comparators with combine=OR", () => {
    const r = composeTrigger(
      [t(VALID, "1"), { probes: [STATE], op: "==", radix: "H", value: "A" }],
      "or",
      SEQ_BUILD,
    );
    const stage = JSON.parse(r.sequenceJson ?? "")[0];
    expect(stage.combine).toBe(3);
    expect(stage.cmp_mode_a).toBe(0);
    expect(stage.cmp_mode_b).toBe(0);
  });

  it("AND of two edges is impossible in hardware", () => {
    expect(() => composeTrigger([t(VALID, "R"), t(READY, "R")], "and", SEQ_BUILD)).toThrow(
      /at most one edge/,
    );
  });

  it("more rows than comparators is rejected", () => {
    expect(() =>
      composeTrigger(
        [t(VALID, "1"), t(READY, "1"), { probes: [STATE], op: "==", radix: "H", value: "1" }],
        "or",
        SEQ_BUILD,
      ),
    ).toThrow(/two comparators/);
  });

  it("sequencer combinations are gated on TRIG_STAGES and DUAL_COMPARE", () => {
    expect(() => composeTrigger([t(VALID, "R")], "and", SIMPLE_BUILD)).toThrow(/TRIG_STAGES/);
    expect(() =>
      composeTrigger(
        [t(VALID, "1"), { probes: [STATE], op: "==", radix: "H", value: "A" }],
        "or",
        ident({ trig_stages: 4, has_dual_compare: false }),
      ),
    ).toThrow(/DUAL_COMPARE/);
  });

  it("rejects fields beyond the 32-bit comparator", () => {
    expect(triggerable(HIGH_FIELD)).toBe(false);
    expect(() =>
      composeTrigger([{ probes: [HIGH_FIELD], op: "==", radix: "H", value: "0" }], "and", SIMPLE_BUILD),
    ).toThrow(/low 32 bits/);
  });

  it("describes the table readably", () => {
    expect(
      describeTerms(
        [t(VALID, "R"), { probes: [STATE], op: "==", radix: "H", value: "A" }],
        "or",
      ),
    ).toBe("valid == R OR state == 0xA");
  });

  // --- probe grouping (concatenated fields) ---------------------------------

  it("groups probes into one concatenated == comparator, split onto each lsb", () => {
    // {addr_hi@16, addr_lo@0} == 0x1234 → addr_hi=0x12, addr_lo=0x34
    expect(composeTrigger([g([ADDR_HI, ADDR_LO], "1234")], "and", SIMPLE_BUILD)).toMatchObject({
      triggerMode: "value_match",
      triggerValue: "0x120034",
      triggerMask: "0xFF00FF",
      useSequencer: false,
    });
  });

  it("group X don't-cares drop whole probes out of the mask", () => {
    // Only the high byte is compared; addr_lo is all don't-care.
    expect(composeTrigger([g([ADDR_HI, ADDR_LO], "12XX")], "and", SIMPLE_BUILD)).toMatchObject({
      triggerValue: "0x120000",
      triggerMask: "0xFF0000",
    });
  });

  it("a group != is a single NEQ comparator over all member bits", () => {
    const r = composeTrigger([g([ADDR_HI, ADDR_LO], "1234", "!=")], "and", SEQ_BUILD);
    const stage = JSON.parse(r.sequenceJson ?? "")[0];
    expect(stage.cmp_mode_a).toBe(1);
    expect(stage.value_a).toBe("0x120034");
    expect(stage.mask_a).toBe("0xFF00FF");
  });

  it("rejects overlapping probes in a group", () => {
    const dup: ProbeSpec = { name: "dup", width: 8, lsb: 0 }; // same bits as addr_lo
    expect(() => composeTrigger([g([dup, ADDR_LO], "1234")], "and", SIMPLE_BUILD)).toThrow(
      /overlap/,
    );
  });

  it("rejects a group whose member sits above the 32-bit comparator", () => {
    expect(() =>
      composeTrigger([g([HIGH_FIELD, ADDR_LO], "0")], "and", SIMPLE_BUILD),
    ).toThrow(/low 32 bits/);
  });

  it("groupTerms concatenates MSB-first and resets the value", () => {
    const grouped = groupTerms([t(STATE, "3", "==", "H"), t(VALID, "1", "==", "B")]);
    expect(grouped.probes).toEqual([STATE, VALID]);
    expect(grouped.op).toBe("==");
    expect(grouped.radix).toBe("H"); // carried from the first row
    expect(grouped.value).toBe("XX"); // width 5 → 2 hex don't-care nibbles
  });

  it("describes a group readably", () => {
    expect(describeTerms([g([ADDR_HI, ADDR_LO], "1234")], "and")).toBe(
      "{addr_hi, addr_lo} == 0x1234",
    );
  });
});

describe("defaults and capabilities", () => {
  it("termWidth sums member widths", () => {
    expect(termWidth(g([ADDR_HI, ADDR_LO], "0"))).toBe(16);
    expect(termWidth(t(VALID, "1"))).toBe(1);
  });

  it("defaultTerm: 1-bit gets binary '1', fields get all-X hex", () => {
    expect(defaultTerm(VALID)).toEqual({ probes: [VALID], op: "==", radix: "B", value: "1" });
    expect(defaultTerm(STATE)).toEqual({ probes: [STATE], op: "==", radix: "H", value: "X" });
  });

  it("hasDirectionalEdges requires TRIG_STAGES >= 2 and edge compare modes", () => {
    expect(hasDirectionalEdges(ident({ trig_stages: 1 }))).toBe(false);
    expect(hasDirectionalEdges(ident({ trig_stages: 2 }))).toBe(true); // caps unknown
    expect(hasDirectionalEdges(ident({ trig_stages: 4, compare_modes: [0, 1] }))).toBe(false);
    expect(hasDirectionalEdges(null)).toBe(false);
  });
});
