import { useEffect, useState } from "react";
import { RunPanel } from "./RunPanel";
import { useSession } from "../session";

/** The Run bar above the wave viewer. Pinned (the default) it docks as a real
 *  row that shares the vertical space with the waveform — no overlap. Unpinned
 *  it compresses to a small "▶ Run" tab and the Arm / Trigger Immediate / Stop
 *  controls slide down over the top of the waveform only while hovered (or
 *  while a capture is armed/running, so Stop and the live status stay reachable
 *  even if the pointer moves away). */
export function RunOverlay() {
  const { conn, identity } = useSession();
  const [hover, setHover] = useState(false);
  const [pinned, setPinned] = useState(true); // default: docked, sharing space
  const [active, setActive] = useState(false); // a capture is armed/running
  const open = pinned || hover || active;

  // Never leave the bar stuck open after a disconnect drops the RunPanel.
  useEffect(() => {
    if (!conn) setActive(false);
  }, [conn]);

  return (
    <div
      className={`run-overlay${open ? " open" : ""}${pinned ? " pinned" : ""}`}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <div className="run-drawer">
        {conn && identity ? (
          <RunPanel identity={identity} onActiveChange={setActive} />
        ) : (
          <div className="run-empty muted">Connect to a target first.</div>
        )}
        <button
          className={`run-pin${pinned ? " on" : ""}`}
          onClick={() => setPinned((p) => !p)}
          title={
            pinned
              ? "Unpin — collapse to a rail; hover to peek"
              : "Pin — dock the Run bar and share space with the viewer"
          }
          aria-pressed={pinned}
        >
          📌
        </button>
      </div>
      <div className="run-rail" title="Run controls">
        <span className="run-rail-label">▶ Run</span>
      </div>
    </div>
  );
}
