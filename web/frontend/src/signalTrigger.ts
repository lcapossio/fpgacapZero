// ILA-style trigger model: a table of comparison rows — operator, radix,
// value — combined with a global AND/OR condition (mirroring Vivado's ILA
// Trigger Setup). A row targets one probe, or a *group* of probes concatenated
// MSB-first into one wider field so a single value spans several signals (e.g.
// {addr_hi, addr_lo} == 0x1234). Values support per-bit don't-cares (X) in
// binary and hex radix, and edge tokens (R/F/B) for single-bit rows in binary
// radix. Everything compiles down to the shared ELA trigger config; bit
// positions come from the probe definitions — nothing here hardcodes a layout.
//
// Hardware mapping (see docs/05). The ELA offers:
// - one simple comparator: value_match ((probe&mask)==(value&mask)) or
//   edge_detect (any masked bit changes) — available in every build;
// - a trigger sequencer stage with two comparators A/B (EQ/NEQ/RISING/
//   FALLING/CHANGED) and an AND/OR combine — TRIG_STAGES >= 2 builds,
//   comparator B additionally needs DUAL_COMPARE.
//
// So a trigger composes into at most two comparator "slots":
// - AND: all `==` terms merge into one EQ slot (X'd bits just drop out of
//   the mask); at most one edge (R/F/B) can join via the second slot, and
//   any `!=` needs a slot of its own. Edges on several probes can't be
//   required in the same cycle — the hardware has no per-bit edge AND.
// - OR: every `==`/`!=` term needs its own slot (merging masks would AND
//   them); all B (either-edge) terms merge into one CHANGED slot; R/F take
//   a slot each.

import type { Identity, ProbeSpec } from "./api";
import type { ElaConfig } from "./session";

export type TriggerOp = "==" | "!=";
/** ILA radix letters: B(inary), H(ex), U(nsigned decimal). */
export type TriggerRadix = "B" | "H" | "U";
export type Combine = "and" | "or";

/** One row of the trigger-setup table. `probes` holds one probe for a plain
 *  row, or several (MSB-first) concatenated into a single field for a group. */
export interface TriggerTerm {
  probes: ProbeSpec[];
  op: TriggerOp;
  radix: TriggerRadix;
  value: string;
}

/** Total bit width of a row's field (sum of its probes' widths). */
export function termWidth(t: TriggerTerm): number {
  return t.probes.reduce((sum, p) => sum + p.width, 0);
}

/** Display name: the probe's name, or `{a, b, …}` for a group. */
export function termName(t: TriggerTerm): string {
  return t.probes.length === 1
    ? t.probes[0].name
    : `{${t.probes.map((p) => p.name).join(", ")}}`;
}

/** A single-bit probe row — the only kind that accepts R/F/B edge tokens. */
function isSingleBit(t: TriggerTerm): boolean {
  return t.probes.length === 1 && t.probes[0].width === 1;
}

/** All-don't-cares value string for a field of the given width and radix. */
export function defaultValue(width: number, radix: TriggerRadix): string {
  if (radix === "U") return "0";
  if (radix === "B") return "X".repeat(width);
  return "X".repeat(Math.ceil(width / 4));
}

// The trigger comparators are driven through 32-bit registers, so only the
// low 32 probe bits are reachable (fields above that can't be triggered on).
export const COMPARATOR_BITS = 32;

const CMP_EQ = 0;
const CMP_NEQ = 1;
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
  /** `==` slots merge under AND; everything else stays its own slot. */
  mergeableEq: boolean;
}

function hex(v: bigint): string {
  return "0x" + v.toString(16).toUpperCase();
}

function fieldMask(p: ProbeSpec): bigint {
  return ((1n << BigInt(p.width)) - 1n) << BigInt(p.lsb);
}

/** Can this probe be used in the trigger table at all? */
export function triggerable(p: ProbeSpec): boolean {
  return p.width > 0 && p.lsb + p.width <= COMPARATOR_BITS;
}

