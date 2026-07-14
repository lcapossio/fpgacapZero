// Unit tests for the pure logic in api.ts — value parsing that guards against
// silent hardware mis-addressing, and the rpc() error envelope contract that
// auto re-arm depends on. Run with `npm test` (vitest, node environment).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  RpcCancelled,
  RpcError,
  parseIntFlexible,
  parseProbesText,
  rpc,
  toHexParam,
} from "./api";

describe("toHexParam", () => {
  it("converts bare decimal to canonical 0x hex (the server parses base-16)", () => {
    expect(toHexParam("100", "address")).toBe("0x64");
    expect(toHexParam("0", "address")).toBe("0x0");
  });

  it("passes 0x hex through, uppercased", () => {
    expect(toHexParam("0x1f", "address")).toBe("0x1F");
    expect(toHexParam("0xDEADBEEF", "address")).toBe("0xDEADBEEF");
  });

  it("keeps >53-bit values exact via BigInt", () => {
    expect(toHexParam("18446744073709551615", "data")).toBe("0xFFFFFFFFFFFFFFFF");
    expect(toHexParam("0xffffffffffffffff", "data")).toBe("0xFFFFFFFFFFFFFFFF");
  });

  it("rejects malformed, empty, and negative input instead of misparsing", () => {
    expect(() => toHexParam("12x", "address")).toThrow(/invalid address/);
    expect(() => toHexParam("", "address")).toThrow(/invalid address/);
    expect(() => toHexParam("   ", "address")).toThrow(/invalid address/);
    expect(() => toHexParam("-5", "address")).toThrow(/non-negative/);
  });
});

describe("parseIntFlexible", () => {
  it("parses 0x as hex and bare digits as decimal", () => {
    expect(parseIntFlexible("0x10")).toBe(16);
    expect(parseIntFlexible("10")).toBe(10);
    expect(parseIntFlexible("  0X8000 ")).toBe(0x8000);
  });
});

describe("parseProbesText", () => {
  it("returns [] for empty input", () => {
    expect(parseProbesText("")).toEqual([]);
    expect(parseProbesText("   ")).toEqual([]);
  });

  it("parses name:width:lsb lines (lsb defaults to 0)", () => {
    expect(parseProbesText("addr:4:0\ndata:4:4")).toEqual([
      { name: "addr", width: 4, lsb: 0 },
      { name: "data", width: 4, lsb: 4 },
    ]);
    expect(parseProbesText("a:8")).toEqual([{ name: "a", width: 8, lsb: 0 }]);
  });

  it("accepts comma-separated entries", () => {
    expect(parseProbesText("a:1:0, b:1:1")).toEqual([
      { name: "a", width: 1, lsb: 0 },
      { name: "b", width: 1, lsb: 1 },
    ]);
  });

  it("parses .prob JSON with a probes array", () => {
    const json = JSON.stringify({ probes: [{ name: "x", width: 2, lsb: 6 }] });
    expect(parseProbesText(json)).toEqual([{ name: "x", width: 2, lsb: 6 }]);
  });

  it("throws on malformed lines and JSON without a probes array", () => {
    expect(() => parseProbesText("nameonly")).toThrow(/invalid probe/);
    expect(() => parseProbesText("{}")).toThrow(/probes array/);
  });
});

describe("rpc", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", {
      getItem: () => null,
      setItem: () => {},
      removeItem: () => {},
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  function stubFetch(status: number, body: unknown) {
    const fetchMock = vi.fn(async () => ({
      status,
      json: async () => body,
    }));
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("merges cmd + params into one request body and returns the envelope", async () => {
    const fetchMock = stubFetch(200, { ok: true, value: "0x42" });
    const r = await rpc("axi_read", { addr: "0x0" });
    expect(r.value).toBe("0x42");
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ cmd: "axi_read", addr: "0x0" });
  });

  it("throws RpcError carrying the server exception type on in-band failure", async () => {
    // Auto re-arm branches on type === "TimeoutError" — the type must survive.
    stubFetch(200, { ok: false, error: "capture did not complete", type: "TimeoutError" });
    const err = await rpc("capture").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(RpcError);
    expect((err as RpcError).type).toBe("TimeoutError");
    expect((err as RpcError).message).toMatch(/did not complete/);
  });

  it("reports 401 as a missing-token error", async () => {
    stubFetch(401, {});
    await expect(rpc("probe")).rejects.toThrow(/unauthorized/);
  });

  it("throws RpcCancelled (not a timeout) when the caller's signal aborts", async () => {
    // The Cancel button aborts the connect flow; the UI branches on the class
    // to show "cancelled" instead of an error.
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) => {
            init.signal?.addEventListener("abort", () =>
              reject(new DOMException("aborted", "AbortError")),
            );
          }),
      ),
    );
    const ac = new AbortController();
    const pending = rpc("connect", {}, 60000, ac.signal).catch((e: unknown) => e);
    ac.abort();
    expect(await pending).toBeInstanceOf(RpcCancelled);
  });
});
