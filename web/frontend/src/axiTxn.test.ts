import { describe, expect, it } from "vitest";
import {
  asAxiDecode,
  cell,
  filterTransactions,
  headline,
  isFault,
  isWindowEdge,
  pairingBroken,
  pairingWarning,
  undecodableReason,
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
    decoded: true,
    unavailable_reason: null,
    sampling: { decimation: 0, storage_qualified: false, contiguous: true },
    transaction_count: 0,
    write_count: 0,
    read_count: 0,
    error_count: 0,
    anomaly_count: 0,
    flagged_count: 0,
    max_latency: null,
    pairing: {
      method: "in-order",
      assumes: "",
      pre_window_traffic_observed: [],
      pre_window_traffic_proven: false,
    },
    transactions: [],
    ...over,
  };
}

describe("isFault", () => {
  it("counts only what a finite window can prove", () => {
    expect(isFault(txn({ flags: ["error_response"] }))).toBe(true);
    expect(isFault(txn({ flags: ["unaligned_address"] }))).toBe(true);
    // Legal AXI. Reporting these as faults would make the filter useless.
    expect(isFault(txn({ flags: ["partial_write"] }))).toBe(false);
    expect(isFault(txn({ flags: ["data_before_address"] }))).toBe(false);
    expect(isFault(txn())).toBe(false);
  });

  it("does not call a window edge a bus fault", () => {
    // The request handshook before the capture started, or the second beat
    // falls after it ends. Both are ordinary traffic seen through a keyhole.
    for (const flag of [
      "request_not_observed",
      "no_response_in_window",
      "write_missing_data",
      "write_missing_address",
      "pairing_suspect",
    ]) {
      expect(isFault(txn({ flags: [flag] }))).toBe(false);
      expect(isWindowEdge(txn({ flags: [flag] }))).toBe(true);
    }
  });
});

describe("filterTransactions", () => {
  const rows = [
    txn({ index: 0, kind: "write", flags: ["error_response"] }),
    txn({ index: 1, kind: "read" }),
    txn({ index: 2, kind: "write", flags: ["partial_write"] }),
    txn({ index: 3, kind: "write", flags: ["request_not_observed"] }),
  ];

  it("passes everything through by default", () => {
    expect(filterTransactions(rows, { kind: "all", onlyAnomalies: false })).toHaveLength(4);
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
    expect(out.map((t) => t.index)).toEqual([0, 2, 3]);
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

describe("undecodableReason", () => {
  it("is empty for a capture that decoded", () => {
    expect(undecodableReason(decode())).toBe("");
    // An older server that sends no `decoded` field still decoded it.
    expect(undecodableReason(decode({ decoded: undefined }))).toBe("");
  });

  it("explains a capture that stored only selected cycles", () => {
    const reason = undecodableReason(
      decode({
        decoded: false,
        unavailable_reason: "the capture stored only selected cycles",
        sampling: { decimation: 3, storage_qualified: false, contiguous: false },
      }),
    );
    expect(reason).toContain("selected cycles");
  });
});

describe("pairingWarning", () => {
  it("states the assumption even when the window looked clean", () => {
    // The dangerous case: a window that opened mid-transaction produces rows
    // that read perfectly and carry the wrong address. Silence here would be
    // read as confirmation.
    const text = pairingWarning(decode());
    expect(text).toContain("idle");
    expect(text).toContain("cannot prove");
    expect(pairingBroken(decode())).toBe(false);
  });

  it("escalates when a response had no visible request", () => {
    const broken = decode({
      pairing: {
        method: "in-order",
        assumes: "",
        pre_window_traffic_observed: ["read", "write"],
        pre_window_traffic_proven: true,
      },
    });
    const warning = pairingWarning(broken);
    expect(warning).toContain("read and write");
    expect(warning).toContain("wrong request");
    expect(pairingBroken(broken)).toBe(true);
  });
});

describe("headline", () => {
  it("separates bus faults from everything merely flagged", () => {
    const text = headline(
      decode({
        transaction_count: 9,
        write_count: 5,
        read_count: 4,
        error_count: 2,
        anomaly_count: 3,
        flagged_count: 7,
      }),
    );
    expect(text).toContain("9 transactions");
    expect(text).toContain("5 write, 4 read");
    expect(text).toContain("2 error responses");
    expect(text).toContain("3 bus faults");
    expect(text).toContain("7 flagged");
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
