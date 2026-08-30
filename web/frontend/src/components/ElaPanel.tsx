import { useSession } from "../session";

/** ELA capture configuration: window geometry and probe naming. Trigger
 *  conditions live in the Trigger drawer; run controls in the Run bar.
 *
 *  Window geometry is expressed as a total sample count plus the trigger's
 *  1-based position within it — more intuitive than raw pre/post counts. The
 *  wire protocol still takes pretrigger/posttrigger, so they are derived here:
 *  pretrigger = position - 1, posttrigger = window - position (trigger sample
 *  included), keeping window = pretrigger + posttrigger + 1. */
export function ElaPanel() {
  const { ela, setEla, identity } = useSession();

  const pre = Math.max(0, Math.floor(Number(ela.pretrigger) || 0));
  const post = Math.max(0, Math.floor(Number(ela.posttrigger) || 0));
  const windowLen = pre + post + 1;
  const triggerPos = pre + 1; // 1-based index of the trigger sample in the window
  const seg = Math.max(1, Number(identity?.num_segments) || 1);
  // A single capture must fit one segment; the usable window is depth/segments.
  const maxWindow = Math.max(1, Math.floor((Number(identity?.depth) || windowLen) / seg));

  function applyWindow(next: number) {
    const w = Math.min(Math.max(1, Math.floor(next || 1)), maxWindow);
    const pos = Math.min(Math.max(1, triggerPos), w); // keep the trigger position
    setEla({ pretrigger: String(pos - 1), posttrigger: String(w - pos) });
  }
  function applyPos(next: number) {
    const pos = Math.min(Math.max(1, Math.floor(next || 1)), windowLen);
    setEla({ pretrigger: String(pos - 1), posttrigger: String(windowLen - pos) });
  }

  async function loadProbeFile(file: File | undefined) {
    if (!file) return;
    setEla({ probesText: await file.text() });
  }

  return (
    <section className="panel">
      <div className="form">
        <label>
          Channel
          <input
            value={ela.channel}
            onChange={(e) => setEla({ channel: e.target.value })}
          />
        </label>
        <label>
          Samples (window)
          <input
            type="number"
            min={1}
            max={maxWindow}
            value={windowLen}
            onChange={(e) => applyWindow(Number(e.target.value))}
          />
        </label>
        <label>
          Trigger position
          <input
            type="number"
            min={1}
            max={windowLen}
            value={triggerPos}
            onChange={(e) => applyPos(Number(e.target.value))}
          />
        </label>
        <label className="inline">
          <input
            type="checkbox"
            checked={ela.segmented}
            onChange={(e) => setEla({ segmented: e.target.checked })}
          />
          Read all segments
        </label>
      </div>
      <input
        type="range"
        min={1}
        max={windowLen}
        value={triggerPos}
        onChange={(e) => applyPos(Number(e.target.value))}
        aria-label="Trigger position in window"
        style={{ width: "100%" }}
      />
      <p className="muted">
        {pre} pre · trigger @ {triggerPos} · {post} post — {windowLen} samples
        {maxWindow > 1 ? ` (max ${maxWindow})` : ""}
      </p>
      {identity?.num_segments ? (
        <p className="muted">Hardware segments: {identity.num_segments}</p>
      ) : null}

      <h3>Probe definitions</h3>
      <div className="btnrow">
        <label className="filepick">
          Load .prob
          <input
            type="file"
            accept=".prob,.json,text/plain"
            onChange={(e) => loadProbeFile(e.target.files?.[0])}
          />
        </label>
        <button className="secondary" onClick={() => setEla({ probesText: "" })}>
          Clear probes
        </button>
      </div>
      <label>
        Named signals
        <textarea
          value={ela.probesText}
          onChange={(e) => setEla({ probesText: e.target.value })}
          placeholder="valid:1:0&#10;state:7:1"
          spellCheck={false}
        />
      </label>
      <p className="muted">
        Set the trigger in the Trigger drawer (hover the ⚡ Trigger rail on the
        viewer&apos;s edge); run captures from the Run bar.
      </p>
    </section>
  );
}