/** Do directional edges (R/F) exist in this bitstream? */
export function hasDirectionalEdges(id: Identity | null): boolean {
  const stages = id?.trig_stages ?? 0;
  const modes = id?.compare_modes;
  // Older servers omit compare_modes; TRIG_STAGES >= 2 alone implies the
  // baseline EQ/NEQ/RISING/FALLING/CHANGED set unless caps say otherwise.
  const edgeModes = modes ? modes.includes(CMP_RISING) && modes.includes(CMP_FALLING) : true;
  return stages >= 2 && edgeModes;
}

/** Sensible default row for a probe, ILA-style. */
export function defaultTerm(p: ProbeSpec): TriggerTerm {
  return p.width === 1
    ? { probes: [p], op: "==", radix: "B", value: "1" }
    : { probes: [p], op: "==", radix: "H", value: "X".repeat(Math.ceil(p.width / 4)) };
}

/** Merge rows into one group (concatenated MSB-first in the given order). The
 *  op/radix carry over from the first row; the value resets to all-don't-cares
 *  since the field width changed. */
export function groupTerms(rows: TriggerTerm[]): TriggerTerm {
  const probes = rows.flatMap((r) => r.probes);
  const { op, radix } = rows[0];
  return { probes, op, radix, value: defaultValue(probes.reduce((s, p) => s + p.width, 0), radix) };
}

/** Parsed value: cared bits (mask, relative to bit 0 of the field) and their
 *  levels, or an edge kind for single-bit R/F/B. */
interface ParsedValue {
  edge?: "R" | "F" | "B";
  value: bigint;
  mask: bigint; // which field bits are compared (X's drop out)
}

/** Parse a term's value text per its radix (throws with a user-facing message).
 *  For a group the value spans the whole concatenated field (bit 0 = LSB of the
 *  last probe); `slotOf` splits it back onto each probe. */
export function parseTermValue(t: TriggerTerm): ParsedValue {
  const width = termWidth(t);
  const w = BigInt(width);
  const full = (1n << w) - 1n;
  const raw = t.value.trim().toUpperCase().replace(/_/g, "");
  const name = termName(t);
  if (!raw) throw new Error(`${name}: empty value`);

  if (t.radix === "B") {
    if (isSingleBit(t) && (raw === "R" || raw === "F" || raw === "B")) {
      if (t.op !== "==") throw new Error(`${name}: edges only combine with ==`);
      return { edge: raw, value: 0n, mask: 1n };
    }
    if (!/^[01X]+$/.test(raw)) {
      throw new Error(
        `${name}: binary value may use 0, 1, X${isSingleBit(t) ? ", R, F, B" : ""}`,
      );
    }
    if (raw.length > width) {
      throw new Error(`${name}: value wider than ${width} bits`);
    }
    let value = 0n;
    let mask = 0n;
    for (const ch of raw) {
      value <<= 1n;
      mask <<= 1n;
      if (ch !== "X") {
        mask |= 1n;
        if (ch === "1") value |= 1n;
      }
    }
    return { value, mask };
  }

  if (t.radix === "H") {
    if (!/^[0-9A-FX]+$/.test(raw)) {
      throw new Error(`${name}: hex value may use 0-9, A-F, X`);
    }
    let value = 0n;
    let mask = 0n;
    for (const ch of raw) {
      value <<= 4n;
      mask <<= 4n;
      if (ch !== "X") {
        mask |= 0xfn;
        value |= BigInt(parseInt(ch, 16));
      }
    }
    if ((value & ~full) !== 0n) {
      throw new Error(`${name}: value exceeds ${width} bits`);
    }
    return { value: value & full, mask: mask & full };
  }

  if (!/^[0-9]+$/.test(raw)) {
    throw new Error(`${name}: unsigned value must be decimal digits`);
  }
  const value = BigInt(raw);
  if (value > full) throw new Error(`${name}: value exceeds ${width} bits`);
  return { value, mask: full };
}

/** Human phrasing of one row ("valid == R", "{addr_hi, addr_lo} == 0x1234"). */
export function describeTerm(t: TriggerTerm): string {
  const prefix = t.radix === "H" ? "0x" : t.radix === "B" ? "0b" : "";
  const v = t.value.trim().toUpperCase();
  const shown = /^[RFB]$/.test(v) && isSingleBit(t) ? v : `${prefix}${v}`;
  return `${termName(t)} ${t.op} ${shown}`;
}

