import { useEffect, useRef } from "react";

// Vendored Surfer WASM build (mounted at /surfer). We drive it via InjectMessage
// (a small, known surface of the otherwise-unstable surfer::Message API).
const SURFER_SRC = "/surfer/index.html";

// VCD scope name emitted by Analyzer.export_vcd_text ($scope module logic).
const VCD_SCOPE = "logic";
// Add every variable under that scope. id "None" is ScopeId::default — Surfer
// resolves the scope by its `strs` path (the same way it re-resolves saved
// state), so we don't need a backend-specific id.
const ADD_SCOPE = { AddScope: [{ strs: [VCD_SCOPE], id: "None" }, true] };
// ZoomToFit is a STRUCT variant in this Surfer build (not the bare "ZoomToFit"
// unit string, which fails to deserialise): it needs a viewport index.
const ZOOM_TO_FIT = { ZoomToFit: { viewport_idx: 0 } };
// The VCD uses one time unit per sample, so axis numbers are sample indices.
// "No" formatting keeps them raw (no SI rescale to µs/ms on deep captures), so a
// big sample count still reads as its plain sample number. Surfer has no
// "samples" unit, so the axis is still suffixed "ns" — the number is the sample.
const RAW_TIME_UNITS = { SetTimeStringFormatting: "No" };

const SETTLE_MS = 450; // let the first waveform parse before adding signals
// Marker and scope both arrive as messages; injecting them back-to-back lets the
// scope land first and pushes the marker to the end of the item list. A short gap
// guarantees the marker is item 0 (so we can colour exactly it, not a signal).
const MARKER_GAP_MS = 120;

// Surfer's fixed marker id for the trigger. AddMarker creates it (with a name);
// SetMarker(id) upserts by this id on later captures, so it never stacks.
const TRIGGER_MARKER_ID = 0;

/** Encode a non-negative integer as Surfer's `time` field: num-bigint's
 *  `(Sign, BigUint)` tuple, `[sign, [u32 digits little-endian]]`, where Sign is
 *  the i8 -1/0/1. Verified against the vendored WASM. */
function bigIntTime(n: number): [number, number[]] {
  let v = Math.max(0, Math.floor(n));
  if (v === 0) return [0, []]; // NoSign, no digits
  const digits: number[] = [];
  while (v > 0) {
    digits.push(v >>> 0); // low 32 bits
    v = Math.floor(v / 0x1_0000_0000);
  }
  return [1, digits]; // Plus
}

// Create the trigger marker: a STATIC named vertical line pinned to the trigger
// sample. Unlike the cursor it does not move when the user clicks in the
// waveform. It is injected before AddScope so it becomes item 0, letting us
// colour it (and only it) yellow — distinct from the red movable cursor.
function addTriggerMarker(time: number) {
  return { AddMarker: { time: bigIntTime(time), name: "trigger", move_focus: false } };
}

// Move the existing trigger marker (upsert by id) — keeps the name from
// AddMarker and does not add a second marker on re-captures.
function moveTriggerMarker(time: number) {
  return { SetMarker: { id: TRIGGER_MARKER_ID, time: bigIntTime(time) } };
}

// Paint the trigger marker (item 0) yellow so it reads apart from the red cursor.
const COLOR_TRIGGER = { ItemColorChange: [{ Explicit: TRIGGER_MARKER_ID }, "Yellow"] };

/** Embed Surfer once and, per capture, swap the waveform in place — keeping the
 *  same window, displayed signals and zoom (only the first capture sets them up). */
export function SurferView({ vcd, triggerTime }: { vcd: string; triggerTime?: number }) {
  const ref = useRef<HTMLIFrameElement>(null);
  const firstLoad = useRef(true);

  useEffect(() => {
    if (!vcd) return;
    const blob = new Blob([vcd], { type: "text/plain" });
    const url = URL.createObjectURL(blob);

    const win = () =>
      ref.current?.contentWindow as
        | (Window & { inject_message?: unknown })
        | null
        | undefined;
    const ready = (): boolean => {
      try {
        return typeof win()?.inject_message === "function";
      } catch {
        return false; // transient during iframe/WASM load
      }
    };
    // InjectMessage carries a raw surfer::Message (object or unit-variant string).
    const inject = (msg: unknown) =>
      win()?.postMessage({ command: "InjectMessage", message: JSON.stringify(msg) }, "*");

    const timers: number[] = [];
    let tries = 0;
    const start = () => {
      if (!ready()) {
        if (tries++ < 75) timers.push(window.setTimeout(start, 200)); // ~15s for WASM init
        return;
      }
      const first = firstLoad.current;
      const hasTrigger = triggerTime != null && triggerTime >= 0;
      // First capture: clear and (after it parses) add the signals + fit.
      // Later captures: KeepAvailable re-uses the displayed signals and view —
      // the window doesn't relaunch, the data just updates.
      inject({ LoadWaveformFileFromUrl: [url, first ? "Clear" : "KeepAvailable"] });
      if (first) {
        timers.push(
          window.setTimeout(() => {
            // Add the marker first (item 0) so the trigger line exists before
            // any signal — a short gap keeps the scope from re-ordering it.
            if (hasTrigger) inject(addTriggerMarker(triggerTime));
            timers.push(
              window.setTimeout(() => {
                inject(ADD_SCOPE);
                inject(RAW_TIME_UNITS);
                inject(ZOOM_TO_FIT);
                if (hasTrigger) inject(COLOR_TRIGGER);
                // Only now is the view set up. Flipping this before the timer
                // fires would let a quick second capture cancel the setup and
                // leave every later load with no displayed signals.
                firstLoad.current = false;
              }, MARKER_GAP_MS),
            );
          }, SETTLE_MS),
        );
      } else if (hasTrigger) {
        // Reload keeps the signals/view; move the same marker to the new trigger.
        timers.push(window.setTimeout(() => inject(moveTriggerMarker(triggerTime)), SETTLE_MS));
      }
    };
    start();

    return () => {
      timers.forEach((t) => window.clearTimeout(t));
      URL.revokeObjectURL(url);
    };
  }, [vcd]);

  return (
    <div className="surfer-fill">
      <iframe ref={ref} title="Surfer" src={SURFER_SRC} className="surfer" />
    </div>
  );
}
