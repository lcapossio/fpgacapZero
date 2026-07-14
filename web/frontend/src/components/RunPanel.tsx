import { useEffect, useRef, useState } from "react";
import { RpcCancelled, RpcError, downloadText, parseProbesText, rpc } from "../api";
import type { Identity } from "../api";
import { useSession } from "../session";

const SINGLE_TIMEOUT = 10; // hardware wait (s) for a single capture
const CONT_TIMEOUT = 5; // shorter per-capture wait in auto re-arm so Stop is responsive
// JS numbers are exact only to 53 bits. Bit vectors (trigger value/mask) go over
// the wire as strings so wide values (e.g. 160-bit AXI samples) don't round; wide
// sample data uses the string-based VCD/CSV exports, not the JSON-number result.
const SAFE_SAMPLE_BITS = 53;

/** ELA run controls. Reads trigger config from the ELA tab and pushes captures
 *  to the active core's Viewer tab. */
export function RunPanel({ identity: identityProp }: { identity: Identity }) {
  const { ela, captures, pushCapture, conn, switching } = useSession();
  const capture = conn ? captures[conn.chain] : undefined;
  const [autoRearm, setAutoRearm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [waiting, setWaiting] = useState(false); // armed, trigger not fired yet
  const [overflow, setOverflow] = useState(false);
  const runRef = useRef(false);
  // Stop aborts the in-flight capture request so an armed wait ends now, not
  // at its timeout; the core itself is then disarmed server-side.
  const stopCtl = useRef<AbortController | null>(null);
  // The auto re-arm loop is a long-lived closure; read the identity through a
  // ref so a core switch mid-loop can't send another core's geometry.
  const identityRef = useRef(identityProp);
  identityRef.current = identityProp;

  // A core switch invalidates the armed config — stop the re-arm loop.
  useEffect(() => {
    if (switching) runRef.current = false;
  }, [switching]);

  function params(immediate: boolean, timeout: number) {
    const identity = identityRef.current;
    const sequence = ela.useSequencer ? JSON.parse(ela.sequenceJson || "[]") : undefined;
    return {
      channel: Number(ela.channel),
      pretrigger: Number(ela.pretrigger),
      posttrigger: Number(ela.posttrigger),
      trigger_mode: ela.triggerMode,
      // Send as strings (hex or decimal); the backend parses with full precision.
      trigger_value: ela.triggerValue.trim() || "0",
      trigger_mask: ela.triggerMask.trim() || "0",
      ext_trigger_mode: Number(ela.extTriggerMode),
      sequence,
      segments: ela.segmented,
      probes: parseProbesText(ela.probesText),
      sample_width: identity.sample_width,
      depth: identity.depth,
      timeout,
      immediate,
      // Wide captures can't round-trip through JSON numbers safely — request the
      // lossless VCD as the primary result and skip the JSON-number samples.
      format: identity.sample_width > SAFE_SAMPLE_BITS ? "vcd" : "json",
      include_vcd: true,
      include_csv: true,
    };
  }

  async function once(immediate: boolean, timeout: number) {
    const r = await rpc(
      "capture",
      params(immediate, timeout),
      timeout * 1000 + 4000,
      stopCtl.current?.signal,
    );
    setOverflow(Boolean(r.overflow));
    if (typeof r.vcd === "string") {
      pushCapture({
        vcd: r.vcd,
        csv: typeof r.csv === "string" ? r.csv : undefined,
        json: r.result,
        sampleCount: r.sample_count as number | string | undefined,
      });
    }
    return r.sample_count ?? "?";
  }

  /** Disarm the core after a stopped wait (queues behind the in-flight
   *  capture command server-side; best-effort). */
  function disarm() {
    rpc("disarm", {}, 20000).catch(() => {});
  }

  async function single(immediate: boolean) {
    setBusy(true);
    setError("");
    setStatus("");
    stopCtl.current = new AbortController();
    try {
      if (!immediate) {
        setWaiting(true);
        setStatus("armed - waiting for trigger");
      }
      const n = await once(immediate, SINGLE_TIMEOUT);
      setStatus(`captured ${n} samples - see the Viewer tab`);
    } catch (e) {
      if (e instanceof RpcCancelled) {
        setStatus("stopped - disarmed");
        disarm();
      } else {
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      stopCtl.current = null;
      setWaiting(false);
      setBusy(false);
    }
  }

  async function loop(immediate: boolean) {
    setError("");
    setRunning(true);
    runRef.current = true;
    stopCtl.current = new AbortController();
    let count = 0;
    try {
      while (runRef.current) {
        try {
          if (!immediate) {
            setWaiting(true);
            setStatus(
              count
                ? `auto re-arm: armed - waiting for trigger (${count} captures)`
                : "auto re-arm: armed - waiting for trigger",
            );
          }
          const n = await once(immediate, CONT_TIMEOUT);
          setWaiting(false);
          count += 1;
          setStatus(`auto re-arm: ${count} captures (${n} samples)`);
        } catch (e) {
          // The short per-capture timeout only exists to keep Stop responsive;
          // a trigger that didn't fire inside one window just means re-arm.
          if (e instanceof RpcError && e.type === "TimeoutError") {
            continue;
          }
          if (e instanceof RpcCancelled) {
            setStatus(`stopped after ${count} captures - disarmed`);
            disarm();
            return;
          }
          throw e;
        }
      }
      setStatus(`stopped after ${count} captures - disarmed`);
      disarm();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      runRef.current = false;
      stopCtl.current = null;
      setWaiting(false);
      setRunning(false);
    }
  }

  function start(immediate: boolean) {
    if (autoRearm) loop(immediate);
    else single(immediate);
  }

  function stop() {
    runRef.current = false;
    stopCtl.current?.abort(); // ends the armed wait now, not at its timeout
    setStatus("stopping...");
  }

  function download(format: "vcd" | "csv" | "json") {
    if (!capture) return;
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    if (format === "vcd") {
      downloadText(`fcapz-capture-${stamp}.vcd`, capture.vcd, "text/plain");
    } else if (format === "csv" && capture.csv) {
      downloadText(`fcapz-capture-${stamp}.csv`, capture.csv, "text/csv");
    } else if (format === "json") {
      downloadText(
        `fcapz-capture-${stamp}.json`,
        JSON.stringify(capture.json ?? {}, null, 2),
        "application/json",
      );
    }
  }

  const locked = busy || running || switching;

  return (
    <div className="runbar">
      <div className="runbar-row">
        <button onClick={() => start(false)} disabled={locked}>
          {busy ? "Arming..." : "Arm"}
        </button>
        <button onClick={() => start(true)} disabled={locked}>
          Trigger Immediate
        </button>
        <button className="danger" onClick={stop} disabled={!running && !busy}>
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
        {/* One compact control for all export formats — a native select so
            the popup can't be clipped by the slim panel. Always shows the
            placeholder; picking a format downloads and resets. */}
        <select
          className="runbar-download"
          value=""
          disabled={!capture}
          title={
            capture && !capture.json
              ? "JSON export is off for wide captures (>53-bit) to avoid number rounding — use VCD or CSV."
              : undefined
          }
          onChange={(e) => {
            const f = e.target.value as "vcd" | "csv" | "json" | "";
            if (f) download(f);
          }}
        >
          <option value="" disabled hidden>
            Download…
          </option>
          <option value="vcd" disabled={!capture?.vcd}>
            VCD
          </option>
          <option value="csv" disabled={!capture?.csv}>
            CSV
          </option>
          <option value="json" disabled={!capture?.json}>
            JSON
          </option>
        </select>
        <span className="runbar-status">
          {error ? (
            <span className="err">{error}</span>
          ) : overflow ? (
            <span className="warn">overflow</span>
          ) : status ? (
            <span className={waiting ? "armed" : "muted"}>
              {waiting && <span className="armdot" />}
              {status}
            </span>
          ) : null}
        </span>
      </div>
    </div>
  );
}
