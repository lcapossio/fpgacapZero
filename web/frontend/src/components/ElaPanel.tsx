import { useRef, useState } from "react";
import { parseIntFlexible, rpc } from "../api";
import type { Identity } from "../api";

const SINGLE_TIMEOUT = 10; // hardware wait (s) for a single capture
const CONT_TIMEOUT = 5; // shorter per-capture wait in auto re-arm so Stop is responsive

/** ELA run controls — Arm / Trigger Immediate / Auto re-arm / Stop, mirroring
 *  the desktop GUI. The waveform renders in the Viewer (Surfer) tab; each
 *  capture is pushed up via onCaptured as VCD text. */
export function ElaPanel({
  identity,
  onCaptured,
}: {
  identity: Identity;
  onCaptured: (vcd: string) => void;
}) {
  const [channel, setChannel] = useState("0");
  const [pretrigger, setPre] = useState("8");
  const [posttrigger, setPost] = useState("16");
  const [triggerMode, setTriggerMode] = useState("value_match");
  const [triggerValue, setTriggerValue] = useState("0x00");
  const [triggerMask, setTriggerMask] = useState("0xFF");
  const [autoRearm, setAutoRearm] = useState(false);
  const [busy, setBusy] = useState(false); // a single capture in flight
  const [running, setRunning] = useState(false); // continuous loop active
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [overflow, setOverflow] = useState(false);
  const runRef = useRef(false); // synchronous stop flag for the loop

  function params(immediate: boolean, timeout: number) {
    return {
      channel: Number(channel),
      pretrigger: Number(pretrigger),
      posttrigger: Number(posttrigger),
      trigger_mode: triggerMode,
      trigger_value: parseIntFlexible(triggerValue),
      trigger_mask: parseIntFlexible(triggerMask),
      sample_width: identity.sample_width,
      depth: identity.depth,
      timeout,
      immediate, // Trigger Immediate -> always-true trigger
      include_vcd: true, // the Viewer tab loads this into Surfer
    };
  }

  // One capture. The fetch timeout must exceed the hardware wait or it would
  // abort before a slow trigger fires.
  async function once(immediate: boolean, timeout: number) {
    const r = await rpc("capture", params(immediate, timeout), timeout * 1000 + 4000);
    setOverflow(Boolean(r.overflow));
    if (typeof r.vcd === "string") onCaptured(r.vcd);
    return r.sample_count ?? "?";
  }

  async function single(immediate: boolean) {
    setBusy(true);
    setError("");
    setStatus("");
    try {
      const n = await once(immediate, SINGLE_TIMEOUT);
      setStatus(`captured ${n} samples — see the Viewer tab`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function loop(immediate: boolean) {
    setError("");
    setRunning(true);
    runRef.current = true;
    let count = 0;
    try {
      while (runRef.current) {
        const n = await once(immediate, CONT_TIMEOUT);
        count += 1;
        setStatus(`auto re-arm: ${count} captures (${n} samples)`);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      runRef.current = false;
      setRunning(false);
    }
  }

  function start(immediate: boolean) {
    if (autoRearm) loop(immediate);
    else single(immediate);
  }

  function stop() {
    runRef.current = false; // loop exits after the in-flight capture returns
    setStatus("stopping…");
  }

  const locked = busy || running;

  return (
    <section className="panel">
      <h2>ELA capture</h2>
      <div className="form">
        <label>
          Channel
          <input value={channel} onChange={(e) => setChannel(e.target.value)} />
        </label>
        <label>
          Pre
          <input value={pretrigger} onChange={(e) => setPre(e.target.value)} />
        </label>
        <label>
          Post
          <input value={posttrigger} onChange={(e) => setPost(e.target.value)} />
        </label>
        <label>
          Mode
          <select
            value={triggerMode}
            onChange={(e) => setTriggerMode(e.target.value)}
          >
            <option value="value_match">value_match</option>
            <option value="edge_detect">edge_detect</option>
            <option value="both">both</option>
          </select>
        </label>
        <label>
          Trigger value
          <input
            value={triggerValue}
            onChange={(e) => setTriggerValue(e.target.value)}
          />
        </label>
        <label>
          Trigger mask
          <input
            value={triggerMask}
            onChange={(e) => setTriggerMask(e.target.value)}
          />
        </label>
      </div>

      <div className="btnrow">
        <button onClick={() => start(false)} disabled={locked}>
          {busy ? "Arming…" : "Arm"}
        </button>
        <button onClick={() => start(true)} disabled={locked}>
          Trigger Immediate
        </button>
        <button className="secondary" onClick={stop} disabled={!running}>
          Stop
        </button>
        <label className="inline">
          <input
            type="checkbox"
            checked={autoRearm}
            onChange={(e) => setAutoRearm(e.target.checked)}
            disabled={running}
          />{" "}
          Auto re-arm
        </label>
      </div>

      {overflow && <p className="warn">overflow</p>}
      {status && <p className="muted">{status}</p>}
      {error && <p className="err">{error}</p>}
    </section>
  );
}
