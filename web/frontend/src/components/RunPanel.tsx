import { useRef, useState } from "react";
import { parseIntFlexible, rpc } from "../api";
import type { Identity } from "../api";
import { useSession } from "../session";

const SINGLE_TIMEOUT = 10; // hardware wait (s) for a single capture
const CONT_TIMEOUT = 5; // shorter per-capture wait in auto re-arm so Stop is responsive

/** ELA run controls — Arm / Trigger Immediate / Auto re-arm / Stop, mirroring
 *  the desktop GUI. Reads the trigger config from the ELA tab and pushes each
 *  capture (as VCD) to the Viewer tab. */
export function RunPanel({ identity }: { identity: Identity }) {
  const { ela, pushCapture } = useSession();
  const [autoRearm, setAutoRearm] = useState(false);
  const [busy, setBusy] = useState(false); // a single capture in flight
  const [running, setRunning] = useState(false); // continuous loop active
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [overflow, setOverflow] = useState(false);
  const runRef = useRef(false); // synchronous stop flag for the loop

  function params(immediate: boolean, timeout: number) {
    return {
      channel: Number(ela.channel),
      pretrigger: Number(ela.pretrigger),
      posttrigger: Number(ela.posttrigger),
      trigger_mode: ela.triggerMode,
      trigger_value: parseIntFlexible(ela.triggerValue),
      trigger_mask: parseIntFlexible(ela.triggerMask),
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
    if (typeof r.vcd === "string") pushCapture(r.vcd);
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
    <div className="runbar">
      <span className="runbar-grip" title="Run controls" aria-hidden>
        ⠿
      </span>
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
      <span className="runbar-status">
        {error ? (
          <span className="err">{error}</span>
        ) : overflow ? (
          <span className="warn">overflow</span>
        ) : status ? (
          <span className="muted">{status}</span>
        ) : null}
      </span>
    </div>
  );
}
