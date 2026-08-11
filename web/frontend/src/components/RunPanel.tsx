import { useEffect, useRef, useState } from "react";
import { RpcCancelled, downloadText, parseProbesText, rpc } from "../api";
import type { Identity } from "../api";
import { describeElaTrigger } from "../signalTrigger";
import { useSession } from "../session";
import { vcdTimeAtSample } from "../vcdTime";

const IMMEDIATE_TIMEOUT = 10; // hardware wait (s) — Trigger Immediate fires at once
// Armed waits have NO deadline: the core is armed once and polled with short
// capture_wait calls until the trigger fires or the user stops. The short poll
// only bounds how long a single RPC blocks the server, keeping Stop responsive.
const POLL_TIMEOUT = 4;
// Gap between cheap trigger-status polls while armed. The poll itself is a
// single register read; this just paces it and bounds Stop latency.
const STATUS_POLL_MS = 120;

/** Sleep that rejects (RpcCancelled) the moment Stop aborts, so an armed wait
 *  ends now rather than after the next poll gap. */
function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new RpcCancelled("capture_status"));
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(new RpcCancelled("capture_status"));
      },
      { once: true },
    );
  });
}
// JS numbers are exact only to 53 bits. Bit vectors (trigger value/mask) go over
// the wire as strings so wide values (e.g. 160-bit AXI samples) don't round; wide
// sample data uses the string-based VCD/CSV exports, not the JSON-number result.
const SAFE_SAMPLE_BITS = 53;

/** Client-side readback budget (ms). The server has no readback deadline, but
 *  the client RPC needs one big enough for the whole buffer. Scale it with the
 *  sample-buffer size so a deep/wide core (e.g. a 160-bit AXI monitor) — or a
 *  slow per-word fallback transport — never hits a *false* timeout while the
 *  server is still streaming valid data. Fast burst/pipelined readback finishes
 *  far inside this; ~15 ms/word conservatively covers the slow fallback. */
function readbackBudgetMs(id: Identity | null): number {
  const sw = Number(id?.sample_width) || 8;
  const depth = Number(id?.depth) || 0;
  const words = depth * Math.ceil(sw / 32);
  return words * 15;
}

/** First-capture estimate of ms/sample for the readback progress, before a real
 *  rate has been measured: the slow per-word JTAG path runs ~4 ms per 32-bit
 *  word. Burst-capable narrow cores are far faster (and finish before the
 *  estimate matters); wide cores like the 160-bit monitor track this closely. */
function estMsPerSample(id: Identity | null): number {
  const sw = Number(id?.sample_width) || 8;
  return Math.ceil(sw / 32) * 4;
}

/** ELA run controls. Reads trigger config from the ELA tab and pushes captures
 *  to the active core's Viewer tab. `onActiveChange` reports when a capture is
 *  armed/running so a host (e.g. the hover-out Run bar) can stay open while the
 *  user might need Stop or the live status. */
