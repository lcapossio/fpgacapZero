import { useEffect, useRef, useState } from "react";
import { rpc, toHexParam } from "../api";
import type { ConnectionParams } from "../api";
import { useSession } from "../session";

const ATTACH_TIMEOUT = 12000;
const DUMP_TIMEOUT = 20000;

function msg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** JTAG-AXI master — attach the bridge, then single read/write and block dump,
 *  mirroring the desktop GUI's AXI panel over the same unified RPC commands.
 *  When the bridge was auto-detected on connect, its chain is pre-filled and a
 *  banner names it, so attaching is one click with no chain to guess. */
export function AxiPanel({ conn }: { conn: ConnectionParams }) {
  const { ejtagAxi } = useSession();
  const [chain, setChain] = useState(ejtagAxi ? String(ejtagAxi.chain) : "4");
  const [attached, setAttached] = useState(false);
  const [info, setInfo] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [log, setLog] = useState<string[]>([]);

  const [addr, setAddr] = useState("0x0");
  const [data, setData] = useState("0x0");
  const [wstrb, setWstrb] = useState("0xF");
  const [dumpAddr, setDumpAddr] = useState("0x0");
  const [dumpCount, setDumpCount] = useState("16");
  const [burst, setBurst] = useState(false);

  // Detection lands after connect — adopt the bridge's chain until the user
  // attaches (or edits it themselves; this only re-fires when detection does).
  useEffect(() => {
    if (ejtagAxi && !attached) setChain(String(ejtagAxi.chain));
  }, [ejtagAxi, attached]);

  // Auto-attach once when a bridge was detected — the user shouldn't have to
  // click Attach for a bridge we already found. A manual detach won't re-trigger
  // it (the guard stays set); a reconnect remounts this panel and resets it.
  const autoAttempted = useRef(false);
  useEffect(() => {
    if (ejtagAxi && !attached && !busy && !autoAttempted.current) {
      autoAttempted.current = true;
      attach(ejtagAxi.chain); // use the detected chain, not the pending state
    }
    // attach reads current props/state; run only on detection/attach changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ejtagAxi, attached, busy]);

  function push(lines: string[]) {
    setLog((l) => [...lines, ...l].slice(0, 300));
  }

  async function attach(useChain?: number) {
    setBusy(true);
    setError("");
    try {
      const r = await rpc(
        "axi_connect",
        {
          backend: conn.backend,
          host: conn.host,
          port: conn.port,
          tap: conn.tap,
          ir_table: conn.ir_table,
          chain: useChain ?? Number(chain),
        },
        ATTACH_TIMEOUT,
      );
      setInfo(r);
      setAttached(true);
      push([
        `attached: core 0x${Number(r.core_id ?? 0).toString(16).toUpperCase()}, ` +
          `addr_w=${r.addr_w}, data_w=${r.data_w}, fifo=${r.fifo_depth}`,
      ]);
    } catch (e) {
      setError(msg(e));
    } finally {
      setBusy(false);
    }
  }

  async function detach() {
    setBusy(true);
    try {
      await rpc("axi_close");
    } catch {
      /* already gone */
    }
    setAttached(false);
    setInfo(null);
    setBusy(false);
  }

  async function read() {
    setBusy(true);
    setError("");
    try {
      const a = toHexParam(addr, "address");
      const r = await rpc("axi_read", { addr: a });
      push([`READ  ${a} -> ${r.value}`]);
    } catch (e) {
      setError(msg(e));
    } finally {
      setBusy(false);
    }
  }

  async function write() {
    setBusy(true);
    setError("");
    try {
      const a = toHexParam(addr, "address");
      const d = toHexParam(data, "write data");
      const w = toHexParam(wstrb, "wstrb");
      await rpc("axi_write", { addr: a, data: d, wstrb: w });
      push([`WRITE ${a} <- ${d} (wstrb ${w})`]);
    } catch (e) {
      setError(msg(e));
    } finally {
      setBusy(false);
    }
  }

  async function dump() {
    setBusy(true);
    setError("");
    try {
      const a = toHexParam(dumpAddr, "dump address");
      const r = await rpc(
        "axi_dump",
        { addr: a, count: Number(dumpCount), burst },
        DUMP_TIMEOUT,
      );
      const words = (r.words as string[]) ?? [];
      const base = BigInt(a);
      const lines = words.map(
        (w, i) =>
          `0x${(base + BigInt(i) * 4n).toString(16).toUpperCase().padStart(8, "0")}: ${w}`,
      );
      push([`DUMP ${a} x${words.length}${burst ? " (burst)" : ""}`, ...lines]);
    } catch (e) {
      setError(msg(e));
    } finally {
      setBusy(false);
    }
  }

  if (!attached) {
    return (
      <section className="panel">
        {ejtagAxi ? (
          <p className="ok">
            EJTAG-AXI bridge detected on chain {ejtagAxi.chain} — v
            {ejtagAxi.versionMajor}.{ejtagAxi.versionMinor} · addr {ejtagAxi.addrW} · data{" "}
            {ejtagAxi.dataW} · fifo {ejtagAxi.fifoDepth}
            {ejtagAxi.legacy ? " · legacy" : ""}
          </p>
        ) : (
          <p className="muted">
            No EJTAG-AXI bridge auto-detected — enter its USER chain to attach.
          </p>
        )}
        <div className="form">
          <label>
            Chain
            <input value={chain} onChange={(e) => setChain(e.target.value)} />
          </label>
        </div>
        <button onClick={() => attach()} disabled={busy}>
          {busy ? "Attaching…" : "Attach AXI"}
        </button>
        {error && <p className="err">{error}</p>}
      </section>
    );
  }

  return (
    <section className="panel">
      <p className="muted">
        core 0x{Number(info?.core_id ?? 0).toString(16).toUpperCase()} · addr_w
        {String(info?.addr_w)} · data_w{String(info?.data_w)} · fifo{" "}
        {String(info?.fifo_depth)} · chain {chain}
      </p>

      <div className="form">
        <label>
          Address
          <input value={addr} onChange={(e) => setAddr(e.target.value)} />
        </label>
        <label>
          Write data
          <input value={data} onChange={(e) => setData(e.target.value)} />
        </label>
        <label>
          WSTRB
          <input value={wstrb} onChange={(e) => setWstrb(e.target.value)} />
        </label>
      </div>
      <div className="btnrow">
        <button onClick={read} disabled={busy}>
          Read
        </button>
        <button onClick={write} disabled={busy}>
          Write
        </button>
      </div>

      <div className="form">
        <label>
          Dump address
          <input value={dumpAddr} onChange={(e) => setDumpAddr(e.target.value)} />
        </label>
        <label>
          Word count
          <input value={dumpCount} onChange={(e) => setDumpCount(e.target.value)} />
        </label>
      </div>
      <div className="btnrow">
        <button onClick={dump} disabled={busy}>
          Dump
        </button>
        <label className="inline">
          <input
            type="checkbox"
            checked={burst}
            onChange={(e) => setBurst(e.target.checked)}
          />{" "}
          Burst
        </label>
        <button className="secondary" onClick={detach} disabled={busy}>
          Detach
        </button>
      </div>

      {error && <p className="err">{error}</p>}
      {log.length > 0 && <pre className="axi-log">{log.join("\n")}</pre>}
    </section>
  );
}
