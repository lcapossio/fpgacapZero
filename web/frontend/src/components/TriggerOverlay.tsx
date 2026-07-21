import { useState } from "react";
import { TriggerPanel } from "./TriggerPanel";

/** A slide-out Trigger drawer pinned to the right edge of the wave viewer.
 *  Collapsed it's a thin vertical rail; hovering the rail (or pinning it)
 *  slides the full Trigger Setup out over the waveform. Moving the pointer off
 *  the drawer collapses it again unless it's pinned open. */
export function TriggerOverlay() {
  const [hover, setHover] = useState(false);
  const [pinned, setPinned] = useState(false);
  const open = hover || pinned;

  return (
    <div
      className={`trig-overlay${open ? " open" : ""}`}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <div className="trig-rail" title="Trigger setup">
        <span className="trig-rail-label">⚡ Trigger</span>
      </div>
      <aside className="trig-drawer" aria-hidden={!open}>
        <div className="trig-drawer-head">
          <span className="trig-drawer-title">Trigger</span>
          <button
            className={`trig-pin${pinned ? " on" : ""}`}
            onClick={() => setPinned((p) => !p)}
            title={pinned ? "Unpin — auto-hide on mouse-out" : "Pin open"}
            aria-pressed={pinned}
          >
            📌
          </button>
        </div>
        <div className="trig-drawer-body">
          <TriggerPanel />
        </div>
      </aside>
    </div>
  );
}
