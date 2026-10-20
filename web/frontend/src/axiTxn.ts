// Decoded AXI4-Lite transactions (`axi` on a capture response, produced by
// fcapz.axi_decode). Types plus the pure helpers the AXI Txn panel uses, kept
// out of the component so they can be tested without rendering.

/** Flags that mean the bus misbehaved. Mirrors FAULT_FLAGS in
 *  host/fcapz/axi_decode.py: only what a finite window can actually prove. */
export const FAULT_FLAGS = ["error_response", "unaligned_address"] as const;

/** Flags that describe the capture window, not the bus. Legal traffic seen
 *  through a keyhole — worth showing, never worth calling a fault. Mirrors
 *  WINDOW_EDGE_FLAGS in host/fcapz/axi_decode.py. */
export const WINDOW_EDGE_FLAGS = [
  "request_not_observed",
  "no_response_in_window",
  "write_missing_address",
  "write_missing_data",
  "pairing_suspect",
] as const;

export interface AxiTransaction {
  index: number;
  kind: "read" | "write";
  addr?: string;
  prot?: number;
  data?: string;
  strb?: string;
  resp?: string;
  cycles?: { addr?: number; data?: number; resp?: number };
  latency?: number;
  stall_cycles?: Record<string, number>;
  flags?: string[];
}

export interface AxiPairing {
  method: string;
  assumes: string;
  pre_window_traffic_observed: string[];
  /** True only when the trace *proved* the assumption false. False is not
   *  proof that it holds. */
  pre_window_traffic_proven?: boolean;
}

export interface AxiSampling {
  decimation: number;
  storage_qualified: boolean;
  contiguous: boolean;
}

export interface AxiDecode {
  protocol: string;
  addr_width: number;
  data_width: number;
  /** False when the capture cannot be read as transactions at all. */
  decoded?: boolean;
  unavailable_reason?: string | null;
  sampling?: AxiSampling;
  transaction_count: number;
  write_count: number;
  read_count: number;
  error_count: number;
  anomaly_count: number;
  flagged_count: number;
  max_latency: number | null;
  pairing: AxiPairing;
  transactions: AxiTransaction[];
}

export type KindFilter = "all" | "read" | "write";

/** True when the transaction carries a flag that means a real fault. */
export function isFault(txn: AxiTransaction): boolean {
  return (txn.flags ?? []).some((f) => (FAULT_FLAGS as readonly string[]).includes(f));
}

/** True when the transaction is clipped by an edge of the capture window. */
export function isWindowEdge(txn: AxiTransaction): boolean {
  return (txn.flags ?? []).some((f) =>
    (WINDOW_EDGE_FLAGS as readonly string[]).includes(f),
  );
}

/** Apply the panel's two filters. Order is the trace order the decoder used. */
export function filterTransactions(
  transactions: AxiTransaction[],
  opts: { kind: KindFilter; onlyAnomalies: boolean },
): AxiTransaction[] {
  return transactions.filter(
    (txn) =>
      (opts.kind === "all" || txn.kind === opts.kind) &&
      (!opts.onlyAnomalies || isFault(txn)),
  );
}

/** Narrow an unknown capture response field to a decode, or undefined.
 *  A capture from a non-AXI probe map simply has no `axi` key. */
export function asAxiDecode(value: unknown): AxiDecode | undefined {
  if (typeof value !== "object" || value === null) return undefined;
  const candidate = value as Partial<AxiDecode>;
  if (!Array.isArray(candidate.transactions)) return undefined;
  if (candidate.protocol !== "axi4lite") return undefined;
  return candidate as AxiDecode;
}

/** Why this capture carries no transactions, or "". Decimation and storage
 *  qualification store only selected cycles, and reassembly needs every one:
 *  a handshake that was never stored cannot be told from one that never
 *  happened, so the decoder refuses rather than reporting wrong addresses. */
export function undecodableReason(decode: AxiDecode): string {
  if (decode.decoded === false) {
    return decode.unavailable_reason ?? "this capture cannot be read as AXI.";
  }
  return "";
}

/** The pairing caveat, always. AXI4-Lite has no transaction IDs, so responses
 *  are matched first-in-first-out; if the window opened mid-transaction every
 *  pairing in that direction sits on the wrong request — and those rows look
 *  entirely ordinary. Returned even when nothing was detected, because a
 *  finite trace cannot prove the assumption holds: only disprove it. */
export function pairingWarning(decode: AxiDecode): string {
  const seen = decode.pairing?.pre_window_traffic_observed ?? [];
  if (seen.length === 0) {
    return (
      "Addresses assume the bus was idle when the capture window opened. " +
      "AXI4-Lite has no transaction IDs, so responses are paired with " +
      "requests in order; a finite capture cannot prove nothing was already " +
      "outstanding."
    );
  }
  return (
    `The capture opened with ${seen.join(" and ")} transactions already ` +
    "outstanding, so responses are paired with the wrong request from that " +
    "point on. Trigger on the first AW/AR, or capture from an idle bus, " +
    "when exact addresses matter."
  );
}

/** True when the pairing caveat is a detected problem rather than the
 *  standing assumption — the panel styles the two differently. */
export function pairingBroken(decode: AxiDecode): boolean {
  return (decode.pairing?.pre_window_traffic_observed ?? []).length > 0;
}

/** One-line headline for the panel header. */
export function headline(decode: AxiDecode): string {
  return (
    `${decode.transaction_count} transactions ` +
    `(${decode.write_count} write, ${decode.read_count} read) · ` +
    `${decode.error_count} error responses · ` +
    `${decode.anomaly_count} bus faults · ` +
    `${decode.flagged_count} flagged`
  );
}

/** Cell text for a value that the decoder omits when it has none. */
export function cell(value: string | number | undefined | null): string {
  return value === undefined || value === null ? "—" : String(value);
}
