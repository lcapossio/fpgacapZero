import { useEffect, useRef } from "react";

// Vendored Surfer WASM build (host/fcapz/web/static/surfer/). It loads a
// waveform when the parent posts {command:"LoadUrl", url} to the iframe.
const SURFER_SRC = "/surfer/index.html";

/** Embed Surfer and hand it the capture as a VCD blob URL. */
export function SurferView({ vcd }: { vcd: string }) {
  const ref = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    if (!vcd) return;
    const blob = new Blob([vcd], { type: "text/plain" });
    const url = URL.createObjectURL(blob);

    // Surfer's `inject_message` is only defined on the iframe window *after*
    // its WASM init finishes; posting LoadUrl before that is silently dropped.
    // Poll the (same-origin) iframe until it's ready, then post exactly once —
    // no blind retry loop that would re-Clear and reset the user's view.
    let timer: number | undefined;
    let tries = 0;
    const ready = (): boolean => {
      try {
        const w = ref.current?.contentWindow as
          | (Window & { inject_message?: unknown })
          | null
          | undefined;
        return typeof w?.inject_message === "function";
      } catch {
        return false; // transient during load
      }
    };
    const post = () => {
      if (ready()) {
        ref.current?.contentWindow?.postMessage({ command: "LoadUrl", url }, "*");
        return;
      }
      if (tries++ < 75) timer = window.setTimeout(post, 200); // ~15s for WASM init
    };
    post();

    return () => {
      if (timer) window.clearTimeout(timer);
      URL.revokeObjectURL(url);
    };
  }, [vcd]);

  return (
    <div className="waveform">
      <iframe ref={ref} title="Surfer" src={SURFER_SRC} className="surfer" />
    </div>
  );
}
