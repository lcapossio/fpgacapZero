import { useRef, useState } from "react";
import { downloadText, parseProbesText, rpc } from "../api";
import type { Identity } from "../api";
import { useSession } from "../session";

const SINGLE_TIMEOUT = 10; // hardware wait (s) for a single capture
const CONT_TIMEOUT = 5; // shorter per-capture wait in auto re-arm so Stop is responsive
// JS numbers are exact only to 53 bits. Bit vectors (trigger value/mask) go over
// the wire as strings so wide values (e.g. 160-bit AXI samples) don't round; wide
// sample data uses the string-based VCD/CSV exports, not the JSON-number result.
const SAFE_SAMPLE_BITS = 53;

/** ELA run controls. Reads trigger config from the ELA tab and pushes captures
 *  to the Viewer tab. */
export function RunPanel({ identity }: { identity: Identity }) {
  const { ela, capture, pushCapture } = useSession();
  const [autoRearm, setAutoRearm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [overflow, setOverflow] = useState(false);
  const runRef = useRef(false);

  function params(immediate: boolean, timeout: number) {
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
    const r = await rpc("capture", params(immediate, timeout), timeout * 1000 + 4000);
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

  async function single(immediate: boolean) {
    setBusy(true);
    setError("");
    setStatus("");
    try {
      const n = await once(immediate, SINGLE_TIMEOUT);
      setStatus(`captured ${n} samples - see the Viewer tab`);
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
    runRef.current = false;
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

  const locked = busy || running;

  return (
    <div className="runbar">
      <div className="runbar-row">
        <span className="runbar-grip" title="Run controls" aria-hidden>
          ::
        </span>
        <button onClick={() => start(false)} disabled={locked}>
          {busy ? "Arming..." : "Arm"}
        </button>
        <button onClick={() => start(true)} disabled={locked}>
          Trigger Immediate
        </button>
        <button className="danger" onClick={stop} disabled={!running}>
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
      <div className="runbar-row runbar-downloads">
        <button className="secondary" onClick={() => download("vcd")} disabled={!capture?.vcd}>
          Download VCD
        </button>
        <button className="secondary" onClick={() => download("csv")} disabled={!capture?.csv}>
          Download CSV
        </button>
        <button
          className="secondary"
          onClick={() => download("json")}
          disabled={!capture?.json}
          title={
            capture && !capture.json
              ? "JSON export is off for wide captures (>53-bit) to avoid number rounding — use VCD or CSV."
              : undefined
          }
        >
          Download JSON
        </button>
      </div>
    </div>
  );
}
