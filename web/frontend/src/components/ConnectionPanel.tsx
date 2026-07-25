import { useEffect, useRef, useState } from "react";
import { RpcCancelled, getToken, rpc, setToken } from "../api";
import type { Board, ConnectionParams, Core, Identity, ProbeSpec } from "../api";
import { probesToText } from "../axiMon";
import type { AxiMonInfo } from "../axiMon";
import { defaultElaForDepth, useSession } from "../session";
import type { ElaConfig } from "../session";

const BACKENDS = ["openocd", "hw_server"];
const DEFAULT_PORT: Record<string, string> = { openocd: "6666", hw_server: "3121" };
const CONNECT_TIMEOUT = 6000;
// Discovery probes every tap on a small sweep of TCL ports, so give it more
// room than a single connect. Each physical board is one OpenOCD instance on
// its own port (port .. port+PORT_SWEEP-1).
const PORT_SWEEP = 4;
// 15s is the cap for every connect-path wait, so a stuck operation fails fast.
const DISCOVER_TIMEOUT = 15000;
// Server-side wall-clock budget for the whole sweep. Kept below the client
// abort so discovery always returns in-band (and releases the server's
// command lock) instead of outliving an aborted request.
const DISCOVER_BUDGET_S = 12;
const START_TIMEOUT = 15000; // server spawns OpenOCD and waits for its TCL port
// Auto-discovery may start OpenOCD once per candidate config and probe each, so
// it needs a wider budget than a single start (several starts + probes back to
// back).
const AUTO_DISCOVER_TIMEOUT = 40000;
// hw_server goes through XSDB (slow cold start). Capped at 15s: if XSDB's first
// start exceeds this the connect aborts, but it leaves hw_server warm so a
// retry is much faster.
const HW_CONNECT_TIMEOUT = 15000;
const HW_SCAN_TIMEOUT = 12; // xsdb subprocess budget (seconds); < the 15s client cap

const VENDOR_NAMES: Record<string, string> = {
  gowin: "Gowin",
  xilinx7: "Xilinx 7-series",
  ultrascale: "Xilinx UltraScale+",
};

