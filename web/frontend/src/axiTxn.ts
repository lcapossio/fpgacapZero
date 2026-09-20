// Decoded AXI4-Lite transactions (`axi` on a capture response, produced by
// fcapz.axi_decode). Types plus the pure helpers the AXI Txn panel uses, kept
// out of the component so they can be tested without rendering.

/** Flags that mean the bus misbehaved, as opposed to legal-but-notable
 *  behaviour. Mirrors FAULT_FLAGS in host/fcapz/axi_decode.py. */
export const FAULT_FLAGS = [
  "error_response",
  "request_not_observed",
  "unaligned_address",
  "write_missing_address",
  "write_missing_data",
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

export interface AxiDecode {
  protocol: string;
  addr_width: number;
  data_width: number;
  transaction_count: number;
  write_count: number;
  read_count: number;
  error_count: number;
  anomaly_count: number;
  flagged_count: number;
  max_latency: number | null;
  pairing: {
    method: string;
    assumes: string;
    pre_window_traffic_observed: string[];
  };
  transactions: AxiTransaction[];
}

export type KindFilter = "all" | "read" | "write";

/** True when the transaction carries a flag that means a real fault. */
export function isFault(txn: AxiTransaction): boolean {
  return (txn.flags ?? []).some((f) => (FAULT_FLAGS as readonly string[]).includes(f));
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

/** The warning to show when the capture window opened mid-flight, or "".
 *  Pairing is first-in-first-out, so an unmatched response means every later
 *  pairing in that direction may sit on the wrong request. */
export function pairingWarning(decode: AxiDecode): string {
  const seen = decode.pairing?.pre_window_traffic_observed ?? [];
  if (seen.length === 0) return "";
  return (
    `The capture opened with ${seen.join(" and ")} transactions already ` +
    "outstanding, so responses may be paired with the wrong request. " +
    "Trigger on the first AW/AR, or capture from an idle bus, when exact " +
    "addresses matter."
  );
}

/** One-line headline for the panel header. */
export function headline(decode: AxiDecode): string {
  return (
    `${decode.transaction_count} transactions ` +
    `(${decode.write_count} write, ${decode.read_count} read) · ` +
    `${decode.error_count} error responses · ` +
    `${decode.anomaly_count} anomalies`
  );
}

/** Cell text for a value that the decoder omits when it has none. */
export function cell(value: string | number | undefined | null): string {
  return value === undefined || value === null ? "—" : String(value);
}
