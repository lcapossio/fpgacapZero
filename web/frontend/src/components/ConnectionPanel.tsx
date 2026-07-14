import { useEffect, useRef, useState } from "react";
import { getToken, rpc, setToken } from "../api";
import type { Board, ConnectionParams, Core, Identity, ProbeSpec } from "../api";
import { probesToText } from "../axiMon";
import type { AxiMonInfo } from "../axiMon";
import { DEFAULT_ELA, useSession } from "../session";
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
// hw_server goes through XSDB (slow cold start). Capped at 15s: if XSDB's first
// start exceeds this the connect aborts, but it leaves hw_server warm so a
// retry is much faster.
const HW_CONNECT_TIMEOUT = 15000;
const HW_SCAN_TIMEOUT = 12; // xsdb subprocess budget (seconds); < the 15s client cap

// Friendly names for the identity readout, so the user sees "Logic Analyzer",
// not the raw ASCII-packed magic (0x4C41 = "LA").
const CORE_NAMES: Record<number, string> = {
  0x4c41: "Embedded Logic Analyzer (ELA)",
  0x494f: "Embedded I/O (EIO)",
};
const VENDOR_NAMES: Record<string, string> = {
  gowin: "Gowin",
  xilinx7: "Xilinx 7-series",
  ultrascale: "Xilinx UltraScale+",
};

function coreName(id: number): string {
  return CORE_NAMES[id] ?? `core 0x${id.toString(16).toUpperCase()}`;
}

function vendorName(ir: string): string {
  return VENDOR_NAMES[ir] ?? ir;
}

/** Human-readable list of the ELA's optional capabilities. */
function elaFeatures(id: Identity): string[] {
  const f: string[] = [];
  if (id.trig_stages && id.trig_stages > 1) f.push(`${id.trig_stages} trigger stages`);
  if (id.has_ext_trigger) f.push("external trigger");
  if (id.has_storage_qualification) f.push("storage qualification");
  if (id.has_decimation) f.push("decimation");
  if (id.has_timestamp)
    f.push(`timestamps${id.timestamp_width ? ` (${id.timestamp_width}-bit)` : ""}`);
  if (id.has_dual_compare) f.push("dual compare");
  return f;
}

/** Synthesize the ELA core entry from the probe identity, for the brief window
 *  before list_cores returns (or if it fails). */
function elaCoreFromIdentity(id: Identity, chain: number): Core {
  return {
    type: "ela",
    name: coreName(id.core_id),
    core_id: id.core_id,
    chain,
    base_addr: 0,
    version_major: id.version_major,
    version_minor: id.version_minor,
    info: id as unknown as Record<string, unknown>,
  };
}

/** One core rendered as a labeled card with type-specific detail. The core the
 *  session is bound to is marked "in use"; others get a one-click switch. */
