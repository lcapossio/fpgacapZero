import { useEffect, useRef } from "react";

// Vendored Surfer WASM build (mounted at /surfer). It loads a waveform when the
// parent posts {command:"LoadUrl", url}; further actions go through InjectMessage
// with a raw surfer::Message (an unstable API — kept to a tiny, known surface).
const SURFER_SRC = "/surfer/index.html";

// VCD scope name emitted by Analyzer.export_vcd_text ($scope module logic).
const VCD_SCOPE = "logic";
// Add every variable under that scope. id "None" is ScopeId::default — Surfer
// resolves the scope by its `strs` path (the same way it re-resolves saved
// state), so we don't need a backend-specific id.
const ADD_SCOPE = JSON.stringify({
  AddScope: [{ strs: [VCD_SCOPE], id: "None" }, true],
});
const ZOOM_FIT = JSON.stringify("ZoomToFit");

const SETTLE_MS = 450; // let the waveform parse before adding signals

/** Embed Surfer, load the capture as a VCD, and auto-add its signals. */
export function SurferView({ vcd }: { vcd: string }) {
  const ref = useRef<HTMLIFrameElement>(null);

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
    const post = (msg: unknown) => win()?.postMessage(msg, "*");

    let timers: number[] = [];
    let tries = 0;
    const start = () => {
      if (!ready()) {
        if (tries++ < 75) timers.push(window.setTimeout(start, 200)); // ~15s for WASM init
        return;
      }
      post({ command: "LoadUrl", url }); // load + Clear previous
      // After the waveform has parsed, add its signals and frame them.
      timers.push(
        window.setTimeout(() => {
          post({ command: "InjectMessage", message: ADD_SCOPE });
          post({ command: "InjectMessage", message: ZOOM_FIT });
        }, SETTLE_MS),
      );
    };
    start();

    return () => {
      timers.forEach((t) => window.clearTimeout(t));
      timers = [];
      URL.revokeObjectURL(url);
    };
  }, [vcd]);

  return (
    <div className="surfer-fill">
      <iframe ref={ref} title="Surfer" src={SURFER_SRC} className="surfer" />
    </div>
  );
}
