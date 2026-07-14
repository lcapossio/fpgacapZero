// Click-to-trigger glue: turn a list of per-signal conditions ("valid rises",
// "state == 0xA") combined with AND/OR into the shared ELA trigger config.
// Bit positions come from the probe definitions; nothing here hardcodes a
// layout.
//
// Hardware mapping (see docs/05). The ELA offers:
// - one simple comparator: value_match ((probe&mask)==(value&mask)) or
//   edge_detect (any masked bit changes) — available in every build;
// - a trigger sequencer stage with two comparators A/B (modes EQ/RISING/
//   FALLING/CHANGED …) and an AND/OR combine — TRIG_STAGES >= 2 builds,
//   comparator B additionally needs DUAL_COMPARE.
//
// So a trigger composes into at most two comparator "slots":
// - AND: all level/equality terms merge into one EQ slot (they're just bits
//   of one pattern); at most one edge-ish term takes the second slot.
//   Multiple edge terms can't AND — the hardware has no per-bit edge AND.
// - OR: every level/equality term needs its own slot (merging masks would
//   AND them); all "changes" terms merge into one CHANGED slot (any-of is
//   exactly what a merged mask means); rising/falling take a slot each.

import { toHexParam } from "./api";
import type { Identity, ProbeSpec } from "./api";
import type { ElaConfig } from "./session";

export type SignalCondition = "rising" | "falling" | "high" | "low" | "change" | "equals";
export type Combine = "and" | "or";

export interface TriggerTerm {
  probe: ProbeSpec;
  cond: SignalCondition;
  /** Decimal or 0x-hex; only for cond === "equals". */
  value?: string;
}

// The trigger comparators are driven through 32-bit registers, so only the
// low 32 probe bits are reachable (fields above that can't be triggered on).
export const COMPARATOR_BITS = 32;

const CMP_EQ = 0;
const CMP_RISING = 6;
const CMP_FALLING = 7;
const CMP_CHANGED = 8;
const COMBINE_AND = 2;
const COMBINE_OR = 3;

/** One comparator's worth of condition. */
interface Slot {
  mode: number;
  value: bigint;
  mask: bigint;
}

function hex(v: bigint): string {
  return "0x" + v.toString(16).toUpperCase();
}

function fieldMask(p: ProbeSpec): bigint {
  return ((1n << BigInt(p.width)) - 1n) << BigInt(p.lsb);
}

/** Can this probe be used for click-to-trigger at all? */
export function triggerable(p: ProbeSpec): boolean {
  return p.width > 0 && p.lsb + p.width <= COMPARATOR_BITS;
}

/** Do directional edges (rising/falling) exist in this bitstream? */
export function hasDirectionalEdges(id: Identity | null): boolean {
  const stages = id?.trig_stages ?? 0;
  const modes = id?.compare_modes;
  // Older servers omit compare_modes; TRIG_STAGES >= 2 alone implies the
  // baseline EQ/NEQ/RISING/FALLING/CHANGED set unless caps say otherwise.
  const edgeModes = modes ? modes.includes(CMP_RISING) && modes.includes(CMP_FALLING) : true;
  return stages >= 2 && edgeModes;
}

/** Human phrasing of one term ("rising edge of valid", "state == 0xA"). */
export function describeTerm(t: TriggerTerm): string {
  switch (t.cond) {
    case "rising":
      return `${t.probe.name} ↑`;
    case "falling":
      return `${t.probe.name} ↓`;
    case "high":
      return `${t.probe.name} == 1`;
    case "low":
      return `${t.probe.name} == 0`;
    case "change":
      return `${t.probe.name} changes`;
    case "equals":
      return `${t.probe.name} == ${(t.value ?? "").trim()}`;
  }
}

export function describeTerms(terms: TriggerTerm[], combine: Combine): string {
  return terms.map(describeTerm).join(combine === "and" ? " AND " : " OR ");
}

/** Value/mask pair for a level or equality term. */
function eqSlotOf(t: TriggerTerm): Slot {
  const mask = fieldMask(t.probe);
  let v: bigint;
  if (t.cond === "high") v = 1n;
  else if (t.cond === "low") v = 0n;
  else {
    v = BigInt(toHexParam(t.value ?? "", `${t.probe.name} value`));
    if (v >= 1n << BigInt(t.probe.width)) {
      throw new Error(`value exceeds ${t.probe.name}'s ${t.probe.width} bits`);
    }
  }
  return { mode: CMP_EQ, value: v << BigInt(t.probe.lsb), mask };
}

