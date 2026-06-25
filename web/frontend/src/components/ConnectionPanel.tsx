import { useState } from "react";
import { getToken, rpc, setToken } from "../api";
import type { ConnectionParams, Identity } from "../api";

const BACKENDS = ["openocd", "hw_server"];
const IR_TABLES = ["xilinx7", "ultrascale", "gowin"];

export function ConnectionPanel({
  identity,
  onConnected,
  onDisconnected,
}: {
  identity: Identity | null;
  onConnected: (params: ConnectionParams, id: Identity) => void;
  onDisconnected: () => void;
}) {
  const [backend, setBackend] = useState("openocd");
  const [host, setHost] = useState("127.0.0.1");
  const [port, setPort] = useState("6666");
  const [tap, setTap] = useState("GW1NR-9C.tap");
  const [irTable, setIrTable] = useState("gowin");
  const [chain, setChain] = useState("1");
  const [token, setTok] = useState(getToken());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function connect() {
    setBusy(true);
    setError("");
    setToken(token);
    const params: ConnectionParams = {
      backend,
      host,
      port: Number(port),
      tap,
      ir_table: irTable,
      chain: Number(chain),
    };
    try {
      await rpc("connect", params as unknown as Record<string, unknown>);
      const r = await rpc("probe");
      onConnected(params, r.probe as Identity);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      onDisconnected();
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    try {
      await rpc("close");
    } catch {
      /* already gone */
    }
    onDisconnected();
    setBusy(false);
  }

  if (identity) {
    return (
      <section className="panel">
        <h2>Connection</h2>
        <p className="ok">
          Connected — core 0x{identity.core_id.toString(16).toUpperCase()},{" "}
          {identity.sample_width}-bit × {identity.depth} ×{" "}
          {identity.num_channels}ch (v{identity.version_major}.
          {identity.version_minor})
        </p>
        <button onClick={disconnect} disabled={busy}>
          Disconnect
        </button>
      </section>
    );
  }

  return (
    <section className="panel">
      <h2>Connection</h2>
      <div className="form">
        <label>
          Backend
          <select value={backend} onChange={(e) => setBackend(e.target.value)}>
            {BACKENDS.map((b) => (
              <option key={b}>{b}</option>
            ))}
          </select>
        </label>
        <label>
          Host
          <input value={host} onChange={(e) => setHost(e.target.value)} />
        </label>
        <label>
          Port
          <input value={port} onChange={(e) => setPort(e.target.value)} />
        </label>
        <label>
          TAP / target
          <input value={tap} onChange={(e) => setTap(e.target.value)} />
        </label>
        <label>
          IR table
          <select value={irTable} onChange={(e) => setIrTable(e.target.value)}>
            {IR_TABLES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </label>
        <label>
          Chain
          <input value={chain} onChange={(e) => setChain(e.target.value)} />
        </label>
        <label>
          API token
          <input
            value={token}
            onChange={(e) => setTok(e.target.value)}
            placeholder="(only if the server set one)"
          />
        </label>
      </div>
      <button onClick={connect} disabled={busy}>
        {busy ? "Connecting…" : "Connect"}
      </button>
      {error && <p className="err">{error}</p>}
    </section>
  );
}
