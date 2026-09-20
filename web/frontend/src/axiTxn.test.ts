import { describe, expect, it } from "vitest";
import {
  asAxiDecode,
  cell,
  filterTransactions,
  headline,
  isFault,
  pairingWarning,
} from "./axiTxn";
import type { AxiDecode, AxiTransaction } from "./axiTxn";

function txn(over: Partial<AxiTransaction> = {}): AxiTransaction {
  return { index: 0, kind: "write", addr: "0x1000", ...over };
}

function decode(over: Partial<AxiDecode> = {}): AxiDecode {
  return {
    protocol: "axi4lite",
    addr_width: 32,
    data_width: 32,
    transaction_count: 0,
    write_count: 0,
    read_count: 0,
    error_count: 0,
    anomaly_count: 0,
    flagged_count: 0,
    max_latency: null,
    pairing: { method: "in-order", assumes: "", pre_window_traffic_observed: [] },
    transactions: [],
    ...over,
  };
}

describe("isFault", () => {
  it("separates real faults from legal-but-notable behaviour", () => {
    expect(isFault(txn({ flags: ["error_response"] }))).toBe(true);
    expect(isFault(txn({ flags: ["request_not_observed"] }))).toBe(true);
    // Legal AXI. Reporting these as faults would make the filter useless.
    expect(isFault(txn({ flags: ["partial_write"] }))).toBe(false);
    expect(isFault(txn({ flags: ["data_before_address"] }))).toBe(false);
    expect(isFault(txn({ flags: ["no_response_in_window"] }))).toBe(false);
    expect(isFault(txn())).toBe(false);
  });
});

describe("filterTransactions", () => {
  const rows = [
    txn({ index: 0, kind: "write", flags: ["error_response"] }),
    txn({ index: 1, kind: "read" }),
    txn({ index: 2, kind: "write", flags: ["partial_write"] }),
  ];

  it("passes everything through by default", () => {
    expect(filterTransactions(rows, { kind: "all", onlyAnomalies: false })).toHaveLength(3);
  });

  it("filters by direction", () => {
    const reads = filterTransactions(rows, { kind: "read", onlyAnomalies: false });
    expect(reads.map((t) => t.index)).toEqual([1]);
  });

  it("filters to faults, not to anything merely flagged", () => {
    const faults = filterTransactions(rows, { kind: "all", onlyAnomalies: true });
    expect(faults.map((t) => t.index)).toEqual([0]);
  });

  it("combines both filters", () => {
    expect(filterTransactions(rows, { kind: "read", onlyAnomalies: true })).toEqual([]);
  });

  it("keeps trace order", () => {
    const out = filterTransactions(rows, { kind: "write", onlyAnomalies: false });
    expect(out.map((t) => t.index)).toEqual([0, 2]);
  });
});

describe("asAxiDecode", () => {
  it("accepts a decode", () => {
    expect(asAxiDecode(decode())).toBeDefined();
  });

  it("rejects a capture that carries none", () => {
    // Non-AXI captures simply have no `axi` key; the panel must not crash.
    expect(asAxiDecode(undefined)).toBeUndefined();
    expect(asAxiDecode(null)).toBeUndefined();
    expect(asAxiDecode({})).toBeUndefined();
    expect(asAxiDecode({ transactions: [] })).toBeUndefined();
    expect(asAxiDecode({ protocol: "axi4lite" })).toBeUndefined();
  });
});

describe("pairingWarning", () => {
  it("is silent when the window opened clean", () => {
    expect(pairingWarning(decode())).toBe("");
  });

  it("warns when a response had no visible request", () => {
    const warning = pairingWarning(
      decode({
        pairing: {
          method: "in-order",
          assumes: "",
          pre_window_traffic_observed: ["read", "write"],
        },
      }),
    );
    expect(warning).toContain("read and write");
    expect(warning).toContain("wrong request");
  });
});

describe("headline", () => {
  it("counts what the user is looking for", () => {
    const text = headline(
      decode({ transaction_count: 9, write_count: 5, read_count: 4, error_count: 2, anomaly_count: 3 }),
    );
    expect(text).toContain("9 transactions");
    expect(text).toContain("5 write, 4 read");
    expect(text).toContain("2 error responses");
    expect(text).toContain("3 anomalies");
  });
});

describe("cell", () => {
  it("renders an omitted field as a dash, not as 'undefined'", () => {
    expect(cell(undefined)).toBe("—");
    expect(cell(null)).toBe("—");
    // 0 is a real value and must survive.
    expect(cell(0)).toBe("0");
    expect(cell("0x0")).toBe("0x0");
  });
});