function vendorName(ir: string): string {
  return VENDOR_NAMES[ir] ?? ir;
}

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
  // Server-managed OpenOCD ("Start OpenOCD" button), offered only when the
  // server enables it and OpenOCD discovery came up empty.
  const [ooEnabled, setOoEnabled] = useState(false);
  const [ooConfigs, setOoConfigs] = useState<string[]>([]);
  const [ooName, setOoName] = useState("");
  // What we actually connected to (may differ from the form when auto-discovered).
  const [connTarget, setConnTarget] = useState<{
    backend: string;
    host: string;
    port: number;
    tap: string;
    ir_table: string;
  } | null>(null);
  const { ela, setEla, setAxiMon, setEjtagAxi, setCores, conn, chainSwitch, setSwitching } =
    useSession();
  // Per-core ELA config, so switching cores doesn't clobber trigger/probe
  // setups — keyed by BSCAN chain, reset with the connection.
  const elaByChain = useRef<Record<number, ElaConfig>>({});
  // Cancels the in-flight connect flow (scan/discover/connect/probe).
  const abortRef = useRef<AbortController | null>(null);

  /** Arm a fresh cancel scope for a connect flow; returns its signal. */
  function beginCancellable(): AbortSignal {
    const ac = new AbortController();
    abortRef.current = ac;
    return ac.signal;
  }

  function sig(): AbortSignal | undefined {
    return abortRef.current?.signal;
  }

  function resetScan() {
    setTargets([]);
    setPicked("");
    setBoards([]);
    setPickedIdx(0);
    setOoEnabled(false);
    setCores([]);
    setStatus("");
    setError("");
    elaByChain.current = {};
  }

  /** Populate the "Cores" section (ELA + EIO + any others) after connect. */
  async function loadCores() {
    try {
      const r = await rpc("list_cores", {}, CONNECT_TIMEOUT);
      setCores((r.cores as Core[]) ?? []);
    } catch {
      setCores([]); // fall back to the ELA synthesized from probe
    }
  }

  /** Detect an AXI monitor anywhere on the target and share it with the AXI
   *  Mon tab (the server scans the other chains too and reports where the
   *  monitor lives). When the monitor is the core the session is bound to,
   *  apply its probe map so captures already show named AXI fields —
   *  `force` overrides existing probe text (used right after switching). */
  async function detectAxiMon(sessionChain: number, force = false) {
    try {
      const r = await rpc("axi_mon_probe", {}, CONNECT_TIMEOUT);
      if (r.present) {
        const info: AxiMonInfo = {
          chain: typeof r.chain === "number" ? r.chain : sessionChain,
          proto: String(r.proto),
          addr_w: Number(r.addr_w),
          data_w: Number(r.data_w),
          decode: Boolean(r.decode),
          sample_width: Number(r.sample_width),
          probes: (r.probes as ProbeSpec[]) ?? [],
        };
        setAxiMon(info);
        const bound = info.chain === sessionChain;
        if (bound && (force || !ela.probesText.trim()) && info.probes.length) {
          setEla({ probesText: probesToText(info.probes) });
        }
        return;
      }
    } catch {
      /* older server or transient error — treat as no monitor */
    }
    setAxiMon(null);
  }

  /** Auto-detect an EJTAG-AXI bridge on the target (its own USER chain) and
   *  share it with the AXI tab so it can attach without the user typing a
   *  chain. Best-effort: absent, an older server, or a transient error all
   *  just leave the AXI tab in its manual-attach state. */
  async function detectEjtagAxi() {
    try {
      const r = await rpc("ejtag_axi_probe", {}, CONNECT_TIMEOUT);
      if (r.present) {
        setEjtagAxi({
          chain: Number(r.chain),
          coreId: Number(r.core_id ?? r.bridge_id ?? 0),
          versionMajor: Number(r.version_major ?? 0),
          versionMinor: Number(r.version_minor ?? 0),
          addrW: Number(r.addr_w ?? 0),
          dataW: Number(r.data_w ?? 0),
          fifoDepth: Number(r.fifo_depth ?? 0),
          legacy: Boolean(r.legacy_id),
        });
        return;
      }
    } catch {
      /* older server or transient error — treat as no bridge */
    }
    setEjtagAxi(null);
  }

  function changeBackend(b: string) {
    setBackend(b);
    setPort(DEFAULT_PORT[b] ?? port); // keep port in sync with the backend
    resetScan(); // drop a stale picker from the previous backend
  }

  function handleError(e: unknown) {
    if (e instanceof RpcCancelled) {
      setStatus("cancelled");
      setError("");
      return;
    }
    const msg = e instanceof Error ? e.message : String(e);
    if (msg.toLowerCase().includes("unauthorized")) setNeedsToken(true);
    setError(msg);
  }

  /** Connect using an explicit tap (manual entry or an hw_server target). */
  async function connectTo(tap: string) {
    setStatus(`connecting to ${tap}…`);
    // ir_table and chain are omitted: the server infers the IR preset from
    // the tap name and autodetects the ELA's BSCAN chain, echoing both back —
    // chains are an implementation detail the user never types.
    const reqParams = { backend, host, port: Number(port), tap };
    // hw_server (XSDB) can take tens of seconds to attach; OpenOCD is instant.
    const t = backend === "hw_server" ? HW_CONNECT_TIMEOUT : CONNECT_TIMEOUT;
    const c = await rpc("connect", reqParams, t, sig());
    const params: ConnectionParams = {
      ...reqParams,
      ir_table: typeof c.ir_table === "string" ? c.ir_table : "",
      chain: typeof c.chain === "number" ? c.chain : 1,
    };
    const r = await rpc("probe", {}, t, sig());
    setConnTarget({ backend, host, port: Number(port), tap, ir_table: params.ir_table });
    const id = r.probe as Identity;
    onConnected(params, id);
    // Fill the whole capture buffer by default (8 pre-trigger, the rest post).
    setEla(defaultElaForDepth(id.depth, id.num_segments));
    loadCores();
    detectAxiMon(params.chain);
    detectEjtagAxi();
  }

  /** Connect to a discovered board (carries its own port/tap/ir_table). */
  async function connectToBoard(b: Board) {
    setStatus(`connecting to ${b.tap} @ :${b.port}…`);
    const reqParams = {
      backend: b.backend,
      host: b.host,
      port: b.port,
      tap: b.tap,
      ir_table: b.ir_table,
    };
    const c = await rpc("connect", reqParams, CONNECT_TIMEOUT, sig());
    const params: ConnectionParams = {
      ...reqParams,
      chain: typeof c.chain === "number" ? c.chain : 1,
    };
    const r = await rpc("probe", {}, CONNECT_TIMEOUT, sig());
    setConnTarget({
      backend: b.backend,
      host: b.host,
      port: b.port,
      tap: b.tap,
      ir_table: b.ir_table,
    });
    const id = r.probe as Identity;
    onConnected(params, id);
    setEla(defaultElaForDepth(id.depth, id.num_segments));
    loadCores();
    detectAxiMon(params.chain);
    detectEjtagAxi();
  }

  /** Re-bind the connected session to a core on another BSCAN chain (e.g.
   *  the AXI monitor) — same target, different core, no user-visible chains.
   *  Each core keeps its own ELA config: the current one is stashed before
   *  the switch and restored when the user comes back; a first visit gets
   *  defaults (plus the monitor's probe map, force-applied). */
  async function switchToChain(newChain: number) {
    if (!connTarget) return;
    if (conn && newChain === conn.chain) return; // already on that core
    setBusy(true);
    // Freeze Run controls for the duration — an arm built for the old core
    // would hit the new core's geometry mid-switch.
    setSwitching(true);
    setError("");
    try {
      if (conn) elaByChain.current[conn.chain] = ela;
      const params: ConnectionParams = { ...connTarget, chain: newChain };
      const t = connTarget.backend === "hw_server" ? HW_CONNECT_TIMEOUT : CONNECT_TIMEOUT;
      // Rebind keeps the live transport and just hops the tap — no reconnect,
      // so ELA <-> AXI monitor switching is one short round-trip, not two
      // connect-weight ones plus a teardown.
      const r = await rpc("rebind", { chain: newChain }, t);
      const id = r.probe as Identity;
      onConnected(params, id);
      const saved = elaByChain.current[newChain];
      setEla(saved ?? defaultElaForDepth(id.depth, id.num_segments));
      loadCores();
      await detectAxiMon(newChain, !saved);
    } catch (e) {
      handleError(e);
      throw e; // let callers (AXI Mon tab) know the switch failed
    } finally {
      setSwitching(false);
      setBusy(false);
    }
  }

  // Expose the switch to other panels (the AXI Mon tab offers it one-click).
  useEffect(() => {
    chainSwitch.current = switchToChain;
    return () => {
      chainSwitch.current = null;
    };
  });

  async function connect() {
    setBusy(true);
    resetScan();
    setToken(token);
    beginCancellable();
    try {
      if (manualTap.trim()) {
        await connectTo(manualTap.trim());
        return;
      }
      if (backend === "openocd") {
        // Just connect: find compatible boards and, if none are reachable,
        // transparently start OpenOCD (when the server allows it) and retry.
        setStatus("searching for compatible boards…");
        let found = await discoverOpenocdBoards();
        let oo: "started" | "picker" | "no" = "no";
        if (found.length === 0) {
          // Nothing already running — let the server bring OpenOCD up itself:
          // filter the configured configs by which USB JTAG adapters are
          // plugged in, then start + probe each. No config picking needed.
          found = await autoDiscoverBoards();
          if (found.length === 0) {
            // Auto-discovery came up empty (feature off, older server, or no
            // adapter matched) — fall back to the manual "Start OpenOCD" path.
            oo = await ensureOpenocdRunning();
            if (oo === "started") {
              setStatus("searching for compatible boards…");
              found = await discoverOpenocdBoards();
            }
          }
        }
        if (found.length === 0) {
          if (oo !== "picker") {
            setError(
              "no compatible fpgacapZero boards found — check the board is " +
                "programmed and cabled, or enter a tap manually.",
            );
          }
        } else if (found.length === 1) {
          await connectToBoard(found[0]);
        } else {
          setBoards(found);
          setPickedIdx(0);
          setStatus(`${found.length} compatible boards found — pick one`);
        }
        return;
      }
      // hw_server: XSDB starts a local hw_server as needed, so just scan + connect.
      // XSDB is slow to start, so both the server-side (timeout) and client-side
      // budgets are much larger than the OpenOCD path's.
      setStatus("scanning for targets…");
      const r = await rpc(
        "scan_targets",
        { backend, host, port: Number(port), timeout: HW_SCAN_TIMEOUT },
        HW_CONNECT_TIMEOUT,
        sig(),
      );
      const found = (r.targets as string[]) ?? [];
      if (found.length === 0) {
        setError(
          "no JTAG targets found — check the board is programmed and cabled " +
            "(Vivado / hw_server), or enter a tap manually.",
        );
      } else if (found.length === 1) {
        await connectTo(found[0]);
      } else {
        setTargets(found);
        setPicked(found[0]);
        setStatus(`${found.length} targets found — pick one`);
      }
    } catch (e) {
      handleError(e);
      // A failure after the backend `connect` succeeded (e.g. `probe` threw)
      // leaves a hardware session open server-side. Tear it down so the UI's
      // disconnected state matches the backend instead of relying on the next
      // connect's implicit cleanup.
      try {
        await rpc("close", {}, CONNECT_TIMEOUT);
      } catch {
        /* nothing to close */
      }
      onDisconnected();
    } finally {
      abortRef.current = null;
      setBusy(false);
    }
  }

  /** Run OpenOCD discovery once and return the compatible boards. */
  async function discoverOpenocdBoards(): Promise<Board[]> {
    const r = await rpc(
      "discover_boards",
      {
        backend,
        host,
        port: Number(port),
        port_span: PORT_SWEEP,
        timeout: 5,
        budget: DISCOVER_BUDGET_S,
      },
      DISCOVER_TIMEOUT,
      sig(),
    );
    return (r.boards as Board[]) ?? [];
  }

  /** Ask the server to auto-discover boards: filter its allow-listed OpenOCD
   *  configs by the USB JTAG adapters that are actually attached, then start
   *  OpenOCD per surviving config and probe for an fpgacapZero core. Returns
   *  confirmed boards (each on its own running port). Empty when the feature is
   *  off, the server is older, the client is remote, or nothing answered. */
  async function autoDiscoverBoards(): Promise<Board[]> {
    try {
      setStatus("starting OpenOCD and probing for boards…");
      const r = await rpc(
        "openocd_discover",
        { backend, host, port: Number(port) },
        AUTO_DISCOVER_TIMEOUT,
        sig(),
      );
      return (r.boards as Board[]) ?? [];
    } catch (e) {
      if (e instanceof RpcCancelled) throw e;
      return []; // feature off / older server / remote client
    }
  }

  /** When discovery finds nothing, transparently bring OpenOCD up if the server
   *  allows it. Returns "started" (retry discovery), "picker" (server has >1
   *  config so the user must choose — a small picker is shown), or "no"
   *  (feature off / remote client). */
  async function ensureOpenocdRunning(): Promise<"started" | "picker" | "no"> {
    let st;
    try {
      st = await rpc("openocd_status", {}, CONNECT_TIMEOUT, sig());
    } catch (e) {
      if (e instanceof RpcCancelled) throw e;
      return "no"; // feature off / not a loopback client
    }
    const configs = (st.configs as string[]) ?? [];
    if (!st.enabled || configs.length === 0) return "no";
    if (configs.length > 1) {
      setOoConfigs(configs);
      setOoName(configs[0]);
      setOoEnabled(true); // ambiguous which board — let the user pick
      setStatus("no board found — pick an OpenOCD config to start");
      return "picker";
    }
    setStatus(`starting OpenOCD (${configs[0]})…`);
    await rpc("openocd_start", { name: configs[0], port: Number(port) }, START_TIMEOUT, sig());
    return "started";
  }

  /** Ask the server to launch OpenOCD, then re-run discovery. */
  async function startOpenocd() {
    setError("");
    setBusy(true);
    setStatus(`starting OpenOCD (${ooName})…`);
    try {
      await rpc(
        "openocd_start",
        { name: ooName, port: Number(port) },
        START_TIMEOUT,
      );
    } catch (e) {
      handleError(e);
      setBusy(false);
      return;
    }
    setBusy(false);
    setOoEnabled(false);
    await connect(); // OpenOCD is up now — discover + connect
  }

  async function connectPickedTarget() {
    setBusy(true);
    setError("");
    beginCancellable();
    try {
      await connectTo(picked);
    } catch (e) {
      handleError(e);
    } finally {
      abortRef.current = null;
      setBusy(false);
    }
  }

  async function connectPickedBoard() {
    setBusy(true);
    setError("");
    beginCancellable();
    try {
      await connectToBoard(boards[pickedIdx]);
    } catch (e) {
      handleError(e);
    } finally {
      abortRef.current = null;
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
        <div className="btnrow">
          <span className="ok">✓ Connected</span>
          <button onClick={disconnect} disabled={busy}>
            Disconnect
          </button>
        </div>
        {error && <p className="err">{error}</p>}
        {connTarget && (
          <p className="muted">
            {connTarget.tap} · {vendorName(connTarget.ir_table)} ·{" "}
            {connTarget.backend} {connTarget.host}:{connTarget.port}
          </p>
        )}
        <p className="muted">
          The discovered debug cores are listed in the <b>Cores</b> tab.
        </p>
      </section>
    );
  }

  // A scan that turns up more than one board/target resolves right here in the
  // button row — the picker replaces Connect instead of appearing below the form.
  const pickerMode = boards.length > 1 ? "boards" : targets.length > 1 ? "targets" : null;

  return (
    <section className="panel">
      <div className="btnrow">
        {pickerMode ? (
          <>
            {pickerMode === "boards" ? (
              <select
                className="conn-picker"
                value={pickedIdx}
                onChange={(e) => setPickedIdx(Number(e.target.value))}
                title="Choose which discovered board to connect to"
              >
                {boards.map((b, i) => (
                  <option key={`${b.host}:${b.port}:${b.tap}`} value={i}>
                    {b.label}
                  </option>
                ))}
              </select>
            ) : (
              <select
                className="conn-picker"
                value={picked}
                onChange={(e) => setPicked(e.target.value)}
                title="Choose which JTAG target to connect to"
              >
                {targets.map((t) => (
                  <option key={t}>{t}</option>
                ))}
              </select>
            )}
            <button
              className="conn-primary"
              onClick={pickerMode === "boards" ? connectPickedBoard : connectPickedTarget}
              disabled={busy}
            >
              {busy ? "Working…" : "Connect"}
            </button>
            <button className="secondary" onClick={resetScan} disabled={busy}>
              Dismiss
            </button>
          </>
        ) : (
          <>
            {/* Fixed width so the label swap (Connect -> Working…) doesn't resize
                it, and Cancel keeps its slot when idle — the buttons never move. */}
            <button className="conn-primary" onClick={connect} disabled={busy}>
              {busy ? "Working…" : "Connect"}
            </button>
            <button
              className={`danger${busy ? "" : " invisible"}`}
              onClick={() => abortRef.current?.abort()}
              disabled={!busy}
              tabIndex={busy ? undefined : -1}
              aria-hidden={!busy}
            >
              Cancel
            </button>
          </>
        )}
        {/* Inline so the transient connect status can't push the form down. */}
        {status && (
          <span className="muted conn-status" title={status}>
            {status}
          </span>
        )}
      </div>
      {error && <p className="err">{error}</p>}
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

      {ooEnabled && (
        <div className="btnrow">
          {ooConfigs.length > 1 && (
            <select value={ooName} onChange={(e) => setOoName(e.target.value)}>
              {ooConfigs.map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          )}
          <button onClick={startOpenocd} disabled={busy}>
            Start OpenOCD
          </button>
        </div>
      )}
    </section>
  );
}
