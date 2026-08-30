import { useEffect, useRef, useState } from "react";
import { fetchLogs, type LogLine } from "../api";

const POLL_MS = 1000;
const MAX_LINES = 5000; // cap the client-side view; the server ring is bounded too

/** Log tab: tails the backend's fcapz log ring (GET /api/logs) so JTAG
 *  diagnostics — readback fallbacks, connection notices, transport warnings —
 *  are visible in the browser, not just on the server's stderr. Polls for new
 *  records by sequence number; Pause freezes the view and auto-scroll.
 *
 *  When hosted in the hover drawer, the overlay passes its pin state so the pin
 *  toggle sits inline with the controls instead of floating in a corner. */
export function LogPanel({
  pinned,
  onTogglePin,
}: {
  pinned?: boolean;
  onTogglePin?: () => void;
} = {}) {
  const [lines, setLines] = useState<LogLine[]>([]);
  const [paused, setPaused] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const [err, setErr] = useState("");
  const sinceRef = useRef(0);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;
  const viewRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    let alive = true;
    const ctl = new AbortController();
    async function tick() {
      if (pausedRef.current) return;
      try {
        const snap = await fetchLogs(sinceRef.current, ctl.signal);
        if (!alive) return;
        sinceRef.current = snap.next;
        if (snap.lines.length) {
          setLines((prev) => {
            const merged = prev.concat(snap.lines);
            return merged.length > MAX_LINES ? merged.slice(merged.length - MAX_LINES) : merged;
          });
        }
        setErr("");
      } catch (e) {
        if (alive && !(e instanceof DOMException && e.name === "AbortError")) {
          setErr(e instanceof Error ? e.message : String(e));
        }
      }
    }
    tick();
    const timer = window.setInterval(tick, POLL_MS);
    return () => {
      alive = false;
      ctl.abort();
      window.clearInterval(timer);
    };
  }, []);

  // Follow the tail on new lines while auto-scroll is on. Scroll the log's own
  // container (not scrollIntoView, which would scroll every ancestor — yanking
  // the whole viewport when the drawer is collapsed off-screen).
  useEffect(() => {
    if (autoScroll && viewRef.current) {
      viewRef.current.scrollTop = viewRef.current.scrollHeight;
    }
  }, [lines, autoScroll]);

  return (
    <section className="panel logpanel">
      <div className="btnrow">
        <button className="secondary" onClick={() => setPaused((p) => !p)}>
          {paused ? "Resume" : "Pause"}
        </button>
        <button className="secondary" onClick={() => setLines([])}>
          Clear view
        </button>
        <label className="inline log-autoscroll">
          <input
            type="checkbox"
            checked={autoScroll}
            onChange={(e) => setAutoScroll(e.target.checked)}
          />
          Auto-scroll
        </label>
        {err && <span className="error">{err}</span>}
        {onTogglePin && (
          <button
            className={`log-pin${pinned ? " on" : ""}`}
            onClick={onTogglePin}
            title={
              pinned
                ? "Unpin — collapse to a rail; hover to peek"
                : "Pin — dock the Log and share space with the viewer"
            }
            aria-pressed={pinned}
          >
            📌
          </button>
        )}
      </div>
      <div className="logview" ref={viewRef}>
        {lines.length === 0 ? (
          <p className="muted">
            No log output yet. Backend diagnostics (JTAG readback, connection,
            warnings) appear here as they happen.
          </p>
        ) : (
          lines.map((l) => (
            <div key={l.seq} className={`logline lvl-${l.level.toLowerCase()}`}>
              <span className="logtime">
                {new Date(l.ts * 1000).toLocaleTimeString()}
              </span>
              <span className="loglevel">{l.level}</span>
              <span className="logname">{l.name.replace(/^fcapz\.?/, "")}</span>
              <span className="logmsg">{l.msg}</span>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