export function describeTerms(terms: TriggerTerm[], combine: Combine): string {
  return terms.map(describeTerm).join(combine === "and" ? " AND " : " OR ");
}

function slotOf(t: TriggerTerm): Slot {
  for (const probe of t.probes) {
    if (!triggerable(probe)) {
      throw new Error(
        `${probe.name} lies above bit ${COMPARATOR_BITS - 1} — the trigger ` +
          `comparator reaches the low ${COMPARATOR_BITS} bits only`,
      );
    }
  }
  // Grouped probes must occupy distinct bits, else OR-ing their slices below
  // would silently corrupt the comparator value/mask.
  let occupied = 0n;
  for (const probe of t.probes) {
    const fm = fieldMask(probe);
    if ((occupied & fm) !== 0n) {
      throw new Error(`${termName(t)}: grouped probes overlap in the sample word`);
    }
    occupied |= fm;
  }

  const p = parseTermValue(t);
  if (p.edge) {
    const mode = p.edge === "R" ? CMP_RISING : p.edge === "F" ? CMP_FALLING : CMP_CHANGED;
    return { mode, value: 0n, mask: fieldMask(t.probes[0]), mergeableEq: false };
  }
  if (p.mask === 0n) {
    throw new Error(`${termName(t)}: all bits are X — the row matches always`);
  }

  // Split the field value (parsed as one wide number, MSB-first) back onto each
  // probe's real bit position. `pos` walks down from the field MSB; each probe
  // takes the next `width` bits and lands at its own `lsb` in the sample word.
  let pos = termWidth(t);
  let value = 0n;
  let mask = 0n;
  for (const probe of t.probes) {
    pos -= probe.width;
    const slice = (1n << BigInt(probe.width)) - 1n;
    value |= ((p.value >> BigInt(pos)) & slice) << BigInt(probe.lsb);
    mask |= ((p.mask >> BigInt(pos)) & slice) << BigInt(probe.lsb);
  }
  return {
    mode: t.op === "==" ? CMP_EQ : CMP_NEQ,
    value,
    mask,
    mergeableEq: t.op === "==",
  };
}

/** Compose the table into an ELA-config patch, or throw a message that says
 *  which hardware capability is missing. */
export function composeTrigger(
  terms: TriggerTerm[],
  combine: Combine,
  id: Identity | null,
): Partial<ElaConfig> {
  if (terms.length === 0) throw new Error("no trigger rows");
  const all = terms.map(slotOf);

  let slots: Slot[];
  if (combine === "and") {
    // One pattern: merge the == rows bitwise, rejecting contradictions.
    const eqs = all.filter((s) => s.mergeableEq);
    const edges = all.filter((s) => s.mode >= CMP_RISING);
    const neqs = all.filter((s) => s.mode === CMP_NEQ);
    if (edges.length > 1) {
      throw new Error(
        "the hardware can AND at most one edge with the other rows " +
          "(edges on several probes can't be required in the same cycle)",
      );
    }
    slots = [];
    if (eqs.length) {
      slots.push(
        eqs.reduce((a, b) => {
          const overlap = a.mask & b.mask;
          if ((a.value & overlap) !== (b.value & overlap)) {
            throw new Error("conflicting == values on the same bits");
          }
          return {
            mode: CMP_EQ,
            value: a.value | b.value,
            mask: a.mask | b.mask,
            mergeableEq: true,
          };
        }),
      );
    }
    slots.push(...neqs, ...edges);
  } else {
    // OR: ==/!= rows keep their own pattern; either-edge (B) rows merge —
    // "any of these bits changed" is exactly a merged CHANGED mask.
    const changed = all.filter((s) => s.mode === CMP_CHANGED);
    slots = all.filter((s) => s.mode !== CMP_CHANGED);
    if (changed.length) {
      slots.push(
        changed.reduce((a, b) => ({
          mode: CMP_CHANGED,
          value: 0n,
          mask: a.mask | b.mask,
          mergeableEq: false,
        })),
      );
    }
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
      "too many rows for the hardware's two comparators — under AND all == rows " +
        "merge into one; != and edge rows each need a comparator of their own",
    );
  }
  if (slots.length === 2 && id && id.has_dual_compare === false) {
    throw new Error("combining two comparators needs a DUAL_COMPARE=1 build");
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
