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

const SETTLE_MS = 450; // let the first waveform parse before adding signals

/** Embed Surfer once and, per capture, swap the waveform in place — keeping the
 *  same window, displayed signals and zoom (only the first capture sets them up). */
export function SurferView({ vcd }: { vcd: string }) {
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
      // First capture: clear and (after it parses) add the signals + fit.
      // Later captures: KeepAvailable re-uses the displayed signals and view —
      // the window doesn't relaunch, the data just updates.
      inject({ LoadWaveformFileFromUrl: [url, first ? "Clear" : "KeepAvailable"] });
      if (first) {
        firstLoad.current = false;
        timers.push(
          window.setTimeout(() => {
            inject(ADD_SCOPE);
            inject("ZoomToFit");
          }, SETTLE_MS),
        );
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
