import { useSession } from "../session";

/** ELA trigger/capture configuration. Run controls (Arm / Trigger Immediate /
 *  Auto re-arm / Stop) live in the Run tab and read this shared config. */
export function ElaPanel() {
  const { ela, setEla } = useSession();

  return (
    <section className="panel">
      <h2>ELA config</h2>
      <div className="form">
        <label>
          Channel
          <input
            value={ela.channel}
            onChange={(e) => setEla({ channel: e.target.value })}
          />
        </label>
        <label>
          Pre
          <input
            value={ela.pretrigger}
            onChange={(e) => setEla({ pretrigger: e.target.value })}
          />
        </label>
        <label>
          Post
          <input
            value={ela.posttrigger}
            onChange={(e) => setEla({ posttrigger: e.target.value })}
          />
        </label>
        <label>
          Mode
          <select
            value={ela.triggerMode}
            onChange={(e) => setEla({ triggerMode: e.target.value })}
          >
            <option value="value_match">value_match</option>
            <option value="edge_detect">edge_detect</option>
            <option value="both">both</option>
          </select>
        </label>
        <label>
          Trigger value
          <input
            value={ela.triggerValue}
            onChange={(e) => setEla({ triggerValue: e.target.value })}
          />
        </label>
        <label>
          Trigger mask
          <input
            value={ela.triggerMask}
            onChange={(e) => setEla({ triggerMask: e.target.value })}
          />
        </label>
      </div>
      <p className="muted">Run captures from the Run tab.</p>
    </section>
  );
}