export function RunPanel({
  identity: identityProp,
  onActiveChange,
}: {
  identity: Identity;
  onActiveChange?: (active: boolean) => void;
}) {
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
  // Measured readback rate (ms per sample) from the last capture, so the
  // "reading back" progress self-calibrates. Seeded per-capture from geometry.
  const readbackRateRef = useRef<number | null>(null);

  // A core switch invalidates the armed config — stop any armed wait.
  useEffect(() => {
    if (switching) {
      runRef.current = false;
      stopCtl.current?.abort();
    }
  }, [switching]);

  // Report armed/running so a hover-out host keeps itself open across the wait.
  useEffect(() => {
    onActiveChange?.(busy || running);
  }, [busy, running, onActiveChange]);

  function params(immediate: boolean, timeout: number) {
    const identity = identityRef.current;
    const sequence = ela.useSequencer ? JSON.parse(ela.sequenceJson || "[]") : undefined;
    // Immediate fires on sample 0, so there is no fresh pre-trigger history —
    // the server forces pretrigger=0 (else the pretrigger slots hold stale
    // samples with a backwards timestamp jump). Match it here so the trigger
    // marker (sample 0) lines up with what's captured. Fold the pre-trigger
    // depth into the post window so an immediate capture still grabs the same
    // total sample count as an armed one — same window, just no trigger.
    const pre = immediate ? 0 : Number(ela.pretrigger);
    const post = immediate
      ? Number(ela.pretrigger) + Number(ela.posttrigger)
      : Number(ela.posttrigger);
    return {
      channel: Number(ela.channel),
      pretrigger: pre,
      posttrigger: post,
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

  function submitCapture(r: Record<string, unknown>, triggerSample: number) {
    setOverflow(Boolean(r.overflow));
    if (typeof r.vcd === "string") {
      pushCapture({
        vcd: r.vcd,
        csv: typeof r.csv === "string" ? r.csv : undefined,
        json: r.result,
        sampleCount: r.sample_count as number | string | undefined,
        // The trigger sample is the `pretrigger`-th stored sample; the VCD emits
        // one `#time` line per sample in order, so its time is that line's — for
        // timestamped and plain captures alike (no index==time assumption).
        // Immediate captures have pretrigger=0, so the marker sits at sample 0.
        triggerTime: vcdTimeAtSample(r.vcd, triggerSample),
      });
    }
    return (r.sample_count as number | string | undefined) ?? "?";
  }

  /** Trigger Immediate: one bundled capture call — it fires right away. */
  async function immediateOnce() {
    const r = await rpc(
      "capture",
      params(true, IMMEDIATE_TIMEOUT),
      IMMEDIATE_TIMEOUT * 1000 + readbackBudgetMs(identityRef.current) + 4000,
      stopCtl.current?.signal,
    );
    return submitCapture(r, 0);
  }

  /** Arm once, then poll until the trigger fires — no deadline. The hardware
   *  stays armed across polls (capture_wait never re-arms), so nothing is
   *  missed between them; a poll timeout just means "still waiting". */
  async function armAndWait() {
    const p = params(false, POLL_TIMEOUT);
    const signal = stopCtl.current?.signal;
    await rpc("configure", p, 15000, signal);
    await rpc("arm", {}, 15000, signal);
    // Phase 1 — the real trigger wait: cheap status polls, no sample transfer.
    // The caller already shows "waiting for trigger"; hold it until the
    // hardware reports the trigger fired (or the capture already completed).
    for (;;) {
      const s = await rpc("capture_status", {}, 15000, signal);
      if (s.triggered || s.done) break;
      await sleep(STATUS_POLL_MS, signal);
    }
    // Phase 2 — the trigger has fired; the remaining wait is the sample
    // transfer, which for a wide/deep core (e.g. the 160-bit AXI monitor over
    // USB-Blaster) is the bulk of the time. Say so, instead of still claiming
    // to wait for a trigger that already passed.
    setWaiting(false);
    const nSamples = Number(p.pretrigger) + Number(p.posttrigger) + 1;
    // Live progress: the readback is one blocking JTAG transfer, so estimate the
    // sample count from elapsed time and the measured per-sample rate (exact
    // elapsed seconds shown alongside). The rate self-calibrates each capture,
    // so after the first readback the "~X of N" tracks closely.
    const start = performance.now();
    const rate = readbackRateRef.current ?? estMsPerSample(identityRef.current);
    const tick = () => {
      const elapsed = performance.now() - start;
      const done = Math.min(nSamples - 1, Math.floor(elapsed / rate));
      setStatus(
        `trigger fired - reading back ~${done} of ${nSamples} samples (${Math.round(elapsed / 1000)}s)`,
      );
    };
    tick();
    // Only tick for readbacks long enough to matter; short ones finish first.
    const timer = nSamples > 128 ? window.setInterval(tick, 300) : 0;
    try {
      const r = await rpc(
        "capture_wait",
        {
          timeout: POLL_TIMEOUT,
          segments: p.segments,
          format: p.format,
          include_vcd: true,
          include_csv: true,
        },
        POLL_TIMEOUT * 1000 + readbackBudgetMs(identityRef.current) + 6000,
        signal,
      );
      if (nSamples > 0) readbackRateRef.current = (performance.now() - start) / nSamples;
      return submitCapture(r, Number(ela.pretrigger));
    } finally {
      if (timer) window.clearInterval(timer);
    }
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
      const n = immediate ? await immediateOnce() : await armAndWait();
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
          const n = immediate ? await immediateOnce() : await armAndWait();
          setWaiting(false);
          count += 1;
          setStatus(`auto re-arm: ${count} captures (${n} samples)`);
        } catch (e) {
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
  // What Arm will actually fire on — decoded from the live config so it tracks
  // the trigger table, the AXI Mon tab and the raw fields alike.
  const triggerDesc = describeElaTrigger(ela, identityProp);

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
      <div className="runbar-trigger" title={`Arm fires on: ${triggerDesc}`}>
        <span className="runbar-trigger-label">⚡ trigger</span>
        <span className="runbar-trigger-cond">{triggerDesc}</span>
      </div>
    </div>
  );
}
