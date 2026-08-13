import { useState } from "react";
import { LogPanel } from "./LogPanel";

/** Backend log drawer under the wave viewer. Auto-hidden by default: only a
 *  thin "▤ Log" rail shows on the viewer's bottom edge, and the log slides up
 *  over the waveform while hovered. Pin it to dock as a real row that shares the
 *  vertical space with the waveform (always visible). Mirror of the Run bar. */
export function LogOverlay() {
  const [hover, setHover] = useState(false);
  const [pinned, setPinned] = useState(false); // default: auto-hide, peek on hover
  const open = pinned || hover;

  return (
    <div
      className={`log-overlay${open ? " open" : ""}${pinned ? " pinned" : ""}`}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <div className="log-rail" title="Backend log">
        <span className="log-rail-label">▤ Log</span>
      </div>
      <div className="log-drawer">
        <LogPanel pinned={pinned} onTogglePin={() => setPinned((p) => !p)} />
      </div>
    </div>
  );
}
