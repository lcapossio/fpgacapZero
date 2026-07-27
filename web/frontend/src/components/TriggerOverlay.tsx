import { useState } from "react";
import { TriggerPanel } from "./TriggerPanel";

/** A slide-out Trigger drawer pinned to the right edge of the wave viewer.
 *  Collapsed it's a thin vertical rail; hovering the rail (or pinning it)
 *  slides the full Trigger Setup out over the waveform. Moving the pointer off
 *  the drawer collapses it again unless it's pinned open. */
export function TriggerOverlay() {
  const [hover, setHover] = useState(false);
  const [pinned, setPinned] = useState(false);
  // Keep the drawer open while any control inside it holds focus. Opening a
  // native <select> (e.g. "+ Add probe…") renders its dropdown outside the
  // drawer's box, so the pointer leaving fires onMouseLeave and would collapse
  // the drawer mid-pick; focus stays on the control, so this keeps it open.
  const [focusWithin, setFocusWithin] = useState(false);
  const open = hover || pinned || focusWithin;

  return (
    <div
      className={`trig-overlay${open ? " open" : ""}`}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onFocusCapture={() => setFocusWithin(true)}
      onBlurCapture={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setFocusWithin(false);
      }}
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
