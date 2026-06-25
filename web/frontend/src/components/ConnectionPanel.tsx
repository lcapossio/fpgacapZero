import { useState } from "react";
import { getToken, inferIrTable, rpc, setToken } from "../api";
import type { ConnectionParams, Identity } from "../api";

const BACKENDS = ["openocd", "hw_server"];
const CONNECT_TIMEOUT = 6000;

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
  const [token, setTok] = useState(getToken());
  const [manualTap, setManualTap] = useState("");
  const [targets, setTargets] = useState<string[]>([]);
  const [picked, setPicked] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");

  async function connectTo(tap: string) {
    setStatus(`connecting to ${tap}…`);
    const params: ConnectionParams = {
      backend,
      host,
      port: Number(port),
      tap,
      ir_table: inferIrTable(tap),
      chain: 1,
    };
    await rpc("connect", params as unknown as Record<string, unknown>, CONNECT_TIMEOUT);
    const r = await rpc("probe", {}, CONNECT_TIMEOUT);
    onConnected(params, r.probe as Identity);
  }

  async function connect() {
    setBusy(true);
    setError("");
    setStatus("");
    setTargets([]);
    setToken(token);
    try {
      if (manualTap.trim()) {
        await connectTo(manualTap.trim());
        return;
      }
      setStatus("scanning for targets…");
      const r = await rpc(
        "scan_targets",
        { backend, host, port: Number(port) },
        CONNECT_TIMEOUT,
      );
      const found = (r.targets as string[]) ?? [];
      if (found.length === 0) {
        setError("no JTAG targets found — check the board / OpenOCD, or enter a tap manually.");
      } else if (found.length === 1) {
        await connectTo(found[0]);
      } else {
        setTargets(found);
        setPicked(found[0]);
        setStatus(`${found.length} targets found — pick one`);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      onDisconnected();
    } finally {
      setBusy(false);
    }
  }

  async function connectPicked() {
    setBusy(true);
    setError("");
    try {
      await connectTo(picked);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    try {
      await rpc("close", {}, CONNECT_TIMEOUT);
    } catch {
      /* already gone */
    }
    setTargets([]);
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
          API token
          <input
            value={token}
            onChange={(e) => setTok(e.target.value)}
            placeholder="(if server set one)"
          />
        </label>
        <label>
          Tap (optional)
          <input
            value={manualTap}
            onChange={(e) => setManualTap(e.target.value)}
            placeholder="auto-detected if blank"
          />
        </label>
      </div>

      {targets.length > 1 ? (
        <div className="form">
          <label>
            Target
            <select value={picked} onChange={(e) => setPicked(e.target.value)}>
              {targets.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </label>
          <button onClick={connectPicked} disabled={busy}>
            Connect to {picked}
          </button>
        </div>
      ) : (
        <button onClick={connect} disabled={busy}>
          {busy ? "Working…" : "Connect"}
        </button>
      )}

      {status && <p className="muted">{status}</p>}
      {error && <p className="err">{error}</p>}
    </section>
  );
}
