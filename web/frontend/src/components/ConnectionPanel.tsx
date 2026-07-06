import { useState } from "react";
import { getToken, inferIrTable, rpc, setToken } from "../api";
import type { Board, ConnectionParams, Identity } from "../api";

const BACKENDS = ["openocd", "hw_server"];
const DEFAULT_PORT: Record<string, string> = { openocd: "6666", hw_server: "3121" };
const CONNECT_TIMEOUT = 6000;
// Discovery probes every tap on a small sweep of TCL ports, so give it more
// room than a single connect. Each physical board is one OpenOCD instance on
// its own port (port .. port+PORT_SWEEP-1).
const PORT_SWEEP = 4;
const DISCOVER_TIMEOUT = 30000;

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
  const [needsToken, setNeedsToken] = useState(false);
  const [manualTap, setManualTap] = useState("");
  // hw_server: XSDB target names (strings). openocd: probed compatible boards.
  const [targets, setTargets] = useState<string[]>([]);
  const [picked, setPicked] = useState("");
  const [boards, setBoards] = useState<Board[]>([]);
  const [pickedIdx, setPickedIdx] = useState(0);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");

  function resetScan() {
    setTargets([]);
    setPicked("");
    setBoards([]);
    setPickedIdx(0);
    setStatus("");
    setError("");
  }

  function changeBackend(b: string) {
    setBackend(b);
    setPort(DEFAULT_PORT[b] ?? port); // keep port in sync with the backend
    resetScan(); // drop a stale picker from the previous backend
  }

  function handleError(e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    if (msg.toLowerCase().includes("unauthorized")) setNeedsToken(true);
    setError(msg);
  }

  /** Connect using an explicit tap (manual entry or an hw_server target). */
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

  /** Connect to a discovered board (carries its own port/tap/ir_table). */
  async function connectToBoard(b: Board) {
    setStatus(`connecting to ${b.tap} @ :${b.port}…`);
    const params: ConnectionParams = {
      backend: b.backend,
      host: b.host,
      port: b.port,
      tap: b.tap,
      ir_table: b.ir_table,
      chain: 1,
    };
    await rpc("connect", params as unknown as Record<string, unknown>, CONNECT_TIMEOUT);
    const r = await rpc("probe", {}, CONNECT_TIMEOUT);
    onConnected(params, r.probe as Identity);
  }

  async function connect() {
    setBusy(true);
    resetScan();
    setToken(token);
    try {
      if (manualTap.trim()) {
        await connectTo(manualTap.trim());
        return;
      }
      if (backend === "openocd") {
        // Find fcapz-compatible boards; only fail if there are none.
        setStatus("searching for compatible boards…");
        const r = await rpc(
          "discover_boards",
          { backend, host, port: Number(port), port_span: PORT_SWEEP, timeout: 5 },
          DISCOVER_TIMEOUT,
        );
        const found = (r.boards as Board[]) ?? [];
        if (found.length === 0) {
          setError(
            "no compatible fpgacapZero boards found — check the board is programmed and " +
              "OpenOCD is running, or enter a tap manually.",
          );
        } else if (found.length === 1) {
          await connectToBoard(found[0]);
        } else {
          setBoards(found);
          setPickedIdx(0);
          setStatus(`${found.length} compatible boards found — pick one`);
        }
        return;
      }
      // hw_server: list XSDB targets (no ELA probe), then connect.
      setStatus("scanning for targets…");
      const r = await rpc(
        "scan_targets",
        { backend, host, port: Number(port), timeout: 5 },
        CONNECT_TIMEOUT,
      );
      const found = (r.targets as string[]) ?? [];
      if (found.length === 0) {
        setError("no JTAG targets found — check the board / hw_server, or enter a tap manually.");
      } else if (found.length === 1) {
        await connectTo(found[0]);
      } else {
        setTargets(found);
        setPicked(found[0]);
        setStatus(`${found.length} targets found — pick one`);
      }
    } catch (e) {
      handleError(e);
      onDisconnected();
    } finally {
      setBusy(false);
    }
  }

  async function connectPickedTarget() {
    setBusy(true);
    setError("");
    try {
      await connectTo(picked);
    } catch (e) {
      handleError(e);
    } finally {
      setBusy(false);
    }
  }

  async function connectPickedBoard() {
    setBusy(true);
    setError("");
    try {
      await connectToBoard(boards[pickedIdx]);
    } catch (e) {
      handleError(e);
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
    resetScan();
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
          <select value={backend} onChange={(e) => changeBackend(e.target.value)}>
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
          Tap (optional)
          <input
            value={manualTap}
            onChange={(e) => setManualTap(e.target.value)}
            placeholder="auto-detected if blank"
          />
        </label>
        {needsToken && (
          <label>
            API token
            <input
              value={token}
              onChange={(e) => setTok(e.target.value)}
              placeholder="required by this server"
            />
          </label>
        )}
      </div>

      {boards.length > 1 ? (
        <div className="form">
          <label>
            Board
            <select
              value={pickedIdx}
              onChange={(e) => setPickedIdx(Number(e.target.value))}
            >
              {boards.map((b, i) => (
                <option key={`${b.host}:${b.port}:${b.tap}`} value={i}>
                  {b.label}
                </option>
              ))}
            </select>
          </label>
          <div className="btnrow">
            <button onClick={connectPickedBoard} disabled={busy}>
              Connect to {boards[pickedIdx]?.tap}
            </button>
            <button className="secondary" onClick={resetScan} disabled={busy}>
              Cancel
            </button>
          </div>
        </div>
      ) : targets.length > 1 ? (
        <div className="form">
          <label>
            Target
            <select value={picked} onChange={(e) => setPicked(e.target.value)}>
              {targets.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </label>
          <div className="btnrow">
            <button onClick={connectPickedTarget} disabled={busy}>
              Connect to {picked}
            </button>
            <button className="secondary" onClick={resetScan} disabled={busy}>
              Cancel
            </button>
          </div>
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