function CoreCard({
  core,
  active,
  onUse,
  busy,
}: {
  core: Core;
  active?: boolean;
  onUse?: () => void;
  busy?: boolean;
}) {
  // Display component: info is a type-specific bag, read loosely.
  const info = core.info as any;
  const feats = core.type === "ela" ? elaFeatures(core.info as unknown as Identity) : [];
  return (
    <div className="core">
      <div className="core-title">
        {core.type === "ela" || core.type === "eio" || core.type === "axi_mon"
          ? core.name
          : coreName(core.core_id)}{" "}
        <span className="muted">
          v{core.version_major}.{core.version_minor} · 0x
          {core.core_id.toString(16).toUpperCase()}
        </span>
        {active && <span className="ok"> · in use</span>}
      </div>
      <dl className="idinfo">
        {core.type === "ela" && (
          <>
            <dt>Sample width</dt>
            <dd>{Number(info.sample_width)} bits</dd>
            <dt>Depth</dt>
            <dd>{Number(info.depth).toLocaleString()} samples</dd>
            <dt>Channels</dt>
            <dd>{Number(info.num_channels)}</dd>
            {Number(info.num_segments) > 1 ? (
              <>
                <dt>Segments</dt>
                <dd>{Number(info.num_segments)}</dd>
              </>
            ) : null}
            {feats.length > 0 && (
              <>
                <dt>Features</dt>
                <dd>{feats.join(", ")}</dd>
              </>
            )}
          </>
        )}
        {core.type === "eio" && (
          <>
            <dt>Inputs</dt>
            <dd>{Number(info.in_w)}</dd>
            <dt>Outputs</dt>
            <dd>{Number(info.out_w)}</dd>
          </>
        )}
        {core.type === "axi_mon" && (
          <>
            <dt>Protocol</dt>
            <dd>{String(info.proto)}</dd>
            <dt>Bus</dt>
            <dd>
              addr {Number(info.addr_w)} · data {Number(info.data_w)}
            </dd>
            <dt>Decode layer</dt>
            <dd>{info.decode ? "on (event triggers)" : "off"}</dd>
            <dt>Sample width</dt>
            <dd>{Number(info.sample_width)} bits</dd>
          </>
        )}
        {core.base_addr ? (
          <>
            <dt>Address</dt>
            <dd>0x{core.base_addr.toString(16)}</dd>
          </>
        ) : null}
      </dl>
      {onUse && (
        <div className="btnrow">
          <button onClick={onUse} disabled={busy}>
            Use this core
          </button>
        </div>
      )}
    </div>
  );
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
  const { ela, setEla, setAxiMon, cores, setCores, conn, chainSwitch } = useSession();
  // Per-core ELA config, so switching cores doesn't clobber trigger/probe
  // setups — keyed by BSCAN chain, reset with the connection.
  const elaByChain = useRef<Record<number, ElaConfig>>({});

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
    // ir_table and chain are omitted: the server infers the IR preset from
    // the tap name and autodetects the ELA's BSCAN chain, echoing both back —
    // chains are an implementation detail the user never types.
    const reqParams = { backend, host, port: Number(port), tap };
    // hw_server (XSDB) can take tens of seconds to attach; OpenOCD is instant.
    const t = backend === "hw_server" ? HW_CONNECT_TIMEOUT : CONNECT_TIMEOUT;
    const c = await rpc("connect", reqParams, t);
    const params: ConnectionParams = {
      ...reqParams,
      ir_table: typeof c.ir_table === "string" ? c.ir_table : "",
      chain: typeof c.chain === "number" ? c.chain : 1,
    };
    const r = await rpc("probe", {}, t);
    setConnTarget({ backend, host, port: Number(port), tap, ir_table: params.ir_table });
    onConnected(params, r.probe as Identity);
    loadCores();
    detectAxiMon(params.chain);
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
    const c = await rpc("connect", reqParams, CONNECT_TIMEOUT);
    const params: ConnectionParams = {
      ...reqParams,
      chain: typeof c.chain === "number" ? c.chain : 1,
    };
    const r = await rpc("probe", {}, CONNECT_TIMEOUT);
    setConnTarget({
      backend: b.backend,
      host: b.host,
      port: b.port,
      tap: b.tap,
      ir_table: b.ir_table,
    });
    onConnected(params, r.probe as Identity);
    loadCores();
    detectAxiMon(params.chain);
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
    setError("");
    try {
      if (conn) elaByChain.current[conn.chain] = ela;
      const params: ConnectionParams = { ...connTarget, chain: newChain };
      const t = connTarget.backend === "hw_server" ? HW_CONNECT_TIMEOUT : CONNECT_TIMEOUT;
      await rpc("connect", params as unknown as Record<string, unknown>, t);
      const r = await rpc("probe", {}, t);
      onConnected(params, r.probe as Identity);
      const saved = elaByChain.current[newChain];
      setEla(saved ?? DEFAULT_ELA);
      loadCores();
      await detectAxiMon(newChain, !saved);
    } catch (e) {
      handleError(e);
      throw e; // let callers (AXI Mon tab) know the switch failed
    } finally {
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
          oo = await ensureOpenocdRunning();
          if (oo === "started") {
            setStatus("searching for compatible boards…");
            found = await discoverOpenocdBoards();
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
      setStatus("scanning for targets… (starting XSDB can take a while)");
      const r = await rpc(
        "scan_targets",
        { backend, host, port: Number(port), timeout: HW_SCAN_TIMEOUT },
        HW_CONNECT_TIMEOUT,
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
    );
    return (r.boards as Board[]) ?? [];
  }

  /** When discovery finds nothing, transparently bring OpenOCD up if the server
   *  allows it. Returns "started" (retry discovery), "picker" (server has >1
   *  config so the user must choose — a small picker is shown), or "no"
   *  (feature off / remote client). */
  async function ensureOpenocdRunning(): Promise<"started" | "picker" | "no"> {
    let st;
    try {
      st = await rpc("openocd_status", {}, CONNECT_TIMEOUT);
    } catch {
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
    await rpc("openocd_start", { name: configs[0], port: Number(port) }, START_TIMEOUT);
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
    const activeChain = conn?.chain ?? 1;
    const shown = cores.length ? cores : [elaCoreFromIdentity(identity, activeChain)];
    return (
      <section className="panel">
        <h2>Connection</h2>
        <p className="ok">✓ Connected</p>
        {connTarget && (
          <p className="muted">
            {connTarget.tap} · {vendorName(connTarget.ir_table)} ·{" "}
            {connTarget.backend} {connTarget.host}:{connTarget.port}
          </p>
        )}
        <h3>Cores ({shown.length})</h3>
        {shown.map((core, i) => {
          const switchable =
            (core.type === "ela" || core.type === "axi_mon") &&
            core.chain !== activeChain;
          return (
            <CoreCard
              key={`${core.type}-${core.chain}-${core.base_addr}-${i}`}
              core={core}
              active={core.chain === activeChain && core.type !== "eio"}
              busy={busy}
              onUse={
                switchable
                  ? () => {
                      // errors surface via handleError inside switchToChain
                      switchToChain(core.chain).catch(() => {});
                    }
                  : undefined
              }
            />
          );
        })}
        <button onClick={disconnect} disabled={busy}>
          Disconnect
        </button>
        {error && <p className="err">{error}</p>}
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

      {status && <p className="muted">{status}</p>}
      {error && <p className="err">{error}</p>}
    </section>
  );
}
