import { describe, expect, it } from "vitest";
import type { Identity, ProbeSpec } from "./api";
import type { TriggerTerm } from "./signalTrigger";
import {
  composeTrigger,
  describeTerms,
  hasDirectionalEdges,
  triggerable,
} from "./signalTrigger";

const VALID: ProbeSpec = { name: "valid", width: 1, lsb: 3 };
const READY: ProbeSpec = { name: "ready", width: 1, lsb: 4 };
const STATE: ProbeSpec = { name: "state", width: 4, lsb: 8 };
const HIGH_FIELD: ProbeSpec = { name: "wdata", width: 32, lsb: 66 };

function t(probe: ProbeSpec, cond: TriggerTerm["cond"], value?: string): TriggerTerm {
  return { probe, cond, value };
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

const SEQ_BUILD = ident({ trig_stages: 4, has_dual_compare: true, compare_modes: [0, 1, 6, 7, 8] });
const SIMPLE_BUILD = ident({ trig_stages: 1 });

describe("composeTrigger", () => {
  it("a single level term is a plain value_match", () => {
    expect(composeTrigger([t(VALID, "high")], "and", SIMPLE_BUILD)).toMatchObject({
      triggerMode: "value_match",
      triggerValue: "0x8",
      triggerMask: "0x8",
      useSequencer: false,
    });
  });

  it("AND merges levels and field values into one pattern", () => {
    expect(
      composeTrigger([t(VALID, "high"), t(READY, "low"), t(STATE, "equals", "0xA")], "and", SIMPLE_BUILD),
    ).toMatchObject({
      triggerMode: "value_match",
      triggerValue: "0xA08",
      triggerMask: "0xF18",
      useSequencer: false,
    });
  });

  it("AND rejects contradictions on the same bits", () => {
    expect(() => composeTrigger([t(VALID, "high"), t(VALID, "low")], "and", SIMPLE_BUILD)).toThrow(
      /conflicting/,
    );
  });

  it("equals values are range-checked", () => {
    expect(() => composeTrigger([t(STATE, "equals", "0x10")], "and", SIMPLE_BUILD)).toThrow(
      /exceeds/,
    );
  });

  it("OR of change terms merges into one edge_detect", () => {
    expect(
      composeTrigger([t(VALID, "change"), t(STATE, "change")], "or", SIMPLE_BUILD),
    ).toMatchObject({
      triggerMode: "edge_detect",
      triggerMask: "0xF08",
      useSequencer: false,
    });
  });

  it("a single rising term becomes a one-stage sequence on sequencer builds", () => {
    const r = composeTrigger([t(VALID, "rising")], "and", SEQ_BUILD);
    expect(r.useSequencer).toBe(true);
    expect(JSON.parse(r.sequenceJson ?? "")).toEqual([
      { cmp_mode_a: 6, value_a: "0x0", mask_a: "0x8", is_final: true },
    ]);
  });

  it("levels AND one edge use both comparators with combine=AND", () => {
    const r = composeTrigger([t(STATE, "equals", "0x3"), t(VALID, "rising")], "and", SEQ_BUILD);
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

  it("OR of two patterns uses both comparators with combine=OR", () => {
    const r = composeTrigger([t(VALID, "high"), t(STATE, "equals", "0xA")], "or", SEQ_BUILD);
    const stage = JSON.parse(r.sequenceJson ?? "")[0];
    expect(stage.combine).toBe(3);
    expect(stage.cmp_mode_a).toBe(0);
    expect(stage.cmp_mode_b).toBe(0);
  });

  it("AND of two edges is impossible in hardware", () => {
    expect(() =>
      composeTrigger([t(VALID, "rising"), t(READY, "rising")], "and", SEQ_BUILD),
    ).toThrow(/at most one edge/);
  });

  it("OR beyond two comparator slots is rejected", () => {
    expect(() =>
      composeTrigger(
        [t(VALID, "high"), t(READY, "high"), t(STATE, "equals", "0x1")],
        "or",
        SEQ_BUILD,
      ),
    ).toThrow(/two comparators/);
  });

  it("sequencer combinations are gated on TRIG_STAGES and DUAL_COMPARE", () => {
    expect(() => composeTrigger([t(VALID, "rising")], "and", SIMPLE_BUILD)).toThrow(
      /TRIG_STAGES/,
    );
    expect(() =>
      composeTrigger(
        [t(VALID, "high"), t(STATE, "equals", "0xA")],
        "or",
        ident({ trig_stages: 4, has_dual_compare: false }),
      ),
    ).toThrow(/DUAL_COMPARE/);
  });

  it("rejects fields beyond the 32-bit comparator", () => {
    expect(triggerable(HIGH_FIELD)).toBe(false);
    expect(() => composeTrigger([t(HIGH_FIELD, "change")], "and", SIMPLE_BUILD)).toThrow(
      /low 32 bits/,
    );
  });

  it("describes the composition readably", () => {
    expect(
      describeTerms([t(VALID, "rising"), t(STATE, "equals", "0xA")], "or"),
    ).toBe("valid ↑ OR state == 0xA");
  });
});

describe("hasDirectionalEdges", () => {
  it("requires TRIG_STAGES >= 2 and edge compare modes", () => {
    expect(hasDirectionalEdges(ident({ trig_stages: 1 }))).toBe(false);
    expect(hasDirectionalEdges(ident({ trig_stages: 2 }))).toBe(true); // caps unknown
    expect(hasDirectionalEdges(ident({ trig_stages: 4, compare_modes: [0, 1] }))).toBe(false);
    expect(hasDirectionalEdges(null)).toBe(false);
  });
});
