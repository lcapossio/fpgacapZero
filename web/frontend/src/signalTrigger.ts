// Click-to-trigger glue: turn "trigger on this signal's rising edge / level /
// value" into the shared ELA trigger config. Bit positions come from the
// probe definitions; nothing here hardcodes a layout.
//
// Hardware mapping (see docs/05):
// - high/low/equals -> simple value_match on the field's bits
// - change          -> simple edge_detect (masked bits change, any direction)
// - rising/falling  -> a single-stage trigger sequence (compare mode 6/7:
//   masked bits go all-zero -> non-zero / the reverse). Directional edges
//   only exist in TRIG_STAGES >= 2 builds — TRIG_STAGES=1 has no sequencer,
//   and the analyzer would silently ignore the stage writes.

import { toHexParam } from "./api";
import type { Identity, ProbeSpec } from "./api";
import type { ElaConfig } from "./session";

export type SignalCondition = "rising" | "falling" | "high" | "low" | "change" | "equals";

// The trigger comparators are driven through 32-bit registers, so only the
// low 32 probe bits are reachable (fields above that can't be triggered on).
export const COMPARATOR_BITS = 32;

const CMP_RISING = 6;
const CMP_FALLING = 7;

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

/** ELA-config patch that makes the trigger fire on `cond` for this signal.
 *  `equalsText` (decimal or 0x-hex) is required for the "equals" condition. */
export function signalTrigger(
  p: ProbeSpec,
  cond: SignalCondition,
  equalsText?: string,
): Partial<ElaConfig> {
  if (!triggerable(p)) {
    throw new Error(
      `${p.name} lies above bit ${COMPARATOR_BITS - 1} — the trigger comparator ` +
        `reaches the low ${COMPARATOR_BITS} bits only`,
    );
  }
  const mask = fieldMask(p);
  const m = hex(mask);
  switch (cond) {
    case "high":
      return simple("value_match", m, m);
    case "low":
      return simple("value_match", "0x0", m);
    case "change":
      return simple("edge_detect", "0x0", m);
    case "equals": {
      const v = BigInt(toHexParam(equalsText ?? "", `${p.name} value`));
      if (v >= 1n << BigInt(p.width)) {
        throw new Error(`value exceeds ${p.name}'s ${p.width} bits`);
      }
      return simple("value_match", hex(v << BigInt(p.lsb)), m);
    }
    case "rising":
    case "falling":
      // One final sequencer stage; the sequencer path drives the trigger, so
      // the legacy value/mask pair is parked at never-matters 0/0.
      return {
        triggerMode: "value_match",
        triggerValue: "0x0",
        triggerMask: "0x0",
        useSequencer: true,
        sequenceJson: JSON.stringify([
          {
            cmp_mode_a: cond === "rising" ? CMP_RISING : CMP_FALLING,
            value_a: "0x0",
            mask_a: m,
            is_final: true,
          },
        ]),
      };
  }
}

/** Human phrasing for the feedback line ("trigger: rising edge of valid"). */
export function describeCondition(p: ProbeSpec, cond: SignalCondition, equalsText?: string): string {
  switch (cond) {
    case "rising":
      return `rising edge of ${p.name}`;
    case "falling":
      return `falling edge of ${p.name}`;
    case "high":
      return `${p.name} == 1`;
    case "low":
      return `${p.name} == 0`;
    case "change":
      return `${p.name} changes`;
    case "equals":
      return `${p.name} == ${(equalsText ?? "").trim()}`;
  }
}

function simple(mode: string, value: string, mask: string): Partial<ElaConfig> {
  return {
    triggerMode: mode,
    triggerValue: value,
    triggerMask: mask,
    useSequencer: false,
  };
}
