import { describe, expect, it } from "vitest";
import type { Identity, ProbeSpec } from "./api";
import { hasDirectionalEdges, signalTrigger, triggerable } from "./signalTrigger";

const BIT: ProbeSpec = { name: "valid", width: 1, lsb: 3 };
const FIELD: ProbeSpec = { name: "state", width: 4, lsb: 8 };
const HIGH_FIELD: ProbeSpec = { name: "wdata", width: 32, lsb: 66 };

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

describe("signalTrigger", () => {
  it("high/low set value_match on the signal's bit", () => {
    expect(signalTrigger(BIT, "high")).toMatchObject({
      triggerMode: "value_match",
      triggerValue: "0x8",
      triggerMask: "0x8",
      useSequencer: false,
    });
    expect(signalTrigger(BIT, "low")).toMatchObject({
      triggerValue: "0x0",
      triggerMask: "0x8",
    });
  });

  it("change uses edge_detect with the field mask", () => {
    expect(signalTrigger(FIELD, "change")).toMatchObject({
      triggerMode: "edge_detect",
      triggerMask: "0xF00",
    });
  });

  it("equals shifts the value into the field, rejecting overflow", () => {
    expect(signalTrigger(FIELD, "equals", "0xA")).toMatchObject({
      triggerMode: "value_match",
      triggerValue: "0xA00",
      triggerMask: "0xF00",
    });
    expect(() => signalTrigger(FIELD, "equals", "0x10")).toThrow(/exceeds/);
    expect(() => signalTrigger(FIELD, "equals", "zz")).toThrow(/invalid/);
  });

  it("rising/falling emit a single final sequencer stage", () => {
    const r = signalTrigger(BIT, "rising");
    expect(r.useSequencer).toBe(true);
    expect(JSON.parse(r.sequenceJson ?? "")).toEqual([
      { cmp_mode_a: 6, value_a: "0x0", mask_a: "0x8", is_final: true },
    ]);
    const f = signalTrigger(BIT, "falling");
    expect(JSON.parse(f.sequenceJson ?? "")[0].cmp_mode_a).toBe(7);
  });

  it("rejects fields beyond the 32-bit comparator", () => {
    expect(triggerable(HIGH_FIELD)).toBe(false);
    expect(() => signalTrigger(HIGH_FIELD, "change")).toThrow(/low 32 bits/);
  });

  it("directional edges require TRIG_STAGES >= 2 and edge compare modes", () => {
    expect(hasDirectionalEdges(ident({ trig_stages: 1 }))).toBe(false);
    expect(hasDirectionalEdges(ident({ trig_stages: 2 }))).toBe(true); // caps unknown
    expect(
      hasDirectionalEdges(ident({ trig_stages: 4, compare_modes: [0, 1, 6, 7, 8] })),
    ).toBe(true);
    expect(hasDirectionalEdges(ident({ trig_stages: 4, compare_modes: [0, 1] }))).toBe(false);
    expect(hasDirectionalEdges(null)).toBe(false);
  });
});