function edgeSlotOf(t: TriggerTerm): Slot {
  const mode =
    t.cond === "rising" ? CMP_RISING : t.cond === "falling" ? CMP_FALLING : CMP_CHANGED;
  return { mode, value: 0n, mask: fieldMask(t.probe) };
}

/** Compose the terms into an ELA-config patch, or throw a message that says
 *  which hardware capability is missing. */
export function composeTrigger(
  terms: TriggerTerm[],
  combine: Combine,
  id: Identity | null,
): Partial<ElaConfig> {
  if (terms.length === 0) throw new Error("no trigger terms");
  for (const t of terms) {
    if (!triggerable(t.probe)) {
      throw new Error(
        `${t.probe.name} lies above bit ${COMPARATOR_BITS - 1} — the trigger ` +
          `comparator reaches the low ${COMPARATOR_BITS} bits only`,
      );
    }
  }

  const eqTerms = terms.filter((t) => t.cond === "high" || t.cond === "low" || t.cond === "equals");
  const changeTerms = terms.filter((t) => t.cond === "change");
  const edgeTerms = terms.filter((t) => t.cond === "rising" || t.cond === "falling");

  let slots: Slot[];
  if (combine === "and") {
    if (changeTerms.length + edgeTerms.length > 1) {
      throw new Error(
        "the hardware can AND at most one edge/change condition with the level terms " +
          "(edges on several signals can't be required in the same cycle)",
      );
    }
    slots = [];
    if (eqTerms.length) {
      // One pattern: merge bits, rejecting contradictions (e.g. x==1 AND x==0).
      const merged = eqTerms.map(eqSlotOf).reduce((a, b) => {
        const overlap = a.mask & b.mask;
        if ((a.value & overlap) !== (b.value & overlap)) {
          throw new Error("conflicting level/value conditions on the same bits");
        }
        return { mode: CMP_EQ, value: a.value | b.value, mask: a.mask | b.mask };
      });
      slots.push(merged);
    }
    const edgeish = [...changeTerms, ...edgeTerms];
    if (edgeish.length) slots.push(edgeSlotOf(edgeish[0]));
  } else {
    // OR: each level/value term is its own pattern; changes merge into one.
    slots = eqTerms.map(eqSlotOf);
    if (changeTerms.length) {
      const mask = changeTerms.map((t) => fieldMask(t.probe)).reduce((a, b) => a | b);
      slots.push({ mode: CMP_CHANGED, value: 0n, mask });
    }
    slots.push(...edgeTerms.map(edgeSlotOf));
  }

  if (slots.length === 1 && (slots[0].mode === CMP_EQ || slots[0].mode === CMP_CHANGED)) {
    // Fits the simple trigger — works in every build.
    return {
      triggerMode: slots[0].mode === CMP_EQ ? "value_match" : "edge_detect",
      triggerValue: hex(slots[0].value),
      triggerMask: hex(slots[0].mask),
      useSequencer: false,
    };
  }

  // Anything else runs on a single sequencer stage.
  const stages = id?.trig_stages ?? 0;
  if (stages < 2) {
    throw new Error(
      `this combination needs a TRIG_STAGES ≥ 2 bitstream (this build: ${stages || "?"}) — ` +
        "simplify the trigger or rebuild the core",
    );
  }
  if (slots.length > 2) {
    throw new Error(
      "too many OR branches — the hardware has two comparators, so at most two " +
        "patterns/edges (all 'changes' terms together count as one)",
    );
  }
  if (slots.length === 2 && id && id.has_dual_compare === false) {
    throw new Error("combining two conditions needs a DUAL_COMPARE=1 build");
  }
  const caps = id?.compare_modes;
  for (const s of slots) {
    if (caps && !caps.includes(s.mode)) {
      throw new Error(`compare mode ${s.mode} not available in this build`);
    }
  }

  const stage: Record<string, unknown> = {
    cmp_mode_a: slots[0].mode,
    value_a: hex(slots[0].value),
    mask_a: hex(slots[0].mask),
    is_final: true,
  };
  if (slots.length === 2) {
    stage.cmp_mode_b = slots[1].mode;
    stage.value_b = hex(slots[1].value);
    stage.mask_b = hex(slots[1].mask);
    stage.combine = combine === "and" ? COMBINE_AND : COMBINE_OR;
  }
  return {
    // The sequencer path drives the trigger; the legacy value/mask pair is
    // parked at never-matters 0/0.
    triggerMode: "value_match",
    triggerValue: "0x0",
    triggerMask: "0x0",
    useSequencer: true,
    sequenceJson: JSON.stringify([stage]),
  };
}
