import { useState } from "react";
import { parseIntFlexible, rpc } from "../api";
import type { ConnectionParams } from "../api";

const ATTACH_TIMEOUT = 12000;
const DUMP_TIMEOUT = 20000;

function msg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/** JTAG-AXI master — attach the bridge, then single read/write and block dump,
 *  mirroring the desktop GUI's AXI panel over the same unified RPC commands. */
export function AxiPanel({ conn }: { conn: ConnectionParams }) {
  const [chain, setChain] = useState("4");
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

  function push(lines: string[]) {
    setLog((l) => [...lines, ...l].slice(0, 300));
  }

  async function attach() {
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
          chain: Number(chain),
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
      const r = await rpc("axi_read", { addr });
      push([`READ  ${addr} -> ${r.value}`]);
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
      await rpc("axi_write", { addr, data, wstrb });
      push([`WRITE ${addr} <- ${data} (wstrb ${wstrb})`]);
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
      const r = await rpc(
        "axi_dump",
        { addr: dumpAddr, count: Number(dumpCount), burst },
        DUMP_TIMEOUT,
      );
      const words = (r.words as string[]) ?? [];
      const base = parseIntFlexible(dumpAddr);
      const lines = words.map(
        (w, i) =>
          `0x${(base + i * 4).toString(16).toUpperCase().padStart(8, "0")}: ${w}`,
      );
      push([`DUMP ${dumpAddr} x${words.length}${burst ? " (burst)" : ""}`, ...lines]);
    } catch (e) {
      setError(msg(e));
    } finally {
      setBusy(false);
    }
  }

  if (!attached) {
    return (
      <section className="panel">
        <h2>JTAG-AXI</h2>
        <div className="form">
          <label>
            Chain
            <input value={chain} onChange={(e) => setChain(e.target.value)} />
          </label>
        </div>
        <button onClick={attach} disabled={busy}>
          {busy ? "Attaching…" : "Attach AXI"}
        </button>
        {error && <p className="err">{error}</p>}
      </section>
    );
  }

  return (
    <section className="panel">
      <h2>JTAG-AXI</h2>
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
