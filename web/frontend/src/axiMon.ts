// AXI monitor glue (axi_mon_probe): typed detection result plus the pure
// helpers the AXI Mon panel uses to turn the server's probe map into ELA
// probe text and trigger value/mask pairs. Field bit positions always come
// from the probe map the server returned — nothing here hardcodes the layout.

import { toHexParam } from "./api";
import type { ProbeSpec } from "./api";

/** Detection result of `axi_mon_probe` when a monitor is present. */
export interface AxiMonInfo {
  /** BSCAN chain the monitor lives on — may differ from the session's;
   *  clients switch to it transparently before using the monitor. */
  chain: number;
  proto: string;
  addr_w: number;
  data_w: number;
  decode: boolean;
  sample_width: number;
  probes: ProbeSpec[];
}

/** Render probe specs as the `name:width:lsb` lines the ELA tab edits. */
export function probesToText(probes: ProbeSpec[]): string {
  return probes.map((p) => `${p.name}:${p.width}:${p.lsb}`).join("\n");
}

/** The decode layer's event bits: single-bit probes in the low byte
 *  (aw_hs .. any_err), in bit order. Empty on DECODE_EN=0 builds. */
export function axiEventProbes(info: AxiMonInfo): ProbeSpec[] {
  if (!info.decode) return [];
  return info.probes
    .filter((p) => p.width === 1 && p.lsb < 8)
    .sort((a, b) => a.lsb - b.lsb);
}

/** Trigger value/mask (hex strings) that fires when ALL named events assert
 *  in the same cycle. Names must be event probes from {@link axiEventProbes}. */
export function axiEventTrigger(
  info: AxiMonInfo,
  names: string[],
): { value: string; mask: string } {
  const events = axiEventProbes(info);
  let mask = 0n;
  for (const name of names) {
    const p = events.find((e) => e.name === name);
    if (!p) throw new Error(`unknown AXI event '${name}'`);
    mask |= 1n << BigInt(p.lsb);
  }
  if (mask === 0n) throw new Error("select at least one event");
  const hex = "0x" + mask.toString(16).toUpperCase();
  return { value: hex, mask: hex };
}

/** Trigger value/mask matching a write address (`awaddr`). Only reachable by
 *  the ELA's 32-bit comparator when awaddr sits in the low 32 bits, i.e.
 *  DECODE_EN=0 builds — mirrors AxiMonitor.write_addr_capture_config. */
export function axiWriteAddrTrigger(
  info: AxiMonInfo,
  addrText: string,
): { value: string; mask: string } {
  const aw = info.probes.find((p) => p.name === "awaddr");
  if (!aw || aw.lsb + aw.width > 32) {
    throw new Error(
      "write-address triggering needs awaddr in the low 32 bits (DECODE_EN=0 build) — use event triggers instead",
    );
  }
  const addr = BigInt(toHexParam(addrText, "write address"));
  const fieldMask = (1n << BigInt(aw.width)) - 1n;
  if (addr > fieldMask) {
    throw new Error(`write address exceeds awaddr's ${aw.width} bits`);
  }
  const mask = fieldMask << BigInt(aw.lsb);
  const value = (addr << BigInt(aw.lsb)) & mask;
  return {
    value: "0x" + value.toString(16).toUpperCase(),
    mask: "0x" + mask.toString(16).toUpperCase(),
  };
}
